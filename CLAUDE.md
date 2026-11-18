# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Context Agent is an autonomous AI coding system: given a natural-language prompt, it plans an architecture, writes every file, runs static analysis, and self-heals errors — with no cloud API keys required (runs against a local Ollama model by default; Groq/Gemini are optional cloud alternatives). It has a FastAPI backend, a React web dashboard, and a legacy terminal CLI. This repo is the agent's own source code, not a generated project — don't confuse the `.contextrules` file (a system prompt used when the agent generates *other* projects) with rules for working on this repo.

For a full architectural writeup, see `Context_Agent_Approach_Document.md`.

## Core Mission: Solving the LLM Context-Window Problem

**This is the actual problem the whole codebase exists to solve**, not an incidental feature. Every LLM has a finite context window (`config.OLLAMA_NUM_CTX`, default 16384 tokens), but real software projects blow past that in two independent directions:

- **Case 1 — Input too large**: an existing codebase to modify is millions of lines, or uploaded requirement docs are hundreds of pages.
- **Case 2 — Output too large**: the requested system (e.g. "build an OS") would require more code than any single generation call could produce.
- **Case 3 — Both at once**: adding a massive new feature to an already-massive existing codebase.

The system never tries to fit "everything" into one prompt. Instead it keeps a **persistent, queryable memory outside the LLM** (the Project Brain) and only ever pulls a small, relevant slice into any single call. When working on context-window-related bugs or features, orient around *which* of these three mechanisms is involved:

### How Case 1 (large input) is handled

1. **Deterministic structural extraction first, LLM second.** `FileRegistryBuilder` (`core/context.py`) parses Python with the stdlib `ast` module — zero LLM calls — to get exact class/function signatures. `ProjectBrain.update_graphify_knowledge()` (`core/brain/project_brain.py`) does the same at scale via the optional `graphify` package, extracting symbols/edges for every file into Neo4j.
2. **Per-file bounded summarization.** `RepositoryIngester.ingest_repository()` (`core/ingestion/ingester.py`) walks every source file and calls `SummarizerAgent.summarize_file()` (`core/agents/summarizer.py`) independently per file (concurrency capped via `asyncio.Semaphore(10)`), truncating each file to 4000 tokens before summarizing. **No matter how large the codebase is, no single LLM call ever sees more than one file.** Summaries land in ChromaDB (`SemanticStore`); AST facts land in Neo4j (`KnowledgeGraph`) — the aggregate knowledge lives in these two databases, never in one prompt.
3. **`UnderstandingAgent.analyze_codebase()`** (`core/agents/understanding_agent.py`) then synthesizes `architecture.md` and picks the entry point — but it reads only the *graph query results and stored summaries*, never raw file contents.
4. **At generation time**, `ContextEngine.build_context_for_file()` (`core/retrieval/context_engine.py`) retrieves a small relevant subgraph for the *one file being written*: architecture overview, owning subsystem, 2-hop related files (`KnowledgeGraph.get_related_files`), direct dependency AST signatures, top-5 semantically similar files (ChromaDB cosine search), top-3 relevant ADRs — all packed against an explicit `token_budget` (default 8000). This is the core insight documented in the module docstring: *"for a 50,000-file codebase, the LLM only needs to see ~50 relevant items to write any single file correctly."*
5. **Large uploaded documents** (PDF/TXT/MD) go through a different, proper **map-reduce**: `RecursiveCharacterChunker` (`core/ingestion/chunker.py`, 8000 chars/chunk, 400 overlap, paragraph→line→sentence→hard-split fallback) splits the doc; `UserDocumentIngester` (`core/ingestion/doc_ingester.py`) stores every chunk in ChromaDB; `ChatAgent.process_task()` (`backend/chat_agent.py`) maps an extraction prompt over each chunk of each doc, discards "not relevant" results, then reduces the surviving summaries into one final answer/spec. This is the most complete map-reduce implementation in the codebase — compare it to §6 below when the naive `SmartChunker` path is involved.

### How Case 2 (large output) is handled

1. **Hierarchical, staged planning** (`core/planners/master_planner.py`) — the LLM is never asked to output an entire codebase in one call. It progressively refines: `generate_vision()` (subsystems only) → `generate_services()` (services + file list per subsystem). Each stage's *output* is a small JSON document, not code.
2. **JIT Epic planning for large/massive projects.** `generate_epic_queue()` produces only high-level Epics (name, purpose, public API contract) up front — a small output regardless of final project size. `generate_sprint_plan()` is then called **once per Epic, lazily, right before that Epic executes** (`Orchestrator.execute_all`, the epic loop) — chunking the *output* temporally, not just spatially, so planning-call output size stays bounded no matter how many Epics the project ultimately needs.
3. **One file per plan step.** `MasterPlanner.flatten_to_plan_steps()` turns the hierarchy into atomic `PlanStep`s, each producing exactly one file. `Orchestrator._execute_step` / `Coder.generate_code_v2` generate one file per LLM call — total project output is unbounded in aggregate, but every individual call stays inside the context window.
4. **Contract-First scaffolding (Phase 0).** Before implementing any file body, `ArchitectAgent.generate_stubs()` (`core/agents/architect_agent.py`) cheaply generates signature-only stubs (`pass`/`NotImplementedError`, no logic) for a whole sprint's modules in one small-output call. This establishes API boundaries so that later full-implementation calls for sibling files never need to see each other's full bodies — only signatures via the File Registry / Context Engine.
5. **Checkpointing across sessions.** `CheckpointManager` (`core/checkpoint.py`) persists `(epic_id, step_number)` after every completed file, so a build that could never finish in one continuous run (or one context window's worth of conversation) can resume exactly where it left off, potentially across days.

### Case 3 (both)

Ingest mode + a large new feature request combines both: `RepositoryIngester` bounds the *input* side (per-file summarization → Brain), Epic/JIT planning + one-file-per-step bounds the *output* side, and `ContextEngine` ties them together so each generation step only ever sees a small relevant slice of both the huge existing code and the huge planned addition.

### Known gaps (be aware of these before "fixing" symptoms)

- **`SmartChunker` (`core/context.py`) is the naive path.** `Orchestrator.generate_plan()` calls `SmartChunker.chunk()` on an oversized raw user prompt but only keeps `chunks[0]` — the rest is silently discarded ("`[Prompt truncated for planning...]`"). This is *not* the same as the proper map-reduce used for uploaded documents (§Case 1.5) — if someone pastes a huge spec directly into the prompt box rather than uploading it as a file, it gets truncated, not map-reduced. Worth knowing if a bug report is "the agent ignored part of my huge prompt."
- **Several modules are defined but not wired into the live `Orchestrator` path**: `core/agents/test_generator.py`, `core/agents/design_reviewer.py`, `core/planner.py` (the "legacy flat planner"), `core/verification/static_analysis.py`, `core/verification/architecture_validator.py`. They're only referenced from the legacy `cli.py` or documentation, not from `backend/orchestrator.py`. Don't assume they run during a normal web-mode build.
- **`config.TOKEN_BUDGET_FILE_REGISTRY` / `TOKEN_BUDGET_STEP_DESC` / `TOKEN_BUDGET_SUMMARIES`** are declared in `config.py` but never read anywhere — only `TOKEN_BUDGET_SYSTEM_PROMPT` and `MIN_GENERATION_BUDGET` are actually used (in `SmartChunker` and `ContextAssembler`).

## Commands

### Backend (Python 3.10+)

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
python main.py              # starts FastAPI backend on 127.0.0.1:8088
```

There is no configured lint/test command for the backend itself (no pytest.ini/pyproject.toml at the root). `pytest` is a dependency used at runtime by the QA Agent to test *generated* projects, not this codebase.

### Frontend (Node 18+)

```bash
cd frontend
npm install
npm run dev       # Vite dev server, http://localhost:5173
npm run build
npm run lint       # eslint .
```

### Quick start (both servers)

`./start.sh` (Linux/macOS) or `start.bat` (Windows) launch backend + frontend together.

### External dependencies

- **Ollama** must be running (`ollama serve`) at `http://127.0.0.1:11434` with a model pulled (default `llama3.1:8b`, `config.py` mentions `qwen3.6:27b` as the recommended high-end model). Health-checked in `core/llm_client.py`.
- **Neo4j** (optional, bolt port 7687, default password `password`) — knowledge-graph features degrade gracefully if absent (`KnowledgeGraph.is_available`), as does ChromaDB (`SemanticStore.is_available`).
  - **All projects share one Neo4j database.** Isolation is by a `project` property (the resolved workspace path) on every node; `KnowledgeGraph` MERGEs on `(project, key)` and filters every query by it. Any raw Cypher passed to `KnowledgeGraph.execute_query` gets `$project` bound automatically and **must** filter on it (e.g. `MATCH (f:File {project: $project})`), or it will read other projects' data.

## Architecture

### Engines: `loop` (default) vs `pipeline`

`config.AGENT_ENGINE` selects how builds and follow-up requests run:

- **`loop` (v3, default)** — `core/agent/`, modelled on OpenCode (reference copy in `reference/opencode/`, not imported). One model, one conversation: the model acts through text action blocks (`### FILE` / `### EDIT` / `### READ` / `### SEARCH` / `### BRAIN` / `### RUN` / `### DONE`, parsed in `core/agent/actions.py`), then `core/agent/diagnostics.py` runs deterministic checks (syntax, ruff F-rules, pyright broken-code rules, smoke run of the entry point) and feeds problems back for up to `AGENT_MAX_REPAIR_ROUNDS`. **Fit or retrieve** (`core/agent/workspace.py`): if the project + task fit in `AGENT_FIT_FRACTION` of the input budget the model sees every file verbatim (nothing is split); otherwise it gets an AST repo map and pulls files with READ/SEARCH/BRAIN. When the conversation outgrows the window it is rebased from the files on disk. `Orchestrator.generate_plan` → `_generate_plan_loop` (one read-only plan call), `execute_all` → `_execute_loop`, follow-ups → `_run_agent`.
- **`pipeline` (v2)** — the hierarchical planner → stubs → one LLM call per file → fixer path described below. Kept for comparison (`benchmarks/` variant `pipeline`).

The Project Brain is indexed from the **AST, not an LLM**: `ProjectBrain.index_file_ast` writes File/Symbol nodes and real `IMPORTS`/`DEPENDS_ON` edges to Neo4j and a searchable descriptor to ChromaDB whenever a file is written or ingested. The old LLM `SummarizerAgent` was removed.

### Layered flow

`frontend/` (React/Vite dashboard) → `backend/server.py` (FastAPI REST + `/ws` WebSocket) → `backend/orchestrator.py` (`Orchestrator` class, the stateful engine) → `core/` (agents, planners, retrieval, verification) → `models/` (dataclass state).

**Everything hangs off one `Orchestrator` instance** (`backend/server.py` module-level `orchestrator = Orchestrator(ws_manager)`), which is driven identically by the FastAPI routes and by `cli.py`/`ui/terminal_ui.py` for the terminal mode. All user interaction (permission prompts, stdin to running processes, pause/resume) goes through asyncio `Event`s on the orchestrator, and all progress is pushed to the frontend via `ConnectionManager` (`backend/ws_manager.py`) over the single `/ws` socket — REST endpoints mostly just kick off `asyncio.create_task(...)` work and return immediately.

### Project lifecycle (see `Orchestrator` docstring in `backend/orchestrator.py`)

1. `create_project` → workspace dir under `projects/<name>/`, venv, and all V2 subsystems initialized (Brain, ContextEngine, agents, verifier, ingesters). If `target_dir` already has files, ingestion auto-triggers.
2. `generate_plan` → hierarchical planning (see Core Mission above), writes `architecture.md` / `plan.txt` / `project_state.json`, status becomes `plan_review`.
3. `approve_plan` → user/API approves.
4. `execute_all` → the NHIL ("No Human In The Loop") pipeline: per-Epic JIT sprint planning → Phase 0 scaffolding → Phase 1 write ALL files → Phase 2 install deps (pip/npm, with a permission prompt) → Phase 4 QA Agent runs the app and auto-fixes failures.
5. `send_input` / permission responses / pause / resume / retry / skip — all mid-execution control flows, backed by `asyncio.Event`s on the orchestrator instance.

State persists to `project_state.json` in the workspace (`models/state.py::ProjectState`) after essentially every mutation, so execution can resume across backend restarts (`load_project`, plus `CheckpointManager` in `core/checkpoint.py` for mid-Epic resumption).

### Per-step execution phases (`Orchestrator._execute_step`)

For each `PlanStep`: context retrieval (`ContextEngine.build_context_for_file`) → code generation (`core/coder.py::generate_code_v2`) → integration verification (`core/agents/integration_agent.py`) → incremental lint/type checks (`core/analyzer.py::IncrementalVerifier`, Ruff + Pyright) → TDD test run if a test stub exists (pytest) → summarization into the Project Brain (`core/agents/summarizer.py`) → AST re-parse into the legacy file registry (bridge for the fixer). Any failure at any phase routes into `Orchestrator._auto_fix`, which loops `core/fixer.py` (SEARCH/REPLACE-style patches with 4-level fuzzy matching, escalating to full-file rewrite after `MAX_SEARCH_FAILURES`, per `.contextrules` §4) up to `config.MAX_FIX_ATTEMPTS`, auto-installing missing modules on import errors.

### Follow-up requests (`Orchestrator.handle_manual_fix`)

User chat input after a project exists is intent-classified by the LLM into `bug_fix` (routes to `_auto_fix`), `feature_update` (routes to `_update_project`, appending new plan steps for re-approval), or `document_task` (routes to `ChatAgent`, the map-reduce doc Q&A path).

### Sandboxing / security (`core/runner.py`, `config.py`)

Generated projects run inside a per-project venv (`Runner`). `config.BLOCKED_COMMANDS` and `DANGEROUS_CODE_PATTERNS` hard-block destructive commands (`rm -rf`, `chmod`, `shutdown`, etc.) regardless of what the LLM tries to run/write. Path-traversal is checked via `Runner.security.is_within_workspace` before any `<write_file>`/`<edit_file>`/`<view_file>` tool call is honored. Process execution has timeouts (`config.PROCESS_RUN_TIMEOUT`, `QA_PROCESS_TIMEOUT`).

### `.contextrules` and `knowledge.json` — both dead

`.contextrules` reads like the strict system prompt for the *generated project's* LLM calls, and the README describes it that way — but **no code loads it**. `config.CUSTOM_RULES_FILE` is declared and never referenced. `ContextAssembler.custom_rules` is populated only from `<repo>/.agent_brain/knowledge/*.md`, a directory that doesn't exist (only `adrs/` and `chroma/` do). `knowledge.json` is likewise never read — `ContextAssembler.self.knowledge` is initialized to `""` and never assigned, yet is concatenated into the architect/planner system prompts.

The rules that actually govern generation live in the hard-coded system prompts in `core/context.py` and `core/planners/master_planner.py`. Don't edit `.contextrules` expecting behavior to change.

See `Context_Agent_Approach_Document_v2.md` §24 for the full audit of documentation-vs-implementation divergences.
