# Context Agent benchmark — run `smoke2`

## Setup

- Model: `llama3.1:8b` via Ollama on CPU (tag `llama3.1-bench:8b`, num_thread=8), context window 16384 tokens, temperature from config.py.
- Hardware: Intel Core i5-1240P, 16 GB RAM, no discrete GPU.
- Neo4j: NOT running (knowledge graph features will be off).
- Runtime caps (agent code unchanged): `{"MAX_FIX_ATTEMPTS": 4, "MAX_QA_ATTEMPTS": 2, "MAX_QA_INTERACTIONS": 8, "QA_PROCESS_TIMEOUT": 120, "PROCESS_RUN_TIMEOUT": 120}`.
- Token estimate: 3.98 chars/token (calibrated from Ollama's own counts).
- Grading: hidden pytest suites the model never sees; each test runs in its own process. Reference solutions pass 100% of tests.

## 1. Task success (hidden tests)

| Variant | Tasks | Hidden tests passed | Mean per-task pass rate | Tasks 100% | Programs run without crashing | Pipeline completed | Mean min/task | LLM calls |
|---|---|---|---|---|---|---|---|---|
| agent | 1 | 2/8 (25.0%) | 25.0% | 0/1 | 1/1 | 0/1 | 797.8 | 13 |

<details><summary>agent — per task</summary>

| Task | Tests | Runs | Phase | Steps | Min | Calls | Max call input | Total input processed | Project tokens |
|---|---|---|---|---|---|---|---|---|---|
| bank_system | 2/8 | yes | timeout | 0/5 | 797.8 | 13 | 10309 | 43583 | 729 |

</details>

## 2. Context-window efficiency

| Variant | Max input / call | Median | p95 | Calls over 16k window | Largest task: total input processed | Largest generated project |
|---|---|---|---|---|---|---|
| agent | 10309 | 2883 | 7507 | 0 | 43583 | 729 |

Calls by component: **agent**: fixer 8, planner 3, scaffolding 1, coder 1

## 3. Self-healing

| Variant | Repair events | Verified fixed | Mean fixer attempts | Auto-installs |
|---|---|---|---|---|
| agent | 0 | 0/0 (0.0%) | 0 | 0 |

Verified = the harness re-ran Ruff+Pyright / py_compile itself after the repair (lint, type and syntax errors); runtime errors count as fixed only when re-execution succeeded. Integration-check repairs cannot be independently verified and are excluded from the rate.


## Resume lines (filled from this run's measured numbers)

- Kept every LLM call within the 16384-token window (largest prompt **10309** tokens, median 2883) while processing up to **43,583** input tokens per project (**2.7×** the window).

_Only quote a line if the comparison in it is favourable and the sample size is stated._
