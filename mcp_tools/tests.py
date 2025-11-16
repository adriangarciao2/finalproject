"""MCP helper tools for Java test generation and running Maven tests.

Functions provided:
- analyze_java_sources(project_root: str) -> list
  Walk Java sources and return simple class+method signatures.
- generate_junit_tests(class_infos: list, project_root: str) -> list
  Create JUnit 5 test skeletons under `src/test/java/...` and return file paths.
- run_maven_tests(project_root: str) -> dict
  Run `mvn test` (or project wrapper) and return structured results.

This module is intentionally lightweight and uses regex-based parsing for
source analysis. It is suitable as a FastMCP tool implementation.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple


def analyze_java_sources(project_root: str) -> List[Dict]:
    """Scan Java source files and extract simple class + method signatures.

    Args:
        project_root: path to project root (str)

    Returns:
        List of dicts: {
            'file': str, 'package': str or None, 'class': classname, 'methods': [ {'name':..., 'signature':...}, ... ]
        }
    """
    root = Path(project_root)
    java_files = list(root.rglob("*.java"))
    results = []

    class_re = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)")
    package_re = re.compile(r"^\s*package\s+([a-zA-Z0-9_.]+)\s*;", re.M)
    # very broad method regex: visibility + return type + name + params
    method_re = re.compile(r"\b(public|protected|private)\s+([\w<>, \[\]]+)\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(([^)]*)\)")

    for f in java_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue

        package = None
        m = package_re.search(text)
        if m:
            package = m.group(1)

        classes = class_re.findall(text)
        # If file contains multiple classes, we'll create an entry per top-level class name found.
        for cls in classes:
            methods = []
            for mm in method_re.finditer(text):
                visibility, ret_type, name, params = mm.groups()
                sig = f"{visibility} {ret_type} {name}({params.strip()})"
                methods.append({"name": name, "signature": sig})

            results.append({
                "file": str(f.relative_to(root)),
                "package": package,
                "class": cls,
                "methods": methods,
            })

    return results


def _package_to_path(package: str) -> str:
    return package.replace(".", os.sep) if package else ""


def generate_junit_tests(class_infos: List[Dict], project_root: str) -> List[str]:
    """Generate JUnit 5 test skeletons for given class infos.

    Args:
        class_infos: output from analyze_java_sources()
        project_root: path where to create `src/test/java/...`

    Returns:
        List of file paths (strings) created.
    """
    root = Path(project_root)
    created: List[str] = []
    test_root = root / "src" / "test" / "java"

    for info in class_infos:
        package = info.get("package")
        class_name = info.get("class")
        test_class_name = f"{class_name}Test"

        if package:
            package_path = test_root / _package_to_path(package)
        else:
            package_path = test_root

        package_path.mkdir(parents=True, exist_ok=True)

        file_path = package_path / f"{test_class_name}.java"
        # Build file contents
        lines: List[str] = []
        if package:
            lines.append(f"package {package};")
            lines.append("")

        lines.append("import org.junit.jupiter.api.Test;")
        lines.append("import static org.junit.jupiter.api.Assertions.*;")
        lines.append("")
        lines.append(f"public class {test_class_name} {{")

        # For each method, generate a placeholder test
        methods = info.get("methods", [])
        if not methods:
            # Add a basic smoke test
            lines.append("    @Test")
            lines.append("    void smokeTest() {")
            lines.append("        // TODO: implement test")
            lines.append("        assertTrue(true);")
            lines.append("    }")
        else:
            for m in methods:
                test_name = f"test_{m['name']}"
                lines.append("    @Test")
                lines.append(f"    void {test_name}() {{")
                lines.append("        // TODO: implement test for: {}".format(m.get("signature")))
                lines.append("        // Example: create instance and call method")
                lines.append(f"        // {class_name} sut = new {class_name}();")
                lines.append("        // assertEquals(expected, sut.{name}(...));".format(name=m["name"]))
                lines.append("    }")

        lines.append("}")

        file_text = "\n".join(lines) + "\n"
        file_path.write_text(file_text, encoding="utf-8")
        created.append(str(file_path.relative_to(root)))

    return created


def run_maven_tests(project_root: str, timeout: int = 300) -> Dict:
    """Run `mvn test` (or project wrapper) and return structured results.

    The function will prefer the project Maven wrapper if present (`mvnw` / `mvnw.cmd`).

    Returns a dict with keys:
      - success: bool
      - return_code: int
      - failed_tests: list[str]
      - raw_output: str
    """
    root = Path(project_root)
    # Prefer wrapper if available
    is_windows = os.name == "nt"
    if is_windows and (root / "mvnw.cmd").exists():
        cmd = [str(root / "mvnw.cmd"), "test"]
    elif (root / "mvnw").exists():
        # use the wrapper script
        cmd = [str(root / "mvnw"), "test"]
    else:
        cmd = ["mvn", "test"]

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        return {
            "success": False,
            "return_code": -1,
            "failed_tests": ["timeout"],
            "raw_output": str(e),
        }

    raw = proc.stdout or ""
    success = proc.returncode == 0

    failed_tests: List[str] = []

    # Attempt to find a 'Failed tests:' section (common in Surefire output)
    m = re.search(r"(?:\[INFO\]\s*)?Failed tests:\s*(.*?)\n\s*\n", raw, re.S)
    if m:
        section = m.group(1)
        for line in section.splitlines():
            line = line.strip()
            if not line:
                continue
            # Many times the line starts with the test name; strip any trailing info
            failed_tests.append(line.split()[0])

    # Alternative heuristic: lines that begin with "Tests run:" report failures counts
    if not failed_tests:
        for line in raw.splitlines():
            line = line.strip()
            # Example: "Tests run: 1, Failures: 1, Errors: 0, Skipped: 0"
            m2 = re.match(r"Tests run:.*Failures:\s*(\d+).*(Errors:\s*(\d+))?", line)
            if m2:
                failures = int(m2.group(1))
                if failures > 0:
                    # we couldn't extract names, add a placeholder
                    failed_tests.append(f"{failures} failing tests (names unavailable)")

    if not success and not failed_tests:
        failed_tests = ["unknown failures - see raw_output"]

    return {
        "success": success,
        "return_code": proc.returncode,
        "failed_tests": failed_tests,
        "raw_output": raw,
    }


if __name__ == "__main__":
    # quick smoke when invoked directly
    import json
    root = os.getcwd()
    print(json.dumps(run_maven_tests(root), indent=2))
