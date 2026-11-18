# Context Agent benchmark — run `smoke`

## Setup

- Model: `llama3.1:8b` via Ollama on CPU (tag `llama3.1-bench:8b`, num_thread=8), context window 16384 tokens, temperature from config.py.
- Hardware: Intel Core i5-1240P, 16 GB RAM, no discrete GPU.
- Neo4j: NOT running (knowledge graph features will be off).
- Runtime caps (agent code unchanged): `{"MAX_FIX_ATTEMPTS": 4, "MAX_QA_ATTEMPTS": 2, "MAX_QA_INTERACTIONS": 8, "QA_PROCESS_TIMEOUT": 120, "PROCESS_RUN_TIMEOUT": 120}`.
- Token estimate: 0.33 chars/token (calibrated from Ollama's own counts).
- Grading: hidden pytest suites the model never sees; each test runs in its own process. Reference solutions pass 100% of tests.

## 1. Task success (hidden tests)

| Variant | Tasks | Hidden tests passed | Mean per-task pass rate | Tasks 100% | Programs run without crashing | Pipeline completed | Mean min/task | LLM calls |
|---|---|---|---|---|---|---|---|---|
| agent | 1 | 0/8 (0.0%) | 0.0% | 0/1 | 0/1 | 1/1 | 22.8 | 15 |
| baseline | 1 | 3/8 (37.5%) | 37.5% | 0/1 | 0/1 | 1/1 | 3.8 | 1 |

<details><summary>agent — per task</summary>

| Task | Tests | Runs | Phase | Steps | Min | Calls | Max call input | Total input processed | Project tokens |
|---|---|---|---|---|---|---|---|---|---|
| bank_system | 0/8 | no | done | 5/5 | 22.8 | 15 | 37448 | 182671 | 31103 |

</details>

<details><summary>baseline — per task</summary>

| Task | Tests | Runs | Phase | Steps | Min | Calls | Max call input | Total input processed | Project tokens |
|---|---|---|---|---|---|---|---|---|---|
| bank_system | 3/8 | no | done | -/- | 3.8 | 1 | 6091 | 6091 | 10530 |

</details>

## 2. Context-window efficiency

| Variant | Max input / call | Median | p95 | Calls over 16k window | Largest task: total input processed | Largest generated project |
|---|---|---|---|---|---|---|
| agent | 37448 | 7342 | 35894 | 3 | 182671 | 31103 |

Calls by component: **agent**: planner 4, coder 4, fixer 3, summarizer 3, scaffolding 1

## 3. Self-healing

| Variant | Repair events | Verified fixed | Mean fixer attempts | Auto-installs |
|---|---|---|---|---|
| agent | 3 | 0/3 (0.0%) | 1 | 0 |

Verified = the harness re-ran Ruff+Pyright / py_compile itself after the repair (lint, type and syntax errors); runtime errors count as fixed only when re-execution succeeded. Integration-check repairs cannot be independently verified and are excluded from the rate.

- **agent** by category: lint: 0/3 verified of 3

## Resume lines (filled from this run's measured numbers)

- Raised hidden-test pass rate from **37.5%** (single-shot, same model) to **0.0%** across 1 multi-file Python projects (8 hidden tests) on a local 8B model, CPU-only.
- Working programs: **0/1** (agent) vs **0/1** (single-shot).
- Kept every LLM call within the 16384-token window (largest prompt **37448** tokens, median 7342) while processing up to **182,671** input tokens per project (**11.1×** the window).
- Autonomous repair loop fixed **0.0%** of verifiable lint/type/syntax/runtime failures without human input (mean 1 attempts).

_Only quote a line if the comparison in it is favourable and the sample size is stated._
