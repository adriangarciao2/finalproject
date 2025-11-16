#!/usr/bin/env python3
"""Smoke test script to exercise the MCP orchestrator locally.

Runs one iteration against `d2l/codebase` and prints a concise summary.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mcp_tools.agent_workflow import run_test_improvement_cycle


def main():
    project = "d2l/codebase"
    print(f"Running test improvement cycle against: {project}")
    try:
        res = run_test_improvement_cycle(project, do_commit=False, dry_run=True)
    except Exception as e:
        print("Exception during run:", e)
        raise

    # Print short summary
    print("\n=== Summary ===")
    print("Project:", res.get('project'))
    before = res.get('coverage_before')
    after = res.get('coverage_after')
    print("Coverage before:", before)
    print("Coverage after:", after)
    created = res.get('generated_tests') or []
    print(f"Generated tests: {len(created)}")
    if created:
        for c in created:
            print(' -', c)

    errors = res.get('errors') or []
    print(f"Errors: {len(errors)}")
    for e in errors:
        print(' -', e)

    # Git status snippet
    gs = res.get('git_status') or {}
    print('Git status clean:', gs.get('clean'))
    print('Staged files count:', len(gs.get('staged', [])))

    # Dump full JSON for debugging to file
    outp = ROOT / 'reports' / 'smoke_test_result.json'
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(res, indent=2, default=str), encoding='utf-8')
    print('\nWrote detailed results to', outp)


if __name__ == '__main__':
    main()
