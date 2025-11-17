# final_project_se333_GarciaAdrian

## Project Overview

This repository implements an MCP-based automated testing agent for Java/Maven projects. The agent:
- Runs Maven tests on a target Java project (the included `d2l` commons-lang3-style codebase).
- Generates and iterates on JUnit tests to improve coverage.
- Parses JaCoCo reports and recommends test improvements.
- Uses Git automation (status / add / commit / push / PR) to manage changes.

Architecture: a Python FastMCP server (`server.py`) exposes tools implemented under `mcp_tools/`. The GPT-5 mini model (used via MCP) performs reasoning / orchestration; MCP-exposed functions perform deterministic operations (mvn runs, parsing, edits, git).

---

## MCP Tool / API Documentation

Below are the main tools implemented in `mcp_tools/` and exposed (or wrapped) by `server.py`.

Notes: function signatures reflect the current code in this workspace.

### Maven helper
- Location: `mcp_tools/maven_helper.py`
- Function:
  - `run_maven(args: List[str], project_root: Optional[str] = None, timeout: int = 300) -> str`
- Description: Runs a Maven command. Prefers a project `mvnw` wrapper when present; otherwise resolves `mvn` via `shutil.which` and invokes the full executable path (works on Windows with `mvn.CMD`).
- Inputs:
  - `args`: list of arguments (e.g., `['test']`, `['-v']`).
  - `project_root`: optional path to run in (prefers wrapper there).
  - `timeout`: command timeout seconds.
- Output: captured stdout (string). Raises `FileNotFoundError` if Maven not found, `CalledProcessError` on non-zero exit.
- Example:
  - PowerShell:
    ```powershell
    python -c "from mcp_tools.maven_helper import run_maven; print(run_maven(['-v']))"
    ```

### Maven / test orchestration
- Location: `mcp_tools/tests.py` (high-level helpers) and `mcp_tools/agent_workflow.py` (orchestrator)
- Notable functions:
  - `run_maven_tests(project_root: str, timeout: int = 300) -> Dict` (wraps `run_maven` to run `mvn test` and return structured result).
  - `generate_junit_tests(...)` — generate skeleton JUnit tests (used by iteration logic).
  - `improve_tests_iteration(project_root: str, ...)` — iterative test improvement (uses coverage, generator, auto-fix).
  - `run_test_improvement_cycle(project_path: str = "d2l", do_commit: bool=False, dry_run: bool=True, ...) -> dict`  
    (in `mcp_tools.agent_workflow`: orchestrates full cycle — run tests, parse coverage, generate tests, run tests again, propose/apply fixes, and optionally stage/commit).
- Example:
  - Dry run improvement cycle:
    ```powershell
    python -c "from mcp_tools.agent_workflow import run_test_improvement_cycle; import json; print(json.dumps(run_test_improvement_cycle('d2l', do_commit=False, dry_run=True), indent=2))"
    ```

### Coverage analysis (JaCoCo)
- Location: `mcp_tools/coverage.py`
- Functions:
  - `parse_jacoco_report(report_path: str) -> Dict`  
    Parses `target/site/jacoco/jacoco.xml` and returns overall coverage counters and per-class data.
  - `find_uncovered_segments(report_path: str, line_threshold: float = 0.0) -> List[Dict]`  
    Identifies methods/classes below threshold; returns entries like `{class, method, lineRange, percent}`.
  - `coverage_recommendations(uncovered_segments: List[Dict]) -> List[str]`  
    Produces natural-language suggestions (e.g., "Write a test for X.foo() that covers the null case.").
- Example:
  ```powershell
  python -c "from mcp_tools.coverage import parse_jacoco_report; print(parse_jacoco_report('d2l/target/site/jacoco/jacoco.xml'))"
  ```

### Git automation
- Location: `mcp_tools/git_tools.py`
- Notable functions:
  - `git_status(repo_dir: str) -> Dict` — returns {clean/dirty, staged, unstaged, untracked, conflicts, branch}
  - `git_add_all(repo_dir: str, patterns: Optional[List[str]] = None) -> List[str]` — stages files (honors .gitignore).
  - `git_commit(repo_dir: str, message: str) -> Dict` — ensures staged changes and commits; can compose messages that include coverage stats.
  - `git_push(repo_dir: str, remote: str = "origin") -> Dict` — pushes current branch.
  - `git_pull_request(repo_dir: str, base: str = "main", title: Optional[str], body: Optional[str]) -> str` — creates PR using `gh` CLI or GitHub API.
  - `git_workflow_commit_and_push(repo_dir: str, commit_message: str, dry_run: bool = True, allow_main: bool = False) -> Dict` — higher-level helper that stages/commits/pushes (supports dry-run and branch protection).
- Example:
  ```powershell
  python -c "from mcp_tools.git_tools import git_status; import json; print(json.dumps(git_status('d2l'), indent=2))"
  ```

### Auto-fix proposals
- Location: `mcp_tools/auto_fix.py`
- Functions:
  - `propose_fixes(raw_output: str, project_root: str, max_suggestions: int = 3) -> List[Dict]`
  - `apply_fix(suggestion: Dict) -> Dict`  
- Description: conservative, reversible source edits (e.g., adjust visibility) proposed when new tests fail. Applied only when configured.

### Dashboard & reporting
- Location: `mcp_tools/dashboard.py` and `tools/generate_coverage_dashboard.py`
- Function:
  - `generate_coverage_dashboard(module_path: str = 'd2l') -> None`  
    Produces/updates `reports/coverage_history.md` with timestamped coverage entries and basic metrics (#tests, #assertions estimate, commits).
- Example:
  ```powershell
  python -c "from mcp_tools.dashboard import generate_coverage_dashboard; generate_coverage_dashboard('d2l')"
  ```

### MCP server tools (exposed via `server.py`)
- `add(a: float, b: float) -> float` — simple example tool.
- `coverage_summary(module: str = "d2l", top_n: int = 10) -> Dict[str, Any]` — returns parsed JaCoCo summary and worst-covered classes (uses `mcp_tools.coverage.parse_jacoco_report`).
- `run_full_test_cycle(project_path: str = "d2l/codebase", do_commit: bool = False, dry_run: bool = True) -> Dict[str, Any]` — MCP wrapper that calls `run_test_improvement_cycle` (same behavior as the Python orchestrator above, exposed via MCP).

---

## Installation & Configuration Guide

### Prerequisites
- OS: Windows 10+ (examples use PowerShell). Tools are cross-platform but this repo was exercised on Windows.
- Python: 3.12+ (project used a uv-managed virtualenv; see `pyproject.toml` and `uv.lock`)
- Java: JDK (this repo ran tests on JDK 25 in development). For best cross-version compatibility, JDK 17 is commonly safe; tests were stabilized for JDK 25 via Surefire JVM flags in `d2l/pom.xml`.
- Maven: Apache Maven 3.9.x (Chocolatey path example: `C:\ProgramData\chocolatey\lib\maven\apache-maven-3.9.11\bin\mvn.CMD`), or use a `mvnw` in project root.
- Git & GitHub account if you want PR integration.
- VS Code (optional) and the MCP extension if you use MCP from the editor.

### Quick setup (from repo root)
- Clone repo:
  ```powershell
  git clone <REPO_URL>
  cd final_project_se333_GarciaAdrian
  ```
- Create & activate Python env (using `uv` if available here):
  ```powershell
  uv venv
  .\.venv\Scripts\Activate.ps1
  uv sync
  ```
  Or use a standard venv:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt  # if requirements exist
  ```
- Ensure `mvn` is available to the Python process:
  - Add Maven to PATH (Chocolatey typical):
    - Confirm: `where.exe mvn` → `C:\ProgramData\chocolatey\lib\maven\...\bin\mvn.CMD`
    - Restart VS Code/terminal after adjusting PATH so `shutil.which('mvn')` from Python sees it.
  - Preferred: create a Maven wrapper in `d2l`:
    ```powershell
    cd d2l
    mvn -N io.takari:maven:wrapper
    cd ..
    ```
- Java: verify `java -version` or set `JAVA_HOME` in PowerShell for the session:
  ```powershell
  $env:JAVA_HOME = 'C:\Program Files\Java\jdk-17'  # or jdk-25 if intended
  $env:PATH = \"$env:JAVA_HOME\bin;${env:PATH}\"
  ```

### Environment variables and config
- `GITHUB_TOKEN` / `GH_TOKEN` if `git_pull_request` needs to use the GitHub API fallback.
- The agent default project path: `d2l` (some tools default to `d2l/codebase` historically; prefer `d2l`).

---

## VS Code MCP configuration

- `server.py` runs the FastMCP server. Start it in an activated venv:
  ```powershell
  python server.py
  ```
- In VS Code:
  - Ctrl+Shift+P → `MCP: Add Server` → enter `http://127.0.0.1:8000/sse` (as SSE).
  - Use the Chat/Tool view to call tools exposed by the MCP server.
- Model note: the prompt file `.github/prompts/tester.prompt.md` describes the agent behavior — the workspace uses `gpt-5-mini` as the model identifier in prompts so the agent knows the intended capabilities.

---

## How the Agent Workflow Works

Typical full cycle (`run_test_improvement_cycle` / `run_full_test_cycle`):
1. Selects the target project (`d2l`).
2. Runs `mvn test` via `mcp_tools.maven_helper.run_maven(...)`.
3. Parses JaCoCo XML via `mcp_tools.coverage.parse_jacoco_report`.
4. Calls `mcp_tools.coverage.find_uncovered_segments` to identify low coverage areas.
5. Generates JUnit skeletons for a subset via `mcp_tools.tests.generate_junit_tests`.
6. Re-runs `mvn test`.
   - If new tests fail, `mcp_tools.auto_fix.propose_fixes` analyzes stack traces and suggests low-risk edits.
   - Optionally apply safe fixes with `mcp_tools.auto_fix.apply_fix`.
7. If improvements meet policy, use `mcp_tools.git_tools.git_workflow_commit_and_push` (or stage/commit manually) to prepare commits and optionally create a PR.

End-to-end example (dry-run):
```powershell
python -c "from mcp_tools.agent_workflow import run_test_improvement_cycle; import json; print(json.dumps(run_test_improvement_cycle('d2l', do_commit=False, dry_run=True), indent=2, default=str))"
```

To run and actually stage a commit (you must be sure):
```powershell
python -c "from mcp_tools.agent_workflow import run_test_improvement_cycle; run_test_improvement_cycle('d2l', do_commit=True, dry_run=False)"
```
(Agent will refuse to commit to `main` unless `allow_main=True` is present in git helper.)

---

## Troubleshooting & FAQ

- Maven not found from Python subprocess
  - Symptom: `FileNotFoundError: [WinError 2]` when calling `subprocess.run(['mvn', ...])`.
  - Cause: Python subprocess sometimes fails to locate `mvn` if extension resolution isn't performed.
  - Fix: Ensure `C:\ProgramData\chocolatey\lib\maven\...\bin` is on PATH; restart terminal/VS Code. The project provides `mcp_tools/maven_helper.py` which uses `shutil.which('mvn')` and executes the resolved path (recommended).

- Raw `subprocess.run(['mvn', ...])` still fails
  - Use `mcp_tools.maven_helper.run_maven(...)` which calls the resolved executable path (e.g., `mvn.CMD`).

- JaCoCo plugin not found / `mvn jacoco:report` fails
  - Ensure `d2l/pom.xml` contains the JaCoCo plugin configuration; run `mvn verify` to generate `target/site/jacoco/jacoco.xml` and `index.html`.

- Test suite failures due to reflection / `InaccessibleObject` (modern JDK)
  - Symptom: tests failing with `java.lang.reflect.InaccessibleObjectException`.
  - Cause: module encapsulation in newer JDKs (JDK 17+ / 25).
  - Fixes used in this repo:
    - Added Surefire JVM args (`--add-opens` flags) in `d2l/pom.xml` to permit reflective access during tests.
    - Prefer setting `JAVA_HOME` to a supported JDK if needed.
  - Tradeoff: `--add-opens` is test-only and avoids changing production code.

- PNT timezone deprecation warnings
  - Symptom: many `WARNING: Use of the three-letter time zone ID "PNT" is deprecated...`.
  - Cause: legacy three-letter zone IDs used in some tests / inputs under new JDKs.
  - Mitigations implemented:
    - Tests/code normalized time zone usage where necessary (or Surefire JVM system properties set to a modern IANA zone).
    - These warnings are non-fatal; suppress by replacing legacy IDs or by test JVM properties.

- MCP server connection problems
  - Ensure `server.py` is running in the activated venv.
  - Confirm `.vscode/mcp.json` points to `http://127.0.0.1:8000/sse` (type `sse`).
  - If SSE connection fails, check CORS/ports and that the server is listening `127.0.0.1:8000`.

---

## Usage Examples

- Run a dry-run improvement cycle:
  ```powershell
  python -c "from mcp_tools.agent_workflow import run_test_improvement_cycle; import json; print(json.dumps(run_test_improvement_cycle('d2l', do_commit=False, dry_run=True), indent=2))"
  ```

- Run the MCP server (start tools for VS Code):
  ```powershell
  .\.venv\Scripts\Activate.ps1
  python server.py
  ```
  Then register `http://127.0.0.1:8000/sse` in VS Code MCP.

- Regenerate JaCoCo & full build:
  ```powershell
  cd d2l
  mvn clean verify
  # Open coverage:
  Start-Process .\target\site\jacoco\index.html
  ```

---

  ## Coverage

  - Short JaCoCo snapshot and link: `d2l/COVERAGE_SUMMARY.md`.
  - HTML report: `d2l/target/site/jacoco/index.html` (open in a browser or with PowerShell using `Start-Process`).

  See `d2l/COVERAGE_SUMMARY.md` for the current coverage numbers and links to the detailed report.


## Future Work & Limitations

- Dependence on JDK version: we added test-time JVM flags to support modern JDKs; long-term the library/tests should be made JDK version tolerant.
- Assumes a Maven-style Java project with `src/main/java` and `src/test/java`.
- The agent primarily targets a single project (`d2l`) by default; support for multiple projects or monorepos can be added.
- Auto-fixes are intentionally conservative. Complex fixes require human review.

---

## Files & Important Locations (quick reference)
- MCP server: `server.py`
- Maven helper: `mcp_tools/maven_helper.py`
- Orchestrator: `mcp_tools/agent_workflow.py`
- Test orchestration & generator: `mcp_tools/tests.py`
- Coverage tools: `mcp_tools/coverage.py`
- Git tools: `mcp_tools/git_tools.py`
- Auto-fix: `mcp_tools/auto_fix.py`
- Dashboard: `mcp_tools/dashboard.py` and `tools/generate_coverage_dashboard.py`
- Smoke harness: `scripts/smoke_test_agent.py`
- Prompt: `.github/prompts/tester.prompt.md`
- Target Java project: `d2l/` (contains `pom.xml`, `src/main/java`, `src/test/java`, `target/site/jacoco`)

---