"""Coverage analysis tools for JaCoCo XML reports.

Tools:
- parse_jacoco_report(report_path: str) -> dict
  Parses `target/site/jacoco/jacoco.xml` and returns overall and per-class coverage info.

- find_uncovered_segments(report_path: str, line_threshold: float = 0.0) -> list
  Identifies methods/classes with low or zero line coverage. Returns list of
  dicts: { 'package', 'class', 'method', 'startLine', 'endLine', 'pct' }

- coverage_recommendations(uncovered_segments: list) -> list[str]
  Turns uncovered segments into human-readable test suggestions.

This is a simple, robust implementation using ElementTree and heuristics; it
doesn't rely on external libraries and aims to be tolerant of different
JaCoCo XML versions.
"""
from __future__ import annotations

import os
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional


def _counter_to_dict(counter_elem: ET.Element) -> Dict[str, int]:
    t = counter_elem.get("type")
    missed = int(counter_elem.get("missed", "0"))
    covered = int(counter_elem.get("covered", "0"))
    total = missed + covered
    pct = (covered / total * 100.0) if total > 0 else 0.0
    return {"type": t, "missed": missed, "covered": covered, "total": total, "pct": pct}


def parse_jacoco_report(report_path: str) -> Dict:
    """Parse a JaCoCo XML report and return summary + per-class coverage.

    Args:
        report_path: path to `jacoco.xml` (str)

    Returns:
        dict: {
            'overall': { counter_type: {missed, covered, total, pct}, ... },
            'classes': [ { 'package', 'name', 'sourcefile', 'counters': {...}, 'methods': [ {name, desc, line, counters}, ... ] }, ... ]
        }
    """
    p = Path(report_path)
    if not p.exists():
        raise FileNotFoundError(f"JaCoCo report not found: {report_path}")

    tree = ET.parse(str(p))
    root = tree.getroot()

    overall: Dict[str, Dict] = {}
    # report-level counters
    for c in root.findall("counter"):
        info = _counter_to_dict(c)
        overall[info["type"]] = info

    classes: List[Dict] = []

    # iterate packages -> classes
    for pkg in root.findall("package"):
        pkg_name = pkg.get("name")
        # classes
        for cls in pkg.findall("class"):
            cls_name = cls.get("name")  # e.g. com/example/App
            sourcefile = cls.get("sourcefilename")

            # collect counters at class level
            cls_counters = {}
            for cc in cls.findall("counter"):
                info = _counter_to_dict(cc)
                cls_counters[info["type"]] = info

            methods = []
            for m in cls.findall("method"):
                m_name = m.get("name")
                m_desc = m.get("desc")
                line_attr = m.get("line")
                m_line = int(line_attr) if line_attr and line_attr.isdigit() else None
                m_counters = {}
                for mc in m.findall("counter"):
                    mi = _counter_to_dict(mc)
                    m_counters[mi["type"]] = mi

                methods.append({
                    "name": m_name,
                    "desc": m_desc,
                    "line": m_line,
                    "counters": m_counters,
                })

            classes.append({
                "package": pkg_name,
                "name": cls_name,
                "sourcefile": sourcefile,
                "counters": cls_counters,
                "methods": methods,
            })

    return {"overall": overall, "classes": classes}


def find_uncovered_segments(report_path: str, line_threshold: float = 0.0) -> List[Dict]:
    """Identify classes/methods with low/zero coverage.

    Args:
        report_path: path to `jacoco.xml`.
        line_threshold: include methods whose LINE coverage pct <= this value.

    Returns:
        list of dicts: { 'package', 'class', 'method', 'startLine', 'endLine', 'pct' }
    """
    parsed = parse_jacoco_report(report_path)
    root = Path(report_path).parents[0].parents[0]  # up from .../site/jacoco/jacoco.xml -> project root

    uncovered = []

    for cls in parsed["classes"]:
        pkg = cls.get("package")
        cls_name = cls.get("name")
        # normalize class name to dot-notation
        cls_dot = cls_name.replace("/", ".")

        # Check methods first
        methods = cls.get("methods", [])
        # sort by line if possible
        methods_sorted = sorted([m for m in methods if m.get("line")], key=lambda x: x.get("line") or 0)

        for idx, m in enumerate(methods_sorted):
            m_line = m.get("line")
            counters = m.get("counters", {})
            line_counter = counters.get("LINE") or counters.get("INSTRUCTION")
            pct = line_counter.get("pct") if line_counter else 0.0
            if pct <= line_threshold:
                # estimate end line as next method start -1 or None
                if idx + 1 < len(methods_sorted):
                    end_line = methods_sorted[idx + 1].get("line") - 1
                else:
                    end_line = None

                uncovered.append({
                    "package": pkg,
                    "class": cls_dot,
                    "method": m.get("name"),
                    "startLine": m_line,
                    "endLine": end_line,
                    "pct": pct,
                })

        # If class-level line coverage is 0 and no method detail, add class as whole
        cls_line_counter = cls.get("counters", {}).get("LINE")
        if cls_line_counter and cls_line_counter.get("pct", 100.0) <= line_threshold and not methods_sorted:
            uncovered.append({
                "package": pkg,
                "class": cls_dot,
                "method": None,
                "startLine": None,
                "endLine": None,
                "pct": cls_line_counter.get("pct", 0.0),
            })

    return uncovered


def coverage_recommendations(uncovered_segments: List[Dict]) -> List[str]:
    """Turn uncovered segment list into human-readable test suggestions.

    Args:
        uncovered_segments: output of `find_uncovered_segments`.

    Returns:
        list of suggestion strings.
    """
    suggestions: List[str] = []
    for seg in uncovered_segments:
        cls = seg.get("class")
        pkg = seg.get("package")
        method = seg.get("method")
        start = seg.get("startLine")
        end = seg.get("endLine")
        pct = seg.get("pct")

        target = f"{cls}" if not pkg else f"{pkg}.{cls}"
        if method:
            if start and end:
                loc = f"lines {start}-{end}"
            elif start:
                loc = f"line {start}"
            else:
                loc = "the method body"

            suggestions.append(
                f"Write a unit test for {target}.{method}() (covers {loc}) — current coverage {pct:.1f}%. Consider edge cases and error paths."
            )
        else:
            suggestions.append(
                f"Write tests for {target} to exercise its public API (current line coverage {pct:.1f}%). Start with typical use cases and null/empty inputs."
            )

    return suggestions


if __name__ == "__main__":
    import json
    rp = os.path.join(os.getcwd(), "target", "site", "jacoco", "jacoco.xml")
    if os.path.exists(rp):
        parsed = parse_jacoco_report(rp)
        print(json.dumps(parsed.get("overall", {}), indent=2))
        uncovered = find_uncovered_segments(rp)
        print("Uncovered:", json.dumps(uncovered, indent=2))
        print("Recommendations:")
        for s in coverage_recommendations(uncovered):
            print(" -", s)
    else:
        print("No jacoco.xml found at", rp)
