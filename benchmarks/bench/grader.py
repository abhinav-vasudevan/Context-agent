"""
Grader — runs a task's hidden tests against a generated workspace.

Each hidden test runs in its own subprocess with a timeout, so an infinite
loop or a crash in generated code fails that one test instead of hanging the
benchmark. The model never sees these tests: they live in
benchmarks/tasks/<task>/test_hidden.py, outside every generated workspace.

Also performs a smoke run of main.py with the task's sample stdin to record
whether the program runs end to end without crashing.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from bench import settings

SUPPORT_DIR = settings.TASKS_DIR / "_support"


def _env(workspace: Path) -> dict:
    env = dict(os.environ)
    env["BENCH_WORKSPACE"] = str(workspace.resolve())
    env["PYTHONPATH"] = str(SUPPORT_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _pytest(args: list[str], workspace: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, env=_env(workspace), cwd=str(settings.TASKS_DIR),
    )


def collect(task_id: str) -> list[str]:
    test_file = settings.TASKS_DIR / task_id / "test_hidden.py"
    res = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(test_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=_env(Path(".")), cwd=str(settings.TASKS_DIR), timeout=120,
    )
    return [ln.strip() for ln in res.stdout.splitlines() if "::" in ln]


def smoke_run(task: dict, workspace: Path) -> dict:
    """Run main.py with the task's sample stdin; crash = traceback, non-zero exit or hang."""
    sys.path.insert(0, str(SUPPORT_DIR))
    os.environ["BENCH_WORKSPACE"] = str(workspace.resolve())
    import importlib
    import discover
    importlib.reload(discover)
    try:
        proc = discover.run_main(task.get("smoke_stdin", "quit\n"), timeout=30)
        crashed = proc.returncode != 0 or "Traceback (most recent call last)" in proc.stderr
        return {"ran": True, "crashed": crashed, "exit_code": proc.returncode,
                "stderr_tail": proc.stderr[-400:]}
    except subprocess.TimeoutExpired:
        return {"ran": True, "crashed": True, "exit_code": None, "stderr_tail": "timeout (hang)"}
    except LookupError as e:
        return {"ran": False, "crashed": True, "exit_code": None, "stderr_tail": str(e)}


def grade(task_id: str, workspace: Path) -> dict:
    task = json.loads((settings.TASKS_DIR / task_id / "task.json").read_text(encoding="utf-8"))
    tests = collect(task_id)
    results = []
    for node in tests:
        name = node.split("::", 1)[1]
        try:
            res = _pytest([node], workspace, settings.PER_TEST_TIMEOUT)
            passed = res.returncode == 0
            reason = "" if passed else _failure_reason(res.stdout + res.stderr)
        except subprocess.TimeoutExpired:
            passed, reason = False, f"timeout after {settings.PER_TEST_TIMEOUT}s"
        results.append({"test": name, "passed": passed, "reason": reason})
    n_pass = sum(r["passed"] for r in results)
    py_files = [p for p in workspace.rglob("*.py")
                if not any(part in {"venv", ".venv", ".agent_brain", "__pycache__"} for part in p.parts)]
    return {
        "task": task_id,
        "tests_total": len(results),
        "tests_passed": n_pass,
        "pass_rate": round(n_pass / len(results), 4) if results else 0.0,
        "all_passed": bool(results) and n_pass == len(results),
        "smoke": smoke_run(task, workspace),
        "py_files": len(py_files),
        "tests": results,
    }


def _failure_reason(output: str) -> str:
    for pat in (r"^E\s+(.+)$", r"(\w+Error: .+)$"):
        m = re.search(pat, output, re.MULTILINE)
        if m:
            return m.group(1).strip()[:300]
    return output.strip().splitlines()[-1][:300] if output.strip() else "failed"


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--workspace", required=True)
    a = ap.parse_args()
    print(json.dumps(grade(a.task, Path(a.workspace)), indent=2))
