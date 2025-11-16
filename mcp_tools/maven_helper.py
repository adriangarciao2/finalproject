from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List


def run_maven(args: List[str], project_root: str | None = None, timeout: int = 300) -> str:
    """Run a Maven command and return captured stdout.

    The function prefers a project Maven wrapper (`mvnw` / `mvnw.cmd`) when
    present. Otherwise it resolves `mvn` via `shutil.which('mvn')` and uses the
    resolved executable path. On Windows this will commonly return the full
    path to `mvn.CMD` which is safe to execute from Python's subprocess API.

    Args:
        args: list of args to append to the mvn executable, e.g. ['-v'] or ['test']
        project_root: optional project root path used to prefer wrapper
        timeout: command timeout in seconds

    Returns:
        stdout string

    Raises:
        FileNotFoundError: if neither mvnw nor mvn can be found.
        subprocess.CalledProcessError: when Maven exits with non-zero return code.
        subprocess.TimeoutExpired: on timeout.
    """
    root = Path(project_root) if project_root else None
    is_windows = os.name == "nt"

    # Prefer wrapper if present
    if root is not None:
        if is_windows and (root / "mvnw.cmd").exists():
            cmd = [str(root / "mvnw.cmd")] + args
        elif (root / "mvnw").exists():
            cmd = [str(root / "mvnw")] + args
        else:
            mvn_path = shutil.which("mvn")
            if not mvn_path:
                raise FileNotFoundError("Maven (mvn) not found in PATH; ensure mvn is installed or add a mvnw wrapper to the project root")
            cmd = [mvn_path] + args
        cwd = str(root)
    else:
        mvn_path = shutil.which("mvn")
        if not mvn_path:
            raise FileNotFoundError("Maven (mvn) not found in PATH; ensure mvn is installed")
        cmd = [mvn_path] + args
        cwd = None

    # Use check=True so a CalledProcessError is raised on non-zero exit.
    completed = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=True,
    )
    return completed.stdout
