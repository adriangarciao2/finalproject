"""Orchestrator that wires existing MCP tools into an end-to-end test-improvement cycle.

This module uses functions from `mcp_tools.tests`, `mcp_tools.coverage`,
`mcp_tools.auto_fix`, and `mcp_tools.git_tools` to run one iteration:
 - run tests
 - parse JaCoCo
 - find uncovered segments
 - generate tests
 - rerun tests
 - propose/apply fixes (conservative)
 - optionally commit changes

The primary entrypoint is `run_test_improvement_cycle(project_path, do_commit=False, dry_run=True)`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Any

from . import tests as mcp_tests
from .git_tools import git_status, git_workflow_commit_and_push


def run_test_improvement_cycle(project_path: str = "d2l/codebase", *, do_commit: bool = False, dry_run: bool = True, max_methods: int = 5) -> Dict[str, Any]:
    """Run one test-improvement cycle for the given Maven project.

    Args:
        project_path: path to the Maven project root (relative or absolute).
        do_commit: whether to commit changes (uses git workflow helper).
        dry_run: pass-through to git workflow and other helpers to avoid pushing.
        max_methods: how many uncovered methods to attempt to generate tests for.

    Returns:
        A summary dict with keys: coverage_before, coverage_after, generated_tests, failures, git_status, commit_summary
    """
    root = Path(project_path)
    if not root.exists():
        return {"error": f"project path not found: {project_path}"}

    # Use the higher-level helper that already orchestrates generation and rerun
    iteration = mcp_tests.improve_tests_iteration(
        project_root=str(root),
        max_methods=max_methods,
        dry_run=dry_run,
        do_commit=do_commit,
        push=False,
        apply_fixes=False,
        max_fixes_apply=1,
    )

    # Gather git status for transparency
    gs = git_status(str(root))

    summary = {
        "project": str(root),
        "initial_test": iteration.get("initial_test"),
        "coverage_before": iteration.get("coverage_before"),
        "generated_tests": iteration.get("generated_tests"),
        "second_test": iteration.get("second_test"),
        "coverage_after": iteration.get("coverage_after"),
        "errors": iteration.get("errors", []),
        "git_status": gs,
    }

    # If requested, commit (use git_workflow_commit_and_push)
    commit_summary = None
    if do_commit and iteration.get("generated_tests"):
        commit_msg = f"test: add {len(iteration.get('generated_tests', []))} generated test(s)"
        commit_summary = git_workflow_commit_and_push(str(root), message=commit_msg, dry_run=dry_run, create_pr=False)
        summary["commit_summary"] = commit_summary

    return summary


if __name__ == "__main__":
    import json
    out = run_test_improvement_cycle("d2l", dry_run=True)
    print(json.dumps(out, indent=2, default=str))
