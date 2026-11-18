"""
Symbol discovery for hidden tests.

Generated projects may place code anywhere (`bank.py`, `src/bank/core.py`,
`app/models.py` ...). Hidden tests therefore look a class/function up by NAME
rather than by path, so the agent and the baseline are graded on behaviour,
not on folder layout. The specification each task gives the model names every
required symbol.

Environment:
  BENCH_WORKSPACE  absolute path of the generated project to grade.
"""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path(os.environ.get("BENCH_WORKSPACE", ".")).resolve()
SKIP_DIRS = {"venv", ".venv", "env", ".agent_brain", "__pycache__", "node_modules",
             ".git", ".pytest_cache", "site-packages", "tests", "test"}

_cache: dict[str, object] = {}


def _source_files() -> list[Path]:
    files = []
    for p in WORKSPACE.rglob("*.py"):
        rel = p.relative_to(WORKSPACE)
        if any(part in SKIP_DIRS for part in rel.parts[:-1]):
            continue
        if p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py":
            continue
        files.append(p)
    # Prefer shallow paths, and non-entry-point files (main.py may run code on import)
    return sorted(files, key=lambda p: (p.name == "main.py", len(p.relative_to(WORKSPACE).parts), str(p)))


def _defines(path: Path, name: str) -> bool:
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    pat = rf"^(class|def|async def)\s+{re.escape(name)}\b|^{re.escape(name)}\s*[:=]"
    return re.search(pat, src, re.MULTILINE) is not None


def _import_file(path: Path):
    """Import a generated module the way the project itself would."""
    rel = path.relative_to(WORKSPACE).with_suffix("")
    for extra in {str(WORKSPACE), str(WORKSPACE / "src"), str(path.parent)}:
        if extra not in sys.path:
            sys.path.insert(0, extra)

    real_input = builtins.input

    def _no_input(*a, **k):
        raise EOFError("input() called during import")

    builtins.input = _no_input
    try:
        dotted = ".".join(rel.parts)
        try:
            return importlib.import_module(dotted)
        except Exception:
            if dotted != path.stem:
                return importlib.import_module(path.stem)
            raise
    finally:
        builtins.input = real_input


def load_symbol(name: str):
    """Return the first class/function/constant called `name` in the project."""
    if name in _cache:
        return _cache[name]
    errors = []
    for path in _source_files():
        if not _defines(path, name):
            continue
        try:
            mod = _import_file(path)
        except BaseException as e:  # SystemExit, EOFError, SyntaxError, ...
            errors.append(f"{path.relative_to(WORKSPACE)}: {type(e).__name__}: {e}")
            continue
        if hasattr(mod, name):
            _cache[name] = getattr(mod, name)
            return _cache[name]
    detail = "; ".join(errors) if errors else "no file defines it"
    raise LookupError(f"Required symbol '{name}' not found in generated project ({detail})")


def find_entry_point() -> Path:
    candidates = [p for p in WORKSPACE.rglob("main.py")
                  if not any(part in SKIP_DIRS for part in p.relative_to(WORKSPACE).parts[:-1])]
    if not candidates:
        raise LookupError("No main.py entry point in generated project")
    return min(candidates, key=lambda p: len(p.relative_to(WORKSPACE).parts))


def run_main(stdin_text: str, timeout: int = 30, args: list[str] | None = None) -> subprocess.CompletedProcess:
    """Run the project's main.py with the given stdin (from the project root)."""
    entry = find_entry_point()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(WORKSPACE), str(WORKSPACE / "src"), str(entry.parent)])
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(entry), *(args or [])],
        input=stdin_text, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=timeout, cwd=str(WORKSPACE), env=env,
    )
