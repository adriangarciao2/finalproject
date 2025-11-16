"""Dashboard generator that wires JaCoCo, Surefire and git helpers into MCP flows.

Provides `generate_coverage_dashboard(module: str='d2l')` for programmatic use.
"""
from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Dict, List, Optional

from .coverage import parse_jacoco_report
from .git_tools import git_count_bugfix_commits_since, git_changed_tests_since


def _parse_surefire_tests_count(surefire_dir: Path) -> int:
    total = 0
    if not surefire_dir.exists():
        return 0
    for p in surefire_dir.glob('TEST-*.xml'):
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(str(p))
            root = tree.getroot()
            tests = root.attrib.get('tests')
            if tests is not None:
                total += int(tests)
        except Exception:
            continue
    return total


def _count_assertions(test_src_dir: Path) -> (int, Dict[str, int]):
    import re
    total = 0
    per_file = {}
    if not test_src_dir.exists():
        return 0, {}
    pat = re.compile(r"\bassert\b|Assert\.")
    for f in test_src_dir.rglob('*.java'):
        try:
            txt = f.read_text(encoding='utf-8')
        except Exception:
            continue
        c = len(pat.findall(txt))
        if c:
            per_file[str(f.relative_to(test_src_dir))] = c
            total += c
    return total, per_file


def generate_coverage_dashboard(module: str = 'd2l', repo_root: Optional[str] = None) -> str:
    root = Path(repo_root) if repo_root else Path.cwd()
    module_path = root / module
    jacoco = module_path / 'target' / 'site' / 'jacoco' / 'jacoco.xml'
    surefire = module_path / 'target' / 'surefire-reports'
    test_src = module_path / 'src' / 'test' / 'java'
    report_md = root / 'reports' / 'coverage_history.md'

    overall = None
    package_map = {}
    class_map = {}
    try:
        parsed = parse_jacoco_report(str(jacoco)) if jacoco.exists() else None
        if parsed:
            overall = parsed.get('overall', {})
            # overall LINE
            line = overall.get('LINE') if overall else None
            if line:
                overall_pct = line.get('pct')
            else:
                overall_pct = None
            # build package/class maps from parsed classes
            classes = parsed.get('classes', []) if parsed else []
            for c in classes:
                pkg = c.get('package')
                name = c.get('name')
                counters = c.get('counters', {})
                line_ctr = counters.get('LINE')
                pct = line_ctr.get('pct') if line_ctr else None
                if pkg and name and pct is not None:
                    package_map.setdefault(pkg, 0.0)
                    # accumulate average? keep last for simplicity
                    class_map[f"{pkg}.{name}"] = pct
        else:
            overall_pct = None
    except Exception:
        overall_pct = None

    num_tests = _parse_surefire_tests_count(surefire)
    num_asserts, per_file = _count_assertions(test_src)

    last_ts = None
    if report_md.exists():
        txt = report_md.read_text(encoding='utf-8')
        m = re.findall(r"## Timestamp: ([0-9T:\-+.Z]+)", txt)
        if m:
            last_ts = m[-1]

    changed_tests = git_changed_tests_since(last_ts, root, module_path)
    bugfix_count, bugfix_msgs = git_count_bugfix_commits_since(last_ts, root)

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    lines: List[str] = []
    lines.append(f"## Timestamp: {now}")
    if overall_pct is None:
        lines.append("- **Total coverage**: JaCoCo XML not found")
    else:
        lines.append(f"- **Total coverage**: {overall_pct:.2f}%")

    if package_map:
        lines.append("- **Coverage per package**:")
        for pkg, pct in sorted(package_map.items(), key=lambda t: t[1])[:20]:
            lines.append(f"  - `{pkg}`: {pct:.2f}%")

    if class_map:
        lines.append("- **Low coverage classes (sample)**:")
        for cls, pct in sorted(class_map.items(), key=lambda t: t[1])[:10]:
            lines.append(f"  - `{cls}`: {pct:.2f}%")

    lines.append(f"- **Number of tests**: {num_tests}")
    lines.append(f"- **Number of assertions (approx)**: {num_asserts}")
    lines.append(f"- **Tests added/changed since last run**: {len(changed_tests)}")
    for t in changed_tests[:50]:
        lines.append(f"  - `{t}`")
    lines.append(f"- **Bug-fix commits since last run**: {bugfix_count}")
    for m in bugfix_msgs[:10]:
        lines.append(f"  - {m}")

    lines.append(f"- **Whether a bug was found/fixed**: {'Yes' if bugfix_count>0 else 'No'}")
    lines.append(f"- **Sources scanned**: `{jacoco}`, `{surefire}`, `{test_src}`")

    entry = '\n'.join(lines) + '\n\n'
    report_md.parent.mkdir(parents=True, exist_ok=True)
    report_md.write_text(report_md.read_text(encoding='utf-8') + entry if report_md.exists() else entry, encoding='utf-8')

    return str(report_md)


if __name__ == '__main__':
    print(generate_coverage_dashboard())
