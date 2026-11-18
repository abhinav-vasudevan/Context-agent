"""
Context Agent benchmark runner.

Examples (run from the benchmarks/ folder):
    python run.py --tasks bank_system --variants baseline,agent          # one task, smoke test
    python run.py --variants baseline,agent                               # full suite
    python run.py --variants no_context,no_scaffold --tasks gradebook     # ablations
    python run.py --report-only --run main                                # rebuild the report

Runs are resumable at two levels - stop with Ctrl+C (or a crash/reboot) and
re-run the same command:
  * a (variant, task) pair that already has grade.json is skipped;
  * an agent run that was interrupted after its plan was approved resumes
    from the last fully written file (the agent saves its state after every
    file); its elapsed time and fix events carry over.
A live timer shows elapsed time for the current run, total time, and an ETA.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from bench import settings
from bench.agent_runner import VARIANTS

ALL_VARIANTS = ["baseline", *VARIANTS]


def all_tasks() -> list[str]:
    return sorted(p.parent.name for p in settings.TASKS_DIR.glob("*/task.json"))


# ── Preflight ───────────────────────────────────────────────────────────

def ensure_bench_model():
    """Create the num_thread-pinned model tag (same weights as BASE_MODEL)."""
    listing = subprocess.run(["ollama", "list"], capture_output=True, text=True).stdout
    if settings.BENCH_MODEL.split(":")[0] in listing:
        return
    modelfile = settings.BENCH_DIR / "bench" / "Modelfile"
    modelfile.write_text(f"FROM {settings.BASE_MODEL}\nPARAMETER num_thread {settings.NUM_THREAD}\n", encoding="utf-8")
    print(f"Creating Ollama tag {settings.BENCH_MODEL} (num_thread={settings.NUM_THREAD}) ...")
    subprocess.run(["ollama", "create", settings.BENCH_MODEL, "-f", str(modelfile)], check=True)


def preflight() -> dict:
    import httpx
    info = {}
    try:
        httpx.get("http://127.0.0.1:11434/api/tags", timeout=5).raise_for_status()
        info["ollama"] = "running"
    except Exception as e:
        sys.exit(f"Ollama is not running ({e}). Start it with `ollama serve` and retry.")
    ensure_bench_model()
    try:
        sys.path.insert(0, str(settings.REPO_ROOT))
        import config
        from neo4j import GraphDatabase
        d = GraphDatabase.driver(config.NEO4J_URI, auth=(config.NEO4J_USER, config.NEO4J_PASSWORD))
        d.verify_connectivity()
        d.close()
        info["neo4j"] = "connected"
    except Exception:
        info["neo4j"] = "NOT running (knowledge graph features will be off)"
    try:
        import ctypes

        class MEM(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MEM()
        m.dwLength = ctypes.sizeof(MEM)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        free_gb = m.ullAvailPhys / 1024 ** 3
        info["free_ram_gb"] = round(free_gb, 1)
        if free_gb < 6:
            print(f"WARNING: only {free_gb:.1f} GB RAM free. The model needs ~7.3 GB; "
                  f"close Chrome/other apps to avoid heavy swapping.")
    except Exception:
        pass
    return info


# ── Running ─────────────────────────────────────────────────────────────

# Rough first guesses (minutes) for the ETA until real runs have finished.
_DEFAULT_MINUTES = {"baseline": 5.0}
_DEFAULT_AGENT_MINUTES = 45.0


def _fmt(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def keep_awake(on: bool):
    """Stop Windows from sleeping while the benchmark runs (a sleeping laptop
    froze an earlier run for 12 h). Does not override closing the lid."""
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
        ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except Exception:
        pass


def _last_status(events_path: Path, state: dict) -> str:
    """Latest status message from the agent's events.jsonl (read incrementally)."""
    try:
        size = events_path.stat().st_size
    except OSError:
        return state.get("status", "")
    if size < state.get("pos", 0):
        state["pos"] = 0
    if size > state.get("pos", 0):
        with open(events_path, "rb") as f:
            f.seek(state.get("pos", 0))
            chunk = f.read().decode("utf-8", errors="replace")
            state["pos"] = size
        for line in chunk.splitlines():
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if ev.get("kind") == "send_status" and len(ev.get("args", [])) >= 2:
                state["status"] = ev["args"][1]
    return state.get("status", "")


def _prior_seconds(out: Path) -> float:
    try:
        return float(json.loads((out / "heartbeat.json").read_text(encoding="utf-8")).get("elapsed_total", 0))
    except Exception:
        return 0.0


def run_one(run_dir: Path, variant: str, task: str, progress: dict) -> dict:
    from bench.grader import grade
    out = run_dir / variant / task
    if (out / "grade.json").exists():
        print(f"  [skip] {variant}/{task} already graded")
        return json.loads((out / "grade.json").read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)

    if (out / "run.json").exists():
        # The run finished in an earlier session but wasn't graded yet.
        print(f"  [grade] {variant}/{task} (run already finished) ...", flush=True)
    else:
        module = "bench.baseline_runner" if variant == "baseline" else "bench.agent_runner"
        cmd = [sys.executable, "-m", module, "--task", task, "--out", str(out)]
        if variant != "baseline":
            cmd += ["--variant", variant]
        prior = _prior_seconds(out) if variant != "baseline" else 0.0
        resumed = variant != "baseline" and (out / "workspace" / "project_state.json").exists()
        label = f"{variant}/{task}"
        print(f"  [run ] {label}{'  (resuming, ' + _fmt(prior) + ' already done)' if resumed and prior else ''}", flush=True)

        t0 = time.time()
        stdout_f = open(out / "runner_stdout.txt", "w", encoding="utf-8", errors="replace")
        # Same console group as this process: Ctrl+C or closing the window stops both.
        proc = subprocess.Popen(cmd, cwd=str(settings.BENCH_DIR), stdout=stdout_f, stderr=subprocess.STDOUT)
        ev_state: dict = {}
        hard_limit = settings.AGENT_RUN_TIMEOUT + 900
        try:
            while proc.poll() is None:
                el = time.time() - t0
                if el > hard_limit:
                    proc.kill()
                    (out / "run.json").write_text(json.dumps({"task": task, "variant": variant, "phase": "hard_timeout",
                                                              "seconds": round(prior + el, 1)}), encoding="utf-8")
                    break
                status = _last_status(out / "events.jsonl", ev_state) if variant != "baseline" else "single LLM call"
                overall = time.time() - progress["t_start"]
                eta = progress["eta_fn"](variant, prior + el)
                line = (f"\r  [timer] {label}  {_fmt(prior + el)}  | total {_fmt(overall)}"
                        f"  | {progress['done']}/{progress['total']} done  | ETA ~{_fmt(eta)}  | {status[:60]}")
                sys.stdout.write(line.ljust(150)[:150])
                sys.stdout.flush()
                time.sleep(1)
        except KeyboardInterrupt:
            try:
                proc.wait(timeout=10)   # child got the Ctrl+C too and exits cleanly
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            stdout_f.close()
            print(f"\n\nStopped during {label}. Progress is saved - run the same command again to continue"
                  f"{' from the last finished file' if variant != 'baseline' else ''}.")
            keep_awake(False)
            sys.exit(130)
        stdout_f.close()
        sys.stdout.write("\r" + " " * 150 + "\r")
        if proc.returncode == 130:   # child got Ctrl+C itself
            print(f"\nStopped during {label}. Run the same command again to continue.")
            keep_awake(False)
            sys.exit(130)
        if not (out / "run.json").exists():
            (out / "run.json").write_text(json.dumps({"task": task, "variant": variant, "phase": "runner_crashed",
                                                      "exit_code": proc.returncode}), encoding="utf-8")

    run_info = json.loads((out / "run.json").read_text(encoding="utf-8"))
    g = grade(task, out / "workspace")
    g["variant"] = variant
    g["wall_seconds"] = run_info.get("seconds") or 0
    (out / "grade.json").write_text(json.dumps(g, indent=2), encoding="utf-8")
    print(f"  [done] {variant}/{task}: {g['tests_passed']}/{g['tests_total']} tests, "
          f"{'runs' if not g['smoke']['crashed'] else 'crashes'}, {g['wall_seconds'] / 60:.1f} min "
          f"(phase: {run_info.get('phase')})", flush=True)
    return g


def make_eta(run_dir: Path, pairs: list):
    """ETA = remaining runs x mean minutes of finished runs of that variant."""
    def mean_minutes(variant: str) -> float:
        vals = []
        for gp in (run_dir / variant).glob("*/grade.json"):
            try:
                vals.append(float(json.loads(gp.read_text(encoding="utf-8")).get("wall_seconds") or 0) / 60)
            except Exception:
                pass
        vals = [v for v in vals if v > 0]
        if vals:
            return sum(vals) / len(vals)
        return _DEFAULT_MINUTES.get(variant, _DEFAULT_AGENT_MINUTES)

    def eta(current_variant: str, current_elapsed: float) -> float:
        total = 0.0
        for v, t in pairs:
            if not (run_dir / v / t / "grade.json").exists():
                total += mean_minutes(v) * 60
        # subtract what the current run has already used (not below 0 for it)
        cur = mean_minutes(current_variant) * 60
        total -= min(current_elapsed, cur)
        return max(0.0, total)
    return eta


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", default="main", help="results folder name (results/<run>)")
    ap.add_argument("--tasks", default="all", help="comma-separated task ids, or 'all'")
    ap.add_argument("--variants", default="baseline,agent", help=f"comma-separated: {','.join(ALL_VARIANTS)}")
    ap.add_argument("--cooldown", type=int, default=settings.COOLDOWN_SECONDS)
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args()

    run_dir = settings.RESULTS_DIR / args.run
    if not args.report_only:
        tasks = all_tasks() if args.tasks == "all" else args.tasks.split(",")
        variants = args.variants.split(",")
        bad = [v for v in variants if v not in ALL_VARIANTS] + [t for t in tasks if t not in all_tasks()]
        if bad:
            sys.exit(f"Unknown variant/task: {bad}")
        info = preflight()
        run_dir.mkdir(parents=True, exist_ok=True)
        meta_path = run_dir / "environment.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        meta.update({"preflight": info, "model": settings.BENCH_MODEL, "base_model": settings.BASE_MODEL,
                     "num_thread": settings.NUM_THREAD, "config_overrides": settings.CONFIG_OVERRIDES,
                     "agent_run_timeout_s": settings.AGENT_RUN_TIMEOUT,
                     "started": meta.get("started", time.strftime("%Y-%m-%d %H:%M:%S"))})
        meta_path.write_text(json.dumps(meta, indent=2))
        print(f"Preflight: {info}")

        pairs = [(v, t) for t in tasks for v in variants]
        done = sum(1 for v, t in pairs if (run_dir / v / t / "grade.json").exists())
        print(f"{done}/{len(pairs)} runs already finished; {len(pairs) - done} to go. "
              f"Press Ctrl+C any time - re-run the same command to continue.\n")
        progress = {"t_start": time.time(), "done": done, "total": len(pairs), "eta_fn": make_eta(run_dir, pairs)}
        keep_awake(True)
        try:
            first = True
            for variant_task in pairs:
                variant, task = variant_task
                pending = not (run_dir / variant / task / "grade.json").exists()
                if pending and not first and args.cooldown:
                    try:
                        for left in range(args.cooldown, 0, -1):
                            sys.stdout.write(f"\r  cooling down {left:3d}s ...  (total {_fmt(time.time() - progress['t_start'])})")
                            sys.stdout.flush()
                            time.sleep(1)
                        sys.stdout.write("\r" + " " * 80 + "\r")
                    except KeyboardInterrupt:
                        print("\n\nStopped. Progress is saved - run the same command again to continue.")
                        sys.exit(130)
                if pending:
                    first = False
                run_one(run_dir, variant, task, progress)
                if pending:
                    progress["done"] += 1
        finally:
            keep_awake(False)
        print(f"\nAll runs finished in {_fmt(time.time() - progress['t_start'])} (this session).")

    from bench.report import build_report
    path = build_report(run_dir)
    print(f"\nReport: {path}")


if __name__ == "__main__":
    main()
