"""Automated, conservative fix proposals for common Java test failures.

This module provides two primary functions:
- propose_fixes(raw_output: str, project_root: str, max_suggestions: int = 3)
    -> List[dict]
- apply_fix(suggestion: dict) -> bool

The heuristics are intentionally minimal and safe:
- Detect stack frames from exceptions and locate the corresponding Java source file.
- If the failing method is declared `private`, propose changing it to `public` (a minimal visibility fix).

Applying fixes is performed atomically by writing to a temporary file and replacing the original.

Note: These heuristics are simplistic and may be incorrect for complex code. The agent
should review suggestions before applying them automatically in non-dry runs.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Dict, Optional


def parse_stack_trace(raw_output: str) -> List[Dict]:
    """Parse Java stack trace lines into frames.

    Returns a list of frames: { class, method, file, line }
    """
    frames = []
    if not raw_output:
        return frames

    # Matches: at com.example.App.add(App.java:23)
    pattern = re.compile(r"\s+at\s+([a-zA-Z0-9_.$]+)\.([A-Za-z0-9_<>$]+)\(([^:]+):(\d+)\)")
    for m in pattern.finditer(raw_output):
        cls, method, file, line = m.groups()
        try:
            line_no = int(line)
        except Exception:
            line_no = None
        frames.append({"class": cls, "method": method, "file": file, "line": line_no})
    return frames


def _locate_source_file(frame: Dict, project_root: str) -> Optional[Path]:
    """Try to find the .java source file referenced by a stack frame.

    We try a few common locations: `src/main/java/<file>`, and a path derived from the class name.
    """
    pr = Path(project_root)

    # direct file under src/main/java (e.g. App.java or com/example/App.java)
    candidates = []
    candidates.append(pr / "src" / "main" / "java" / frame["file"])

    # class-based path
    cls = frame.get("class")
    if cls:
        class_path = Path(cls.replace('.', '/'))
        candidates.append(pr / "src" / "main" / "java" / (str(class_path) + ".java"))

    for c in candidates:
        if c.exists():
            return c

    return None


def propose_fixes(raw_output: str, project_root: str, max_suggestions: int = 3) -> List[Dict]:
    """Return a list of conservative fix suggestions.

    Currently implemented suggestion type(s):
    - change_visibility: change `private` -> `public` on a method referenced in the stack trace.

    Each suggestion is a dict containing at least: { 'type', 'file', 'method', 'description' }
    """
    frames = parse_stack_trace(raw_output)
    suggestions: List[Dict] = []

    for f in frames:
        if len(suggestions) >= max_suggestions:
            break
        if not f.get("file"):
            continue
        src = _locate_source_file(f, project_root)
        if not src:
            continue
        try:
            text = src.read_text(encoding="utf-8")
        except Exception:
            continue

        # Look for method declaration
        method_name = f.get("method")
        # regex: (public|protected|private) <return-type> methodName(
        m_re = re.compile(r"\b(public|protected|private)\s+[\w<>, \[\]]+\s+" + re.escape(method_name) + r"\s*\(")
        m = m_re.search(text)
        if m:
            visibility = m.group(1)
            if visibility == "private":
                # prepare suggestion to change to public
                descr = f"Change visibility of {method_name} in {src} from private to public"
                suggestions.append({
                    "type": "change_visibility",
                    "file": str(src),
                    "method": method_name,
                    "line": f.get("line"),
                    "description": descr,
                })

    return suggestions


def apply_fix(suggestion: Dict) -> bool:
    """Attempt to apply a single suggestion.

    Returns True on success, False otherwise.
    Only implements `change_visibility` currently.
    """
    t = suggestion.get("type")
    if t == "change_visibility":
        file = suggestion.get("file")
        method = suggestion.get("method")
        if not file or not method:
            return False
        p = Path(file)
        if not p.exists():
            return False
        text = p.read_text(encoding="utf-8")

        # find the method occurrence and replace nearest `private` (within 200 chars before)
        idx = text.find(method + "(")
        if idx == -1:
            return False
        start = max(0, idx - 200)
        snippet = text[start:idx]
        # find the last occurrence of 'private' in snippet
        last_private = snippet.rfind("private")
        if last_private == -1:
            return False
        abs_idx = start + last_private
        # replace 'private' with 'public'
        new_text = text[:abs_idx] + "public" + text[abs_idx + len("private"):]

        # write atomically
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(new_text, encoding="utf-8")
        tmp.replace(p)
        return True

    return False
