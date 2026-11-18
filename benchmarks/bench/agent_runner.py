"""
Headless agent runner — drives the real Context Agent `Orchestrator` for one
task, exactly as the web dashboard does (create → plan → approve → execute),
with no browser and no human.

Nothing in the agent's source is modified. The harness only:
  * applies the runtime config overrides from settings.CONFIG_OVERRIDES,
  * supplies a headless stand-in for the WebSocket manager (auto-grants the
    dependency-install permission prompt instead of waiting 5 minutes),
  * wraps methods on the live objects to (a) switch features off for the
    ablation variants and (b) measure the self-healing loop.

Run as a subprocess (one per task, so memory is fully released between tasks):
    python -m bench.agent_runner --task bank_system --variant agent --out <dir>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import py_compile
import sys
import time
from pathlib import Path

from bench import settings

VARIANTS = {
    # v3 agent-loop engine (config.AGENT_ENGINE = "loop")
    "agent": "Agent loop (plan -> one conversation -> automatic checks -> fixes)",
    "no_checks": "Agent loop without automatic checks/repair rounds",
    "no_plan": "Agent loop without the read-only planning call",
    # older v2 engine, kept for before/after comparison
    "pipeline": "v2 pipeline (planner -> stubs -> one call per file -> fixer)",
    "no_context": "v2 pipeline, Context Engine disabled",
    "no_scaffold": "v2 pipeline, skeleton stubs disabled",
    "no_fixloop": "v2 pipeline, fix loop disabled",
    "no_graph": "v2 pipeline, Neo4j disabled",
}
LOOP_VARIANTS = {"agent", "no_checks", "no_plan"}


# ── Environment setup (must run before the agent's modules are imported) ──

def prepare_agent_env(variant: str = "agent"):
    sys.path.insert(0, str(settings.REPO_ROOT))
    import config
    config.OLLAMA_MODEL = settings.BENCH_MODEL   # read as a default arg at import time
    config.AGENT_ENGINE = "loop" if variant in LOOP_VARIANTS else "pipeline"
    if variant == "no_checks":
        config.AGENT_MAX_REPAIR_ROUNDS = 0
    if variant == "no_plan":
        config.AGENT_PLAN_FIRST = False
    applied = {"AGENT_ENGINE": {"original": "loop", "benchmark": config.AGENT_ENGINE}}
    for key, value in settings.CONFIG_OVERRIDES.items():
        applied[key] = {"original": getattr(config, key, None), "benchmark": value}
        setattr(config, key, value)
    return config, applied


class HeadlessWS:
    """Stand-in for backend.ws_manager.ConnectionManager.

    Every send_* method becomes an async no-op that just records the event.
    The install-permission prompt is answered 'yes' immediately.
    """

    def __init__(self, events_path: Path):
        self.orch = None
        self.events_path = events_path
        self.events: list[dict] = []

    def _record(self, kind: str, args, kwargs):
        ev = {"t": round(time.time(), 2), "kind": kind,
              "args": [str(a)[:500] for a in args],
              "kwargs": {k: str(v)[:200] for k, v in kwargs.items()}}
        self.events.append(ev)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")

    async def send_permission_request(self, *args, **kwargs):
        self._record("send_permission_request", args, kwargs)
        loop = asyncio.get_running_loop()
        # The orchestrator creates its Event *after* this call returns.
        loop.call_later(0.2, lambda: asyncio.ensure_future(self.orch.respond_permission(True)))

    def __getattr__(self, name):
        if not name.startswith("send_"):
            raise AttributeError(name)
        quiet = name in ("send_llm_token", "send_llm_thinking", "send_process_stdout", "send_process_stderr")

        async def _noop(*args, **kwargs):
            if not quiet:
                self._record(name, args, kwargs)
        return _noop


# ── Self-healing instrumentation ────────────────────────────────────────

def classify_error(text: str, verify_execution: bool) -> str:
    t = text or ""
    if "Ruff Lint Errors" in t:
        return "lint"
    if "Pyright Type Errors" in t:
        return "type"
    if "Syntax Error" in t or "placeholder" in t.lower():
        return "syntax"
    if "Pytest Output" in t:
        return "test"
    if verify_execution:
        return "runtime"
    return "integration"


def instrument_fix_loop(orch, fix_log):
    """Wrap _auto_fix / fixer.fix_error / runner.install_package to measure repairs.

    The harness independently re-checks lint/type/syntax repairs itself
    (Ruff + Pyright / py_compile) rather than trusting the agent's report.
    """
    counters = {"fixer_calls": 0, "installs": 0, "installs_ok": 0}
    orig_auto_fix = orch._auto_fix
    orig_fix_error = orch.fixer.fix_error
    orig_install = orch.runner.install_package

    async def fix_error(*a, **kw):
        counters["fixer_calls"] += 1
        return await orig_fix_error(*a, **kw)

    async def install_package(*a, **kw):
        counters["installs"] += 1
        res = await orig_install(*a, **kw)
        if getattr(res, "success", False):
            counters["installs_ok"] += 1
        return res

    async def auto_fix(file_path, error_text, verify_execution=True, **kw):
        category = classify_error(error_text, verify_execution)
        before_calls, before_inst = counters["fixer_calls"], counters["installs"]
        t0 = time.time()
        reported = await orig_auto_fix(file_path, error_text, verify_execution=verify_execution, **kw)
        verified, method = None, "agent_reported"
        full = orch.workspace_dir / file_path
        try:
            if category in ("lint", "type"):
                ok, _ = await orch.verifier.verify_file(file_path)
                verified, method = bool(ok), "ruff+pyright_recheck"
            elif category == "syntax" and full.suffix == ".py" and full.exists():
                try:
                    py_compile.compile(str(full), doraise=True)
                    verified = True
                except py_compile.PyCompileError:
                    verified = False
                method = "py_compile_recheck"
            elif category == "runtime":
                verified, method = bool(reported), "execution_verified_by_agent"
        except Exception as e:  # never let instrumentation break the run
            method = f"recheck_error: {e}"
        fix_log.append({
            "file": file_path,
            "category": category,
            "reported_fixed": bool(reported),
            "verified_fixed": verified,
            "verify_method": method,
            "attempts": counters["fixer_calls"] - before_calls,
            "auto_installs": counters["installs"] - before_inst,
            "seconds": round(time.time() - t0, 1),
            "error_head": (error_text or "")[:300],
        })
        return reported

    orch._auto_fix = auto_fix
    orch.fixer.fix_error = fix_error
    orch.runner.install_package = install_package
    return counters


# ── Ablations ───────────────────────────────────────────────────────────

def apply_variant(orch, variant: str):
    if variant == "no_context":
        orch.context_engine.build_context_for_file = lambda file_path, description="", *a, **k: ""
    elif variant == "no_scaffold":
        async def no_stubs(*a, **k):
            return {}
        orch.architect.generate_stubs = no_stubs
    elif variant == "no_fixloop":
        async def no_fix(*a, **k):
            return False
        orch._auto_fix = no_fix
    elif variant == "no_graph":
        if orch.brain and orch.brain.graph:
            orch.brain.graph.close()   # is_available -> False; agent degrades gracefully


# ── Main ────────────────────────────────────────────────────────────────

class PersistentLog(list):
    """A list whose appends are also written to a JSONL file, so fix events
    survive the process being stopped and are merged on resume."""

    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def append(self, item):
        super().append(item)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(item) + "\n")


def _read_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def _resumable(workspace: Path) -> bool:
    """True if a previous session got as far as an approved plan."""
    sf = workspace / "project_state.json"
    if not sf.exists():
        return False
    try:
        st = json.loads(sf.read_text(encoding="utf-8"))
    except Exception:
        return False
    return bool(st.get("plan_approved") and st.get("plan_steps"))


def _reset_outputs(out_dir: Path):
    """Fresh start: remove artifacts of an earlier, unfinished session (a
    non-empty target_dir would make the agent *ingest* it as an existing repo)."""
    import shutil
    ws = out_dir / "workspace"
    if ws.exists():
        shutil.rmtree(ws, ignore_errors=True)
    for name in ("llm_calls.jsonl", "events.jsonl", "fix_events.jsonl", "agent.log",
                 "heartbeat.json", "sessions.json"):
        try:
            (out_dir / name).unlink()
        except FileNotFoundError:
            pass


async def _heartbeat(out_dir: Path, prior: float, t0: float, info: dict):
    """Every 15 s record elapsed time (all sessions) and the current phase, so
    an interrupted run keeps its time and the console timer can show progress."""
    path = out_dir / "heartbeat.json"
    while True:
        info["elapsed_total"] = round(prior + time.time() - t0, 1)
        info["updated"] = time.time()
        try:
            path.write_text(json.dumps(info), encoding="utf-8")
        except Exception:
            pass
        await asyncio.sleep(15)


async def run(task_id: str, variant: str, out_dir: Path, resume: bool) -> dict:
    config, overrides = prepare_agent_env(variant)
    from bench.meter import install as install_meter
    meter = install_meter(out_dir / "llm_calls.jsonl")
    meter.set_context(task=task_id, variant=variant)

    from backend.orchestrator import Orchestrator   # noqa: E402 (after env prep)

    task = json.loads((settings.TASKS_DIR / task_id / "task.json").read_text(encoding="utf-8"))
    workspace = out_dir / "workspace"

    # Time already spent in earlier (interrupted) sessions of this run.
    sessions_path = out_dir / "sessions.json"
    sessions = []
    if resume and sessions_path.exists():
        try:
            sessions = json.loads(sessions_path.read_text(encoding="utf-8"))
        except Exception:
            sessions = []
    hb_path = out_dir / "heartbeat.json"
    prior = 0.0
    if resume and hb_path.exists():
        try:
            prior = float(json.loads(hb_path.read_text(encoding="utf-8")).get("elapsed_total", 0))
        except Exception:
            prior = 0.0
    sessions.append({"started": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "mode": "resume" if resume else "fresh", "prior_seconds": prior})
    sessions_path.write_text(json.dumps(sessions, indent=2), encoding="utf-8")
    workspace.mkdir(parents=True, exist_ok=True)

    ws = HeadlessWS(out_dir / "events.jsonl")
    orch = Orchestrator(ws)
    ws.orch = orch
    fix_log = PersistentLog(out_dir / "fix_events.jsonl")
    result = {"task": task_id, "variant": variant, "model": settings.BENCH_MODEL,
              "config_overrides": overrides, "phase": "create", "sessions": len(sessions)}
    t0 = time.time()
    hb_info = {"phase": "create", "task": task_id, "variant": variant}
    hb = asyncio.ensure_future(_heartbeat(out_dir, prior, t0, hb_info))
    counters = {}
    try:
        if resume:
            r = await orch.load_project(str(workspace))
        else:
            r = await orch.create_project(f"{task_id}_{variant}", task["prompt"], target_dir=str(workspace))
        if not r.get("success"):
            result.update(phase="create_failed", error=r.get("error"))
            return result
        result["graph_available"] = bool(orch.brain and orch.brain.graph.is_available)
        if variant != "no_fixloop":
            if variant not in LOOP_VARIANTS:
                counters = instrument_fix_loop(orch, fix_log)
        apply_variant(orch, variant)
        if variant == "no_graph":
            result["graph_available"] = False

        if not resume:
            result["phase"] = hb_info["phase"] = "plan"
            p = await orch.generate_plan(task["prompt"])
            result["plan_success"] = bool(p.get("success"))
            if not p.get("success"):
                result.update(phase="plan_failed", error=p.get("error"))
                return result
            await orch.approve_plan()
        else:
            result["plan_success"] = True
            orch.state.plan_approved = True
        result["planned_files"] = [s.file_path for s in orch.state.plan_steps]
        result["project_scale"] = orch.state.project_scale

        result["phase"] = hb_info["phase"] = "execute"
        remaining = max(60, settings.AGENT_RUN_TIMEOUT - prior)
        try:
            ex = await asyncio.wait_for(orch.execute_all(), timeout=remaining)
            result["execute_success"] = bool(ex.get("success"))
            result["phase"] = "done"
        except asyncio.TimeoutError:
            await orch.cancel_execution()
            result.update(execute_success=False, phase="timeout")

        steps = orch.state.plan_steps
        result["steps_total"] = len(steps)
        result["steps_completed"] = sum(1 for s in steps if s.status.value == "completed")
        result["final_status"] = orch.state.status
        result["fix_counters"] = counters
        result["engine"] = config.AGENT_ENGINE
        result["agent_loop"] = getattr(orch, "last_agent_result", None)
    except Exception as e:
        import traceback
        result.update(phase=f"crashed_in_{result['phase']}", error=f"{e}\n{traceback.format_exc()[-2000:]}")
    finally:
        hb.cancel()
        result["seconds"] = round(prior + time.time() - t0, 1)
        result["fix_events"] = _read_jsonl(out_dir / "fix_events.jsonl")
        result["llm_calls"] = len(_read_jsonl(out_dir / "llm_calls.jsonl"))
        try:
            if orch.brain:
                orch.brain.close()
        except Exception:
            pass
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    ap.add_argument("--variant", default="agent", choices=sorted(VARIANTS))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Resume an interrupted run if it got past planning; otherwise start clean.
    resume = _resumable(out_dir / "workspace")
    if not resume:
        _reset_outputs(out_dir)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(out_dir / "agent.log", encoding="utf-8")],
    )
    for noisy in ("httpx", "httpcore", "chromadb", "neo4j"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    logging.getLogger(__name__).info("=== session start (%s) ===", "resume" if resume else "fresh")
    try:
        result = asyncio.run(run(args.task, args.variant, out_dir, resume))
    except KeyboardInterrupt:
        # Stopped by the user: write nothing final, so the next run resumes.
        sys.exit(130)
    (out_dir / "run.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result.get(k) for k in ("task", "variant", "phase", "steps_completed",
                                                   "steps_total", "seconds", "llm_calls", "sessions")}))


if __name__ == "__main__":
    main()
