#!/usr/bin/env python3
"""Generate a simple coverage & quality dashboard from JaCoCo, Surefire and git.

Usage:
    python tools/generate_coverage_dashboard.py [--module d2l]

This script will append an entry to `reports/coverage_history.md`.
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_jacoco(jacoco_xml: Path) -> Tuple[Optional[float], Dict[str, float], Dict[str, float]]:
    """Parse JaCoCo XML and return overall line coverage, package coverage map, class coverage map.

    Returns (overall_pct, package_map, class_map) where maps are name->pct (0-100).
    """
    if not jacoco_xml.exists():
        return None, {}, {}
    tree = ET.parse(jacoco_xml)
    root = tree.getroot()

    ns = ''
    # JaCoCo XML typically doesn't use namespaces; find overall counter
    overall_pct = None
    for counter in root.findall('counter'):
        if counter.attrib.get('type') == 'LINE':
            missed = int(counter.attrib.get('missed', '0'))
            covered = int(counter.attrib.get('covered', '0'))
            total = missed + covered
            overall_pct = (covered / total * 100.0) if total > 0 else 0.0
            break

    package_map: Dict[str, float] = {}
    class_map: Dict[str, float] = {}
    for package in root.findall('.//package'):
        pkg_name = package.attrib.get('name')
        # package-level counter
        p_counter = package.find("counter[@type='LINE']")
        if p_counter is not None:
            missed = int(p_counter.attrib.get('missed', '0'))
            covered = int(p_counter.attrib.get('covered', '0'))
            total = missed + covered
            pkg_pct = (covered / total * 100.0) if total > 0 else 0.0
            package_map[pkg_name] = pkg_pct
        # classes
        for cls in package.findall('class'):
            cls_name = cls.attrib.get('name')
            c_counter = cls.find("counter[@type='LINE']")
            if c_counter is not None:
                missed = int(c_counter.attrib.get('missed', '0'))
                covered = int(c_counter.attrib.get('covered', '0'))
                total = missed + covered
                cls_pct = (covered / total * 100.0) if total > 0 else 0.0
                # class names are package-style; normalize
                fqcn = f"{pkg_name}.{cls_name}" if pkg_name else cls_name
                class_map[fqcn] = cls_pct

    return overall_pct, package_map, class_map


def parse_surefire(surefire_dir: Path) -> int:
    """Parse Surefire TEST-*.xml files and sum tests count."""
    if not surefire_dir.exists():
        return 0
    total_tests = 0
    for p in surefire_dir.glob('TEST-*.xml'):
        try:
            tree = ET.parse(p)
            root = tree.getroot()
            # root may be <testsuite>
            tests = root.attrib.get('tests')
            if tests is not None:
                total_tests += int(tests)
        except Exception:
            continue
    return total_tests


def count_assertions(test_src_dir: Path) -> Tuple[int, Dict[str, int]]:
    """Approximate number of assertions by scanning test sources for 'assert' and 'Assert.' occurrences.

    Returns (total_asserts, per_file_map).
    """
    total = 0
    per_file: Dict[str, int] = {}
    if not test_src_dir.exists():
        return 0, {}
    pattern = re.compile(r"\bassert\b|Assert\.")
    for path in test_src_dir.rglob('*.java'):
        try:
            txt = path.read_text(encoding='utf-8')
        except Exception:
            continue
        cnt = len(pattern.findall(txt))
        if cnt:
            per_file[str(path.relative_to(test_src_dir))] = cnt
            total += cnt
    return total, per_file


def git_changed_tests_since(since_iso: Optional[str], repo_root: Path, module_path: Path) -> List[str]:
    """Return list of changed test files under module_path since ISO timestamp.

    If since_iso is None, return recent test files in last 50 commits.
    """
    cmd = ['git', '-C', str(repo_root), 'log', '--name-only', '--pretty=format:']
    if since_iso:
        cmd.insert(4, f'--since={since_iso}')
    else:
        cmd.extend(['-n', '50'])
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return []
    files = set()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        p = Path(line)
        # normalize: test files under module/src/test/java
        try:
            full = (repo_root / p).resolve()
        except Exception:
            continue
        try:
            rel = full.relative_to((repo_root / module_path).resolve())
        except Exception:
            continue
        if str(rel).startswith('src/test/java') and full.suffix == '.java':
            files.add(str(rel))
    return sorted(files)


def git_count_bugfix_commits_since(since_iso: Optional[str], repo_root: Path) -> Tuple[int, List[str]]:
    """Count commits whose message contains 'fix' or 'bug' since timestamp."""
    cmd = ['git', '-C', str(repo_root), 'log', '--pretty=format:%H%x09%s']
    if since_iso:
        cmd.insert(4, f'--since={since_iso}')
    else:
        cmd.extend(['-n', '50'])
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except subprocess.CalledProcessError:
        return 0, []
    count = 0
    msgs = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split('\t', 1)
        if len(parts) != 2:
            continue
        sha, subj = parts
        if re.search(r'\b(fix|fixes|bug|bugfix|hotfix)\b', subj, flags=re.I):
            count += 1
            msgs.append(f"{sha[:7]} {subj}")
    return count, msgs


def read_last_timestamp(report_md: Path) -> Optional[str]:
    if not report_md.exists():
        return None
    txt = report_md.read_text(encoding='utf-8')
    # find last '## Timestamp:' occurrence
    matches = re.findall(r"## Timestamp: ([0-9T:\-+.Z]+)", txt)
    if not matches:
        return None
    return matches[-1]


def append_report(report_md: Path, entry: str) -> None:
    report_md.parent.mkdir(parents=True, exist_ok=True)
    with report_md.open('a', encoding='utf-8') as f:
        f.write(entry)
        f.write('\n\n')


def generate_coverage_dashboard(module: str = 'd2l') -> None:
    repo_root = Path.cwd()
    module_path = Path(module)
    jacoco_xml = repo_root / module_path / 'target' / 'site' / 'jacoco' / 'jacoco.xml'
    surefire_dir = repo_root / module_path / 'target' / 'surefire-reports'
    test_src_dir = repo_root / module_path / 'src' / 'test' / 'java'
    report_md = repo_root / 'reports' / 'coverage_history.md'

    overall_pct, package_map, class_map = parse_jacoco(jacoco_xml)
    num_tests = parse_surefire(surefire_dir)
    num_asserts, per_file_asserts = count_assertions(test_src_dir)

    last_ts = read_last_timestamp(report_md)

    changed_tests = git_changed_tests_since(last_ts, repo_root, module_path)
    bugfix_count, bugfix_msgs = git_count_bugfix_commits_since(last_ts, repo_root)

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'

    prev_pct = None
    if last_ts and report_md.exists():
        # try to read previous coverage value from last entry
        txt = report_md.read_text(encoding='utf-8')
        prev_matches = re.findall(r"- \*\*Total coverage\*\*: ([0-9.]+)%", txt)
        if prev_matches:
            prev_pct = float(prev_matches[-1])

    delta = None
    if overall_pct is not None and prev_pct is not None:
        delta = overall_pct - prev_pct

    # Build markdown entry
    lines: List[str] = []
    lines.append(f"## Timestamp: {now}")
    if overall_pct is None:
        lines.append("- **Total coverage**: JaCoCo XML not found")
    else:
        pct_str = f"{overall_pct:.2f}"
        if delta is not None:
            sign = '+' if delta >= 0 else ''
            lines.append(f"- **Total coverage**: {pct_str}% (prev {prev_pct:.2f}%, {sign}{delta:.2f}%)")
        else:
            lines.append(f"- **Total coverage**: {pct_str}%")

    # Top packages
    if package_map:
        lines.append("- **Coverage per package**:")
        # sort by lowest coverage first
        for pkg, pct in sorted(package_map.items(), key=lambda t: t[1])[:20]:
            lines.append(f"  - `{pkg}`: {pct:.2f}%")

    # Low coverage classes (top 10)
    if class_map:
        lines.append("- **Low coverage classes (sample)**:")
        for cls, pct in sorted(class_map.items(), key=lambda t: t[1])[:10]:
            lines.append(f"  - `{cls}`: {pct:.2f}%")

    lines.append(f"- **Number of tests**: {num_tests}")
    lines.append(f"- **Number of assertions (approx)**: {num_asserts}")
    lines.append(f"- **Tests added/changed since last run**: {len(changed_tests)}")
    if changed_tests:
        for t in changed_tests:
            lines.append(f"  - `{t}`")
    lines.append(f"- **Bug-fix commits since last run**: {bugfix_count}")
    for m in bugfix_msgs[:10]:
        lines.append(f"  - {m}")

    found_fixed = 'Yes' if bugfix_count > 0 else 'No'
    lines.append(f"- **Whether a bug was found/fixed**: {found_fixed}")

    # simple footer with paths used
    lines.append(f"- **Sources scanned**: `{jacoco_xml}`, `{surefire_dir}`, `{test_src_dir}`")

    entry = '\n'.join(lines)
    append_report(report_md, entry)
    print(f"Appended coverage entry to {report_md}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--module', default='d2l', help='Module directory that contains target/ (default: d2l)')
    args = parser.parse_args()
    generate_coverage_dashboard(args.module)


if __name__ == '__main__':
    main()
