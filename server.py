from fastmcp import FastMCP
from pathlib import Path
from typing import Dict, Any

from mcp_tools.coverage import parse_jacoco_report
from mcp_tools.agent_workflow import run_test_improvement_cycle


mcp = FastMCP("Calculator MCP")


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    print(f"[MCP TOOL] Adding {a} and {b}")
    return a + b


@mcp.tool()
def coverage_summary(module: str = "d2l", top_n: int = 10) -> Dict[str, Any]:
    """Parse JaCoCo XML for `module` and return overall metrics + worst-covered classes.

    Args:
        module: module directory (default: `d2l`)
        top_n: number of worst-covered classes to return

    Returns:
        dict with keys: `jacoco_path`, `overall_line_pct`, `worst_classes` (list)
    """
    root = Path.cwd()
    jacoco = root / module / "target" / "site" / "jacoco" / "jacoco.xml"

    if not jacoco.exists():
        return {"error": "jacoco.xml not found", "jacoco_path": str(jacoco)}

    parsed = parse_jacoco_report(str(jacoco))
    overall = parsed.get("overall", {})
    line_info = overall.get("LINE") if overall else None
    overall_pct = line_info.get("pct") if line_info else None

    classes = parsed.get("classes", [])
    class_entries = []
    for c in classes:
        pkg = c.get("package") or ""
        name = c.get("name") or ""
        # Normalize class name (handle internal slash-separated names)
        cls_name = name.replace("/", ".")
        fqcn = f"{pkg}.{cls_name}" if pkg else cls_name
        counters = c.get("counters", {})
        line_ctr = counters.get("LINE")
        pct = line_ctr.get("pct") if line_ctr else None
        missed = line_ctr.get("missed") if line_ctr else None
        covered = line_ctr.get("covered") if line_ctr else None
        class_entries.append({"class": fqcn, "pct": pct, "missed": missed, "covered": covered})

    # Filter out classes without pct and sort ascending (worst first)
    class_entries = [e for e in class_entries if e.get("pct") is not None]
    class_entries.sort(key=lambda x: x["pct"])  # lowest coverage first

    return {
        "jacoco_path": str(jacoco),
        "overall_line_pct": overall_pct,
        "worst_classes": class_entries[:top_n],
        "total_classes": len(class_entries),
    }


@mcp.tool()
def run_full_test_cycle(project_path: str = "d2l/codebase", do_commit: bool = False, dry_run: bool = True) -> Dict[str, Any]:
    """Run the orchestrator workflow for test improvement against `project_path`.

    Returns a summary dict that includes coverage before/after, generated tests and git status.
    """
    return run_test_improvement_cycle(project_path, do_commit=do_commit, dry_run=dry_run)


if __name__ == "__main__":
    mcp.run(transport="sse", host="127.0.0.1", port=8000)
