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
import traceback
import time
import json

from mcp_tools.coverage import parse_jacoco_report, find_uncovered_segments
from mcp_tools.git_tools import git_workflow_commit_and_push
from mcp_tools.auto_fix import propose_fixes, apply_fix


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
    # Prefer scanning main sources when present; otherwise scan whole repo but exclude common folders.
    main_src = root / "src" / "main" / "java"
    if main_src.exists():
        java_files = list(main_src.rglob("*.java"))
    else:
        # Exclude these directories when scanning whole repo
        exclude_dirs = {".mvn", "target", "src/test", "node_modules"}
        java_files = []
        for f in root.rglob("*.java"):
            # skip if any excluded dir is in the file's parts
            parts = {p.lower() for p in f.parts}
            if parts & {d.lower() for d in exclude_dirs}:
                continue
            java_files.append(f)
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
            # Skip classes that look like test classes
            if cls.endswith("Test"):
                continue
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

def improve_tests_iteration(
    project_root: str,
    max_methods: int = 5,
    line_threshold: float = 0.0,
    do_commit: bool = False,
    push: bool = False,
    branch_name: str | None = None,
    dry_run: bool = True,
    apply_fixes: bool = False,
    max_fixes_apply: int = 1,
) -> Dict:
    """Perform one automated test-improvement iteration.

    Steps:
      1. Run tests.
      2. Parse JaCoCo report and find uncovered segments.
      3. Generate JUnit skeletons for a subset of uncovered methods.
      4. Rerun tests.
      5. If new tests pass, optionally commit and push changes.
      6. If new tests fail, capture failures and point to suspected code.

    This function is conservative by default (`dry_run=True`) and will not
    perform commits/pushes unless `do_commit=True` and `dry_run=False`.

    Returns a dict with details about the iteration and actions taken.
    """
    root = Path(project_root)
    report_path = root / "target" / "site" / "jacoco" / "jacoco.xml"

    iteration = {
        "initial_test": None,
        "generated_tests": [],
        "second_test": None,
        "coverage_before": None,
        "coverage_after": None,
        "commit": None,
        "errors": [],
    }

    # 1) Run initial tests
    initial = run_maven_tests(project_root)
    iteration["initial_test"] = initial

    # 2) Parse JaCoCo if present
    if report_path.exists():
        try:
            parsed_before = parse_jacoco_report(str(report_path))
            iteration["coverage_before"] = parsed_before.get("overall", {})
        except Exception as e:
            iteration["errors"].append(f"coverage-parse-before-error: {e}")
            parsed_before = None
    else:
        parsed_before = None

    # 3) Find uncovered segments
    uncovered = []
    if report_path.exists():
        try:
            uncovered = find_uncovered_segments(str(report_path), line_threshold=line_threshold)
        except Exception as e:
            iteration["errors"].append(f"find-uncovered-error: {e}")

    if not uncovered:
        iteration["note"] = "No uncovered segments found; nothing to generate."
        return iteration

    # select subset
    selected = uncovered[:max_methods]

    # group by class/package to build class_infos expected by generate_junit_tests
    group = {}
    for seg in selected:
        pkg = seg.get("package") or ""
        cls_full = seg.get("class") or ""
        # if class contains package part, derive simple name
        if "." in cls_full and not pkg:
            parts = cls_full.split(".")
            pkg = ".".join(parts[:-1])
            cls_simple = parts[-1]
        else:
            cls_simple = cls_full.split(".")[-1]

        key = (pkg, cls_simple)
        group.setdefault(key, []).append(seg.get("method"))

    class_infos = []
    for (pkg, cls), methods in group.items():
        method_entries = []
        for m in methods:
            if not m:
                continue
            method_entries.append({"name": m, "signature": f"public void {m}()"})

        # best-effort file path guess (not required by generate_junit_tests)
        file_guess = os.path.join("src", "main", "java", *(pkg.split(".") if pkg else []), f"{cls}.java")
        class_infos.append({"file": file_guess, "package": pkg or None, "class": cls, "methods": method_entries})

    # 4) Generate tests
    try:
        created = generate_junit_tests(class_infos, project_root)
        iteration["generated_tests"] = created
    except Exception as e:
        iteration["errors"].append(f"generate-tests-error: {traceback.format_exc()}")
        return iteration

    if not created:
        iteration["note"] = "No test files were created (maybe they already existed)."
        return iteration

    # 5) Rerun tests
    second = run_maven_tests(project_root)
    iteration["second_test"] = second

    # 6) Parse new coverage if present
    if report_path.exists():
        try:
            parsed_after = parse_jacoco_report(str(report_path))
            iteration["coverage_after"] = parsed_after.get("overall", {})
        except Exception as e:
            iteration["errors"].append(f"coverage-parse-after-error: {e}")

    # 7) Handle failures: if second run failed, capture and return
    if not second.get("success", False):
        iteration["errors"].append({
            "type": "new-tests-failed",
            "failed_tests": second.get("failed_tests"),
            "raw_output_snippet": second.get("raw_output", "")[:4000],
        })
        # point to suspected code by reusing the first failed test name if available
        if second.get("failed_tests"):
            iteration["suspected_tests"] = second.get("failed_tests")
        # Propose conservative fixes based on the stacktrace / raw output
        try:
            suggestions = propose_fixes(second.get("raw_output", ""), project_root, max_suggestions=max_fixes_apply)
            iteration["fix_suggestions"] = suggestions
            if apply_fixes and suggestions:
                applied = []
                for s in suggestions[:max_fixes_apply]:
                    ok = apply_fix(s)
                    applied.append({"suggestion": s, "applied": ok})
                iteration["applied_fixes"] = applied
                if any(a.get("applied") for a in applied):
                    # rerun tests after applying fixes
                    third = run_maven_tests(project_root)
                    iteration["third_test"] = third
        except Exception:
            iteration["errors"].append(f"auto-fix-error: {traceback.format_exc()}")

        return iteration

    # 8) If tests pass and do_commit requested, commit + push
    if second.get("success", False) and created and do_commit:
        # prepare a succinct commit message with coverage delta if available
        before_pct = None
        after_pct = None
        try:
            before = iteration.get("coverage_before") or {}
            after = iteration.get("coverage_after") or {}
            before_pct = before.get("LINE", {}).get("pct") if before else None
            after_pct = after.get("LINE", {}).get("pct") if after else None
        except Exception:
            pass

        cov_part = ""
        if before_pct is not None and after_pct is not None:
            cov_part = f" coverage LINE {before_pct:.1f}% -> {after_pct:.1f}%"

        commit_msg = f"test: add {len(created)} generated test(s);{cov_part}".strip()

        try:
            # Use the helper workflow; it accepts dry_run to simulate commit/push
            gw = git_workflow_commit_and_push(
                repo_dir=project_root,
                message=commit_msg,
                branch=branch_name,
                dry_run=(not do_commit) or dry_run,
            )
            iteration["commit"] = gw
        except Exception:
            iteration["errors"].append(f"git-workflow-error: {traceback.format_exc()}")

    return iteration

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

    seen = set()

    for info in class_infos:
        # Skip any classes that came from test sources (we don't generate tests for tests)
        fpath = info.get("file", "")
        fpath_norm = fpath.replace("\\", "/").lower()
        if "/src/test/" in fpath_norm or fpath_norm.startswith("src/test/"):
            continue
        package = info.get("package")
        class_name = info.get("class")
        # Skip generating tests for classes that look like test classes
        if class_name.endswith("Test"):
            continue

        test_class_name = f"{class_name}Test"

        if package:
            package_path = test_root / _package_to_path(package)
        else:
            package_path = test_root

        package_path.mkdir(parents=True, exist_ok=True)

        file_path = package_path / f"{test_class_name}.java"

        # If file already exists, skip to avoid overwriting developer tests
        if file_path.exists():
            continue

        # Avoid duplicate generation if class name/package combo already handled
        key = (package or "", class_name)
        if key in seen:
            continue
        seen.add(key)

        # Build file contents
        lines: List[str] = []
        if package:
            lines.append(f"package {package};")
            lines.append("")

        lines.append("import org.junit.jupiter.api.Test;")
        lines.append("import static org.junit.jupiter.api.Assertions.*;")
        lines.append("")
        lines.append(f"public class {test_class_name} {{")

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
                # skip private methods and constructors
                name = m.get("name")
                if name == class_name:
                    continue
                test_name = f"test_{name}"
                lines.append("    @Test")
                lines.append(f"    void {test_name}() {{")
                lines.append("        // TODO: implement test for: {}".format(m.get("signature")))
                lines.append("        // Example: create instance and call method")
                lines.append(f"        // {class_name} sut = new {class_name}();")
                lines.append("        // assertEquals(expected, sut.{name}(...));".format(name=name))
                lines.append("    }")

        lines.append("}")

        file_text = "\n".join(lines) + "\n"
        # Write atomically: write to temp then rename to avoid partial files
        tmp = file_path.with_suffix(file_path.suffix + ".tmp")
        tmp.write_text(file_text, encoding="utf-8")
        tmp.replace(file_path)
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
