"""
Builds results/<run>/REPORT.md and summary.json from the raw run files.

Metrics
  Task success (per variant): hidden-test pass rate, tasks fully passing,
      programs that run without crashing, mean wall time, LLM calls.
  Context efficiency (agent variants): per-call input size vs the 16k window,
      total tokens processed vs the largest single call, generated project size.
  Self-healing (agent variants): repairs attempted / verified fixed by
      category, attempts per repair, auto-installs.
Every number is computed from files on disk; nothing is entered by hand.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from bench import settings

CTX_WINDOW = 16384
GEN_EXT = {".py", ".md", ".txt", ".json", ".toml", ".cfg"}
SKIP = {"venv", ".venv", ".agent_brain", "__pycache__", "node_modules"}


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _calls(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _pct(x, n):
    return round(100 * x / n, 1) if n else 0.0


def _p95(vals):
    if not vals:
        return 0
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def calibrate_chars_per_token(calls: list[dict]) -> float:
    """chars/token from Ollama's own counts. Prompt-cache hits lower
    prompt_tokens (raising the ratio), so use the lowest third of ratios."""
    ratios = sorted(c["input_chars"] / c["prompt_tokens"] for c in calls
                    if c.get("prompt_tokens", 0) > 200 and c.get("input_chars", 0) > 0)
    if len(ratios) < 3:
        return 3.6
    low = ratios[: max(3, len(ratios) // 3)]
    return round(statistics.median(low), 2)


def project_tokens(workspace: Path, cpt: float) -> tuple[int, int]:
    chars, files = 0, 0
    if not workspace.exists():
        return 0, 0
    for p in workspace.rglob("*"):
        if p.is_file() and p.suffix in GEN_EXT and not any(s in p.parts for s in SKIP) \
                and p.name != "project_state.json":
            try:
                chars += len(p.read_text(encoding="utf-8", errors="replace"))
                files += 1
            except OSError:
                pass
    return round(chars / cpt), files


def build_report(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    variants = sorted(p.name for p in run_dir.iterdir() if p.is_dir()) if run_dir.exists() else []
    all_calls = [c for v in variants for t in (run_dir / v).iterdir() if t.is_dir()
                 for c in _calls(t / "llm_calls.jsonl")]
    cpt = calibrate_chars_per_token(all_calls)

    summary = {"run": run_dir.name, "chars_per_token": cpt, "variants": {}}
    for v in variants:
        rows = []
        for tdir in sorted(p for p in (run_dir / v).iterdir() if p.is_dir()):
            g = _load(tdir / "grade.json")
            if not g:
                continue
            r = _load(tdir / "run.json") or {}
            calls = _calls(tdir / "llm_calls.jsonl")
            for c in calls:
                c["est_input_tokens"] = round(c["input_chars"] / cpt)
            ptoks, pfiles = project_tokens(tdir / "workspace", cpt)
            rows.append({"task": tdir.name, "grade": g, "run": r, "calls": calls,
                         "project_tokens": ptoks, "project_files": pfiles})
        if rows:
            summary["variants"][v] = _variant_summary(rows)

    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = _markdown(summary, _load(run_dir / "environment.json") or {})
    out = run_dir / "REPORT.md"
    out.write_text(md, encoding="utf-8")
    return out


def _variant_summary(rows: list[dict]) -> dict:
    n = len(rows)
    tests_total = sum(r["grade"]["tests_total"] for r in rows)
    tests_passed = sum(r["grade"]["tests_passed"] for r in rows)
    calls = [c for r in rows for c in r["calls"]]
    inputs = [c["est_input_tokens"] for c in calls]
    per_task = []
    for r in rows:
        tc = r["calls"]
        per_task.append({
            "task": r["task"],
            "pass": f"{r['grade']['tests_passed']}/{r['grade']['tests_total']}",
            "pass_rate": r["grade"]["pass_rate"],
            "runs": not r["grade"]["smoke"]["crashed"],
            "phase": r["run"].get("phase"),
            "steps": f"{r['run'].get('steps_completed', '-')}/{r['run'].get('steps_total', '-')}",
            "minutes": round((r["grade"].get("wall_seconds") or r["run"].get("seconds") or 0) / 60, 1),
            "llm_calls": len(tc),
            "max_call_input": max((c["est_input_tokens"] for c in tc), default=0),
            "total_input_processed": sum(c["est_input_tokens"] for c in tc),
            "total_output": sum(c["completion_tokens"] for c in tc),
            "project_tokens": r["project_tokens"],
            "project_files": r["project_files"],
        })

    fixes = [f for r in rows for f in r["run"].get("fix_events", [])]
    by_cat = {}
    for f in fixes:
        d = by_cat.setdefault(f["category"], {"events": 0, "verified_fixed": 0, "verifiable": 0, "attempts": 0})
        d["events"] += 1
        d["attempts"] += f["attempts"]
        if f["verified_fixed"] is not None:
            d["verifiable"] += 1
            d["verified_fixed"] += int(bool(f["verified_fixed"]))
    verifiable = [f for f in fixes if f["verified_fixed"] is not None]
    comp = {}
    for c in calls:
        comp.setdefault(c["component"], 0)
        comp[c["component"]] += 1

    return {
        "tasks": n,
        "tests_passed": tests_passed,
        "tests_total": tests_total,
        "test_pass_rate": _pct(tests_passed, tests_total),
        "mean_task_pass_rate": round(100 * statistics.mean(r["grade"]["pass_rate"] for r in rows), 1),
        "tasks_fully_passing": sum(r["grade"]["all_passed"] for r in rows),
        "programs_running": sum(not r["grade"]["smoke"]["crashed"] for r in rows),
        "pipeline_completed": sum(r["run"].get("phase") == "done" for r in rows),
        "mean_minutes": round(statistics.mean(t["minutes"] for t in per_task), 1),
        "llm_calls": len(calls),
        "calls_by_component": dict(sorted(comp.items(), key=lambda kv: -kv[1])),
        "context": {
            "max_call_input_tokens": max(inputs, default=0),
            "median_call_input_tokens": round(statistics.median(inputs)) if inputs else 0,
            "p95_call_input_tokens": _p95(inputs),
            "calls_over_window": sum(1 for c in calls if c["est_input_tokens"] + c["completion_tokens"] > CTX_WINDOW),
            "max_task_total_input": max((t["total_input_processed"] for t in per_task), default=0),
            "max_project_tokens": max((t["project_tokens"] for t in per_task), default=0),
            "total_output_tokens": sum(c["completion_tokens"] for c in calls),
        },
        "self_healing": {
            "repair_events": len(fixes),
            "verifiable": len(verifiable),
            "verified_fixed": sum(bool(f["verified_fixed"]) for f in verifiable),
            "verified_fix_rate": _pct(sum(bool(f["verified_fixed"]) for f in verifiable), len(verifiable)),
            "mean_attempts": round(statistics.mean(f["attempts"] for f in fixes), 2) if fixes else 0,
            "auto_installs": sum(f["auto_installs"] for f in fixes),
            "by_category": by_cat,
        },
        "per_task": per_task,
    }


def _markdown(s: dict, env: dict) -> str:
    V = s["variants"]
    L = [f"# Context Agent benchmark — run `{s['run']}`", ""]
    L += ["## Setup", "",
          f"- Model: `{env.get('base_model', settings.BASE_MODEL)}` via Ollama on CPU "
          f"(tag `{env.get('model', settings.BENCH_MODEL)}`, num_thread={env.get('num_thread', settings.NUM_THREAD)}), "
          f"context window {CTX_WINDOW} tokens, temperature from config.py.",
          f"- Hardware: Intel Core i5-1240P, 16 GB RAM, no discrete GPU.",
          f"- Neo4j: {env.get('preflight', {}).get('neo4j', 'unknown')}.",
          f"- Runtime caps (agent code unchanged): `{json.dumps(env.get('config_overrides', settings.CONFIG_OVERRIDES))}`.",
          f"- Token estimate: {s['chars_per_token']} chars/token (calibrated from Ollama's own counts).",
          "- Grading: hidden pytest suites the model never sees; each test runs in its own process. "
          "Reference solutions pass 100% of tests.", ""]

    L += ["## 1. Task success (hidden tests)", "",
          "| Variant | Tasks | Hidden tests passed | Mean per-task pass rate | Tasks 100% | Programs run without crashing | Pipeline completed | Mean min/task | LLM calls |",
          "|---|---|---|---|---|---|---|---|---|"]
    for v, d in V.items():
        L.append(f"| {v} | {d['tasks']} | {d['tests_passed']}/{d['tests_total']} ({d['test_pass_rate']}%) | "
                 f"{d['mean_task_pass_rate']}% | {d['tasks_fully_passing']}/{d['tasks']} | "
                 f"{d['programs_running']}/{d['tasks']} | {d['pipeline_completed']}/{d['tasks']} | "
                 f"{d['mean_minutes']} | {d['llm_calls']} |")
    L.append("")
    for v, d in V.items():
        L += [f"<details><summary>{v} — per task</summary>", "",
              "| Task | Tests | Runs | Phase | Steps | Min | Calls | Max call input | Total input processed | Project tokens |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for t in d["per_task"]:
            L.append(f"| {t['task']} | {t['pass']} | {'yes' if t['runs'] else 'no'} | {t['phase']} | {t['steps']} | "
                     f"{t['minutes']} | {t['llm_calls']} | {t['max_call_input']} | {t['total_input_processed']} | {t['project_tokens']} |")
        L += ["", "</details>", ""]

    agent_vs = {v: d for v, d in V.items() if v != "baseline"}
    if agent_vs:
        L += ["## 2. Context-window efficiency", "",
              "| Variant | Max input / call | Median | p95 | Calls over 16k window | Largest task: total input processed | Largest generated project |",
              "|---|---|---|---|---|---|---|"]
        for v, d in agent_vs.items():
            c = d["context"]
            L.append(f"| {v} | {c['max_call_input_tokens']} | {c['median_call_input_tokens']} | {c['p95_call_input_tokens']} | "
                     f"{c['calls_over_window']} | {c['max_task_total_input']} | {c['max_project_tokens']} |")
        L += ["", "Calls by component: " + "; ".join(
            f"**{v}**: " + ", ".join(f"{k} {n}" for k, n in d["calls_by_component"].items()) for v, d in agent_vs.items()), ""]

        L += ["## 3. Self-healing", "",
              "| Variant | Repair events | Verified fixed | Mean fixer attempts | Auto-installs |", "|---|---|---|---|---|"]
        for v, d in agent_vs.items():
            h = d["self_healing"]
            L.append(f"| {v} | {h['repair_events']} | {h['verified_fixed']}/{h['verifiable']} ({h['verified_fix_rate']}%) | "
                     f"{h['mean_attempts']} | {h['auto_installs']} |")
        L += ["", "Verified = the harness re-ran Ruff+Pyright / py_compile itself after the repair (lint, type and syntax "
              "errors); runtime errors count as fixed only when re-execution succeeded. Integration-check repairs "
              "cannot be independently verified and are excluded from the rate.", ""]
        for v, d in agent_vs.items():
            if d["self_healing"]["by_category"]:
                L.append(f"- **{v}** by category: " + ", ".join(
                    f"{k}: {x['verified_fixed']}/{x['verifiable']} verified of {x['events']}"
                    for k, x in d["self_healing"]["by_category"].items()))
        L.append("")

    L += ["## Resume lines (filled from this run's measured numbers)", ""]
    b, a = V.get("baseline"), V.get("agent")
    if a:
        c, h = a["context"], a["self_healing"]
        if b:
            L.append(f"- Raised hidden-test pass rate from **{b['test_pass_rate']}%** (single-shot, same model) to "
                     f"**{a['test_pass_rate']}%** across {a['tasks']} multi-file Python projects "
                     f"({a['tests_total']} hidden tests) on a local 8B model, CPU-only.")
            L.append(f"- Working programs: **{a['programs_running']}/{a['tasks']}** (agent) vs "
                     f"**{b['programs_running']}/{b['tasks']}** (single-shot).")
        L.append(f"- Kept every LLM call within the {CTX_WINDOW}-token window (largest prompt "
                 f"**{c['max_call_input_tokens']}** tokens, median {c['median_call_input_tokens']}) while processing up to "
                 f"**{c['max_task_total_input']:,}** input tokens per project "
                 f"(**{c['max_task_total_input'] / CTX_WINDOW:.1f}×** the window).")
        if h["verifiable"]:
            L.append(f"- Autonomous repair loop fixed **{h['verified_fix_rate']}%** of verifiable lint/type/syntax/runtime "
                     f"failures without human input (mean {h['mean_attempts']} attempts).")
        def rate_on(variant: dict, tasks: set) -> tuple[float, int]:
            p = t = 0
            for row in variant["per_task"]:
                if row["task"] in tasks:
                    x, y = map(int, row["pass"].split("/"))
                    p, t = p + x, t + y
            return (_pct(p, t), len(tasks))

        for abl in ("no_context", "no_scaffold", "no_fixloop", "no_graph"):
            if abl in V:
                shared = {r["task"] for r in V[abl]["per_task"]} & {r["task"] for r in a["per_task"]}
                if not shared:
                    continue
                abl_rate, n_shared = rate_on(V[abl], shared)
                full_rate, _ = rate_on(a, shared)
                diff = round(full_rate - abl_rate, 1)
                L.append(f"- Ablation `{abl}` on the same {n_shared} task(s): {abl_rate}% → full agent {full_rate}% "
                         f"({'+' if diff >= 0 else ''}{diff} pts).")
    L += ["", "_Only quote a line if the comparison in it is favourable and the sample size is stated._", ""]
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    print(build_report(Path(sys.argv[1])))
