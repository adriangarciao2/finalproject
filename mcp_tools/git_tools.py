"""Git helper tools for MCP workflows.

Functions:
- git_status(repo_dir) -> dict
- git_add_all(repo_dir) -> dict
- git_commit(repo_dir, message=None) -> dict
- git_push(repo_dir, remote='origin') -> dict
- git_pull_request(repo_dir, base='main', title=None, body=None) -> dict

These tools use the system `git` (and `gh` CLI if available) and will return
structured dictionaries with status and output for integration into MCP flows.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    # local coverage helper to include coverage stats in commit messages
    from .coverage import parse_jacoco_report
except Exception:
    parse_jacoco_report = None


def _run(cmd: List[str], cwd: Optional[str] = None, timeout: int = 300) -> Tuple[int, str]:
    proc = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=timeout)
    return proc.returncode, proc.stdout or ""


def git_status(repo_dir: str) -> Dict:
    """Run `git status --short` and `git status --branch` and parse results.

    Returns dict: { clean: bool, staged: [...], unstaged: [...], untracked: [...], conflicts: [...], branch: str, raw: {short, branch} }
    """
    root = str(Path(repo_dir))
    rc1, short_out = _run(["git", "status", "--short"], cwd=root)
    rc2, branch_out = _run(["git", "status", "--branch"], cwd=root)

    staged: List[str] = []
    unstaged: List[str] = []
    untracked: List[str] = []
    conflicts: List[str] = []

    for line in short_out.splitlines():
        if not line.strip():
            continue
        # format: XY <path>
        # handle paths with leading spaces
        status = line[:2]
        path = line[3:]
        x = status[0]
        y = status[1]
        if x == "?" or status.startswith("??"):
            untracked.append(path)
            continue
        if x != " ":
            staged.append(path)
        if y != " ":
            unstaged.append(path)

        # conflicts detection
        if status.strip() in {"UU", "AA", "DD", "AU", "UA", "DU", "UD"} or "U" in status:
            conflicts.append(path)

    clean = not (staged or unstaged or untracked)

    # parse branch name from branch_out (first line like "On branch NAME" or header)
    branch = None
    m = re.search(r"On branch (\S+)", branch_out)
    if m:
        branch = m.group(1)
    else:
        # try git rev-parse
        rc3, out3 = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
        branch = out3.strip() if rc3 == 0 else None

    return {
        "clean": clean,
        "staged": staged,
        "unstaged": unstaged,
        "untracked": untracked,
        "conflicts": conflicts,
        "branch": branch,
        "raw": {"short": short_out, "branch": branch_out},
    }


def git_add_all(repo_dir: str, patterns: Optional[List[str]] = None) -> Dict:
    """Stage all changes. Patterns is optional and can be used for explicit adds.

    Returns: { success: bool, staged: [...] , raw_output }
    """
    root = str(Path(repo_dir))
    if patterns:
        cmd = ["git", "add"] + patterns
    else:
        # use -A so .gitignore is respected and deletions are staged
        cmd = ["git", "add", "-A"]

    rc, out = _run(cmd, cwd=root)

    # now list staged files
    rc2, staged_out = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
    staged = [s for s in staged_out.splitlines() if s.strip()]

    return {"success": rc == 0, "staged": staged, "raw": out}


def _compose_commit_message(repo_dir: str, message: Optional[str]) -> str:
    if message:
        return message

    # Try to include coverage stats if available
    if parse_jacoco_report:
        try:
            rp = Path(repo_dir) / "target" / "site" / "jacoco" / "jacoco.xml"
            if rp.exists():
                parsed = parse_jacoco_report(str(rp))
                line = parsed.get("overall", {}).get("LINE")
                if line:
                    covered = line.get("covered", 0)
                    total = line.get("total", 0)
                    pct = line.get("pct", 0.0)
                    return f"test: improve coverage to {pct:.0f}% ({covered}/{total} lines covered)"
        except Exception:
            pass

    # fallback generic message
    return "test: update tests"


def git_commit(repo_dir: str, message: Optional[str] = None) -> Dict:
    """Commit staged changes. If no message provided, compose a standardized message (with coverage if available).

    Returns: { success: bool, committed: int, message: str, raw }
    """
    root = str(Path(repo_dir))
    # ensure there are staged changes
    rc, staged_out = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
    staged_files = [s for s in staged_out.splitlines() if s.strip()]
    if not staged_files:
        return {"success": False, "committed": 0, "message": "No staged changes", "raw": ""}

    commit_message = _compose_commit_message(repo_dir, message)
    rc2, out2 = _run(["git", "commit", "-m", commit_message], cwd=root)

    # count files committed by parsing output or using git show --name-only --pretty=""
    rc3, names = _run(["git", "show", "--name-only", "--pretty=", "HEAD"], cwd=root)
    committed_files = [s for s in names.splitlines() if s.strip()]

    return {"success": rc2 == 0, "committed": len(committed_files), "message": commit_message, "raw": out2}


def git_push(repo_dir: str, remote: str = "origin") -> Dict:
    """Push current branch to remote and set upstream.

    Returns: { success: bool, branch: str, raw }
    """
    root = str(Path(repo_dir))
    rc, branch_out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    branch = branch_out.strip() if rc == 0 else None
    if not branch:
        return {"success": False, "branch": None, "raw": "Could not determine branch"}

    rc2, out2 = _run(["git", "push", "-u", remote, branch], cwd=root)
    return {"success": rc2 == 0, "branch": branch, "raw": out2}


def git_pull_request(repo_dir: str, base: str = "main", title: Optional[str] = None, body: Optional[str] = None) -> Dict:
    """Create a PR using `gh` CLI if available, otherwise use GitHub API with token from env.

    Returns: { success: bool, url: Optional[str], raw }
    """
    root = Path(repo_dir)
    # determine current branch
    rc, branch_out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=str(root))
    head = branch_out.strip() if rc == 0 else None
    if not head:
        return {"success": False, "url": None, "raw": "Could not determine branch"}

    # default title/body
    if not title:
        title = f"feat: changes on {head}"
    if not body:
        body = "Automated PR created by MCP tools."

    # try gh CLI
    gh_path = shutil.which("gh")
    if gh_path:
        # create PR and capture URL printed by gh
        cmd = [gh_path, "pr", "create", "--base", base, "--head", head, "--title", title, "--body", body]
        rc2, out2 = _run(cmd, cwd=str(root))
        # gh prints URL on success to stdout
        url_match = re.search(r"https?://[^"]+", out2)
        url = url_match.group(0) if url_match else None
        return {"success": rc2 == 0, "url": url, "raw": out2}

    # fallback: use GitHub API
    # need token
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        return {"success": False, "url": None, "raw": "gh not available and GITHUB_TOKEN not set"}

    # determine repo owner/name from origin url
    rc3, origin_url = _run(["git", "config", "--get", "remote.origin.url"], cwd=str(root))
    origin_url = origin_url.strip()
    # parse formats like git@github.com:owner/repo.git or https://github.com/owner/repo.git
    m = re.search(r"[:/]([^/]+/[^/.]+)(?:\.git)?$", origin_url)
    if not m:
        return {"success": False, "url": None, "raw": f"Could not parse origin url: {origin_url}"}
    owner_repo = m.group(1)

    import json, urllib.request

    api_url = f"https://api.github.com/repos/{owner_repo}/pulls"
    payload = {"title": title, "head": head, "base": base, "body": body}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, headers={
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json",
    }, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_data = resp.read().decode("utf-8")
            j = json.loads(resp_data)
            return {"success": True, "url": j.get("html_url"), "raw": resp_data}
    except Exception as e:
        return {"success": False, "url": None, "raw": str(e)}
