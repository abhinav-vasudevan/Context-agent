# Context Agent — Benchmarks

A self-contained harness that measures the Context Agent; the harness itself
never patches agent behaviour (only the ablation variants switch one feature off). It drives the real `Orchestrator` headlessly (exactly the
create → plan → approve → execute flow the dashboard uses) and grades the
generated projects with hidden tests.

## What is measured

| # | Metric | How |
|---|---|---|
| 1 | **Task success** — hidden-test pass rate, tasks 100% passing, programs that run without crashing | 8 multi-file Python projects, 58 hidden pytest tests the model never sees. Each test runs in its own process with a timeout. |
| 2 | **Agent vs single-shot baseline** | Same model, same temperature, same 16k context window; the baseline gets the identical spec and must write the whole project in one call. |
| 3 | **Ablations** | Re-run the agent with one feature switched off: `no_context`, `no_scaffold`, `no_fixloop`, `no_graph`. |
| 4 | **Context-window efficiency** | Every LLM call is metered (input size, output tokens, time, which component made it). Shows per-call prompts stay under the window while total processed tokens grow past it. |
| 5 | **Self-healing** | Every auto-fix is logged; lint/type/syntax repairs are **independently re-verified** by the harness (Ruff + Pyright / `py_compile`) rather than trusting the agent's own report. |

## Fairness rules built in

- Hidden tests live in `tasks/<id>/test_hidden.py`, outside every generated workspace.
- Tests only check names/behaviour stated in the spec, and find code **by symbol name**, so a project laid out as `src/core/bank.py` is graded the same as `bank.py`.
- Every task has a `reference/` solution that passes 100% of its tests (`python -m bench.grader --task <id> --workspace tasks/<id>/reference`).
- The task suite was frozen before any model run. Do not edit tasks or tests after seeing results.
- All runtime overrides (fix-attempt caps, timeouts, thread count) are recorded in each run's `environment.json` and the report.

## Tasks

| Task | Tests | What it exercises |
|---|---|---|
| `bank_system` | 8 | classes, custom exceptions, atomic transfers, CLI |
| `todo_manager` | 7 | dataclasses, sorting, JSON persistence, CLI |
| `inventory_system` | 8 | business rules, report formatting, CLI |
| `text_analyzer` | 7 | regex tokenising, statistics, stdin processing |
| `expression_evaluator` | 8 | lexer + recursive-descent parser, operator precedence |
| `gradebook` | 6 | statistics, ranking, CSV round-trip, CLI |
| `url_shortener` | 6 | base-62 codec, service logic, CLI |
| `tic_tac_toe` | 8 | game rules, minimax (exhaustively checked to never lose) |

## Running

Prerequisites: Ollama running with `llama3.1:8b` pulled; Neo4j running (optional — the report records whether it was).
**Close Chrome and other heavy apps first**: the model needs ~7.3 GB of RAM.

```powershell
cd benchmarks
python run.py --tasks bank_system --variants baseline,agent   # one task (~1–2 h on CPU)
python run.py --variants baseline,agent                        # full suite (overnight)
python run.py --variants no_context,no_fixloop --tasks gradebook,bank_system   # ablations
python run.py --report-only                                    # rebuild REPORT.md
```

- Runs are **resumable**: anything already graded is skipped, so Ctrl+C and re-run any time.
- One project at a time, each in its own process; a cooldown between tasks (`--cooldown`, default 90 s).
- The harness creates an Ollama tag `llama3.1-bench:8b` = `llama3.1:8b` with `num_thread 8` (same weights; measured fastest on this CPU and keeps the laptop responsive). Remove it any time with `ollama rm llama3.1-bench:8b`.

Results go to `results/<run>/`:
- `REPORT.md` — tables plus resume lines filled with the measured numbers
- `summary.json` — every aggregate number
- `<variant>/<task>/` — `run.json`, `grade.json`, `llm_calls.jsonl`, `events.jsonl`, `agent.log`, and the generated `workspace/`

## Layout

```
benchmarks/
  run.py                 entry point
  bench/settings.py      model, caps, timeouts (all overrides in one place)
  bench/agent_runner.py  headless Orchestrator run + ablations + fix-loop metering
  bench/baseline_runner.py  single-shot baseline
  bench/meter.py         per-LLM-call metering (reads the agent's existing log lines)
  bench/grader.py        hidden-test runner + smoke run
  bench/report.py        REPORT.md / summary.json
  tasks/<id>/            task.json (spec), test_hidden.py, reference/
  tasks/_support/discover.py  find symbols by name in a generated project
```
