"""
Automatic checks run after the model says it is done (no LLM calls).

This plays the role of the language-server diagnostics that OpenCode/Claude
Code feed back after an edit: cheap, deterministic signals that catch the
mistakes a model can't see in its own output — cross-file name mismatches,
missing imports, syntax slips, a crash on start-up.

Checks (Python projects):
  1. Syntax           — compile() every .py file (in-process, instant).
  2. Ruff (pyflakes)  — undefined names, bad imports. Ruff's own safe --fix
                        removes unused imports first, so those never cost a
                        model round.
  3. Pyright          — only rules that mean the code is actually broken:
                        unknown attribute / method, wrong call arity,
                        undefined variable. Style and Optional-narrowing noise
                        is ignored.
  4. Smoke run        — start the entry point with stdin closed for a few
                        seconds. A traceback (other than EOFError from input())
                        is a real crash; a timeout means it is running fine.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from core.agent.actions import run_command
from core.agent.workspace import list_source_files

log = logging.getLogger(__name__)

PYRIGHT_RULES = {
    "reportAttributeAccessIssue",   # obj.missing_method / module has no attribute
    "reportCallIssue",              # wrong number / names of arguments
    "reportUndefinedVariable",
    "reportIndexIssue",
    "reportAbstractUsage",
}
MAX_PROBLEMS = 25


@dataclass
class Diagnostics:
    problems: List[str] = field(default_factory=list)
    checks_run: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def render(self) -> str:
        shown = self.problems[:MAX_PROBLEMS]
        more = f"\n(+{len(self.problems) - MAX_PROBLEMS} more)" if len(self.problems) > MAX_PROBLEMS else ""
        return "\n".join(f"- {p}" for p in shown) + more


def _tool(name: str, venv_path: Optional[Path]) -> Optional[str]:
    if venv_path:
        for sub in ("Scripts", "bin"):
            for exe in (f"{name}.exe", name):
                p = Path(venv_path) / sub / exe
                if p.exists():
                    return str(p)
    return shutil.which(name)


async def _exec(args: List[str], cwd: Path, timeout: int) -> tuple[Optional[int], str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd), stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
    except (FileNotFoundError, OSError) as e:
        return None, str(e)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None, "timeout"
    return proc.returncode, (out or b"").decode("utf-8", "replace") + (err or b"").decode("utf-8", "replace")


def find_entry_point(workspace: Path, files: List[str], hint: str = "") -> Optional[str]:
    if hint and hint in files and hint.endswith(".py"):
        return hint
    for cand in ("main.py", "app.py", "src/main.py", "cli.py", "run.py", "manage.py"):
        if cand in files:
            return cand
    return None


async def run_diagnostics(workspace: Path, venv_path: Optional[Path] = None,
                          entry_hint: str = "", smoke_run: bool = True,
                          use_pyright: bool = True, smoke_timeout: int = 12) -> Diagnostics:
    workspace = Path(workspace).resolve()
    diag = Diagnostics()
    files = list_source_files(workspace)
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return diag

    # 1. syntax
    diag.checks_run.append("syntax")
    broken = set()
    for rel in py_files:
        try:
            src = (workspace / rel).read_text(encoding="utf-8", errors="replace")
            compile(src, rel, "exec")
        except SyntaxError as e:
            broken.add(rel)
            diag.problems.append(f"{rel}:{e.lineno}: SyntaxError: {e.msg}")
    if broken:
        return diag            # other tools only produce noise on unparsable files

    # 2. ruff (pyflakes rules)
    ruff = _tool("ruff", venv_path)
    if ruff:
        diag.checks_run.append("ruff")
        await _exec([ruff, "check", "--fix", "--select", "F401", "--quiet", *py_files], workspace, 60)
        code, out = await _exec(
            [ruff, "check", "--select", "F,E9", "--ignore", "F401,F403,F405,F541,F811,F841",
             "--output-format", "concise", "--quiet", *py_files], workspace, 60)
        if code not in (0, None):
            for line in out.splitlines():
                line = line.strip()
                if line and ":" in line and not line.startswith(("Found", "[*]", "warning")):
                    diag.problems.append(line.replace("\\", "/"))

    # 3. pyright (broken-code rules only)
    pyright = _tool("pyright", None) if use_pyright else None
    if pyright:
        diag.checks_run.append("pyright")
        args = [pyright, "--outputjson"]
        if venv_path and Path(venv_path).exists():
            py = Path(venv_path) / ("Scripts/python.exe" if (Path(venv_path) / "Scripts").exists() else "bin/python")
            if py.exists():
                # relative: npm's pyright.cmd goes through cmd.exe, which splits
                # absolute paths containing '&' (e.g. "L&T")
                try:
                    args += ["--pythonpath", py.resolve().relative_to(workspace).as_posix()]
                except ValueError:
                    if "&" not in str(py):
                        args += ["--pythonpath", str(py)]
        code, out = await _exec(args + py_files, workspace, 180)
        try:
            start = out.find("{")
            data = json.loads(out[start:]) if start >= 0 else {}
            for d in data.get("generalDiagnostics", []):
                if d.get("severity") != "error" or d.get("rule") not in PYRIGHT_RULES:
                    continue
                f = Path(d.get("file", ""))
                try:
                    rel = f.resolve().relative_to(workspace).as_posix()
                except ValueError:
                    rel = f.name
                line = d.get("range", {}).get("start", {}).get("line", 0) + 1
                msg = " ".join(d.get("message", "").split())
                diag.problems.append(f"{rel}:{line}: {msg}")
        except (ValueError, json.JSONDecodeError):
            log.debug("pyright output not parseable: %s", out[:300])

    # 4. smoke run of the entry point
    entry = find_entry_point(workspace, files, entry_hint)
    if smoke_run and entry and not diag.problems:
        diag.checks_run.append(f"run {entry}")
        py = "python"
        code, out = await run_command(f'{py} "{entry}"', workspace, venv_path, smoke_timeout)
        if code not in (0, None) and "Traceback (most recent call last)" in out:
            tail = [ln for ln in out.strip().splitlines() if ln.strip()]
            last = tail[-1] if tail else ""
            benign = ("EOFError", "KeyboardInterrupt", "SystemExit")
            if not any(b in last for b in benign):
                excerpt = "\n".join(tail[-14:])
                diag.problems.append(f"Running `python {entry}` crashed:\n{excerpt}")
    return diag
