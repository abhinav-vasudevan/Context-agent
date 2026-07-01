# Context Agent: Advanced Agentic Coding System

**Context Agent**! This is a deterministic, highly-structured AI agent framework designed to architect, generate, and self-heal complex software projects autonomously. Instead of relying on unpredictable Multi-Agent DAGs that frequently lose context or hallucinate "code stitching," this system relies on a **Hierarchical Master Planner** and a **Concrete Context Engine** powered by Python AST parsing, Neo4j Graph Databases, and ChromaDB Vector Storage.

---

## 🛠️ Tools & Frameworks Used

- **FastAPI & Uvicorn**: The robust backend server handling REST API routes and WebSocket connections for real-time streaming, served by Uvicorn for high-performance async execution.
- **Python AST**: Used to deterministically parse generated Python files and extract true function signatures, classes, and imports.
- **Neo4j (Graphifyy)**: The core graph database that powers Graphifyy. It stores the project's entire knowledge graph (AST nodes, files, dependencies, symbols) for advanced Graph RAG and context filtering.
- **ChromaDB**: Acts as the semantic vector database to store file summaries, architecture specs, and natural language logic for hybrid retrieval.
- **OKF (Open Knowledge Format by Google)**: A highly-structured, strict markdown-based formatting paradigm. Files are stored in `.agent_brain/knowledge/*.md` and act as persistent, immutable system constraints. OKF allows the injection of architectural guardrails, specific coding guidelines, and domain knowledge directly into the LLM's primary system prompt, guaranteeing that the agent adheres to overarching project rules at every step of generation.
- **Ollama / LiteLLM**: The core LLM client layer. Interacts with local models (e.g., `llama3.1:8b`, `qwen:14b`) or cloud APIs (Groq, Gemini), managing streaming, JSON enforcement, and token limits.
- **Pydantic & Dataclasses**: Enforces strict data models for internal agent state validation (`ProjectState`, `PlanSteps`, `ArchitectureSpecs`).
- **Pytest & Venv**: The secure sandbox engine (`core/runner.py`) provisions isolated `venv` virtual environments for every project and uses `pytest` and `py_compile` to autonomously verify code execution and capture stack traces.
- **XML Tooling**: The Coder agent interacts with the workspace exclusively via strict XML tools (`<write_file>`, `<run_command>`, `<edit_file>`).

---

## 🧠 How We Break the Context Window

Traditional AI coding agents fail on large codebases because they attempt to cram the entire project into the LLM's context window, leading to hallucination or catastrophic forgetting. **Context Agent completely shatters this limitation using a two-pronged approach:**

1. **Output Scaling (Hierarchical Planner)**: The agent never writes a full app in one prompt. A Master Planner deduces the architecture and breaks it into a strict, dependency-ordered sequence of single-file generation steps.
2. **Input Scaling (Neo4j Graph + AST Registry)**: As the project grows to thousands of lines, the agent never reads the raw code of previously generated files. Instead, it maintains an **AST File Registry** (extracting only exact function/class signatures and imports). To compress this even further, the **Neo4j Knowledge Graph** dynamically queries the closest relational neighbors (`MATCH (f:File)-[*1..2]-(other_f:File)`) to the file currently being worked on. The LLM receives *only* the exact API signatures of the files it actually needs to integrate with, keeping the context window incredibly small, cheap, and deterministically accurate.
3. **Behavioral Scaling (Google OKF Integration)**: As a system scales, the LLM often forgets overarching architectural patterns, security rules, and code style. Instead of eating up the standard prompt context with these rules, we utilize Google's **Open Knowledge Format (OKF)**. By storing strict `.md` files in `.agent_brain/knowledge/`, these rules are embedded deeply and immutably into the absolute highest priority layer of the LLM's system prompt. This guarantees permanent, unshakeable alignment with the project's core philosophy regardless of how long the generation loop runs.

---

## 🏗️ The Complete Flow: From Prompt to Final Project

### Phase 1: Hierarchical Planning (V2 Architecture)
1. **Vision & Subsystems**: The user submits a prompt. The `MasterPlanner` processes it and generates a massive, high-level `ArchitectureSpec`. It breaks the system down into concrete **Subsystems**.
2. **Service Decomposition**: The planner iterates through each subsystem and breaks it down into individual **Services** and specific **Modules (files)**.
3. **Plan Flattening**: The nested architecture is flattened into sequential `PlanStep`s (always starting with an empty `main.py` and ending with `requirements.txt` and `README.md`).
4. **Approval**: The backend pauses and awaits the user's explicit approval (`/api/plan/approve`) before execution.

### Phase 2: Execution & Code Generation
Once the plan is approved, the `Orchestrator` begins the execution loop step-by-step:
1. **Context Assembly**: For each file, the `ContextAssembler` builds the LLM prompt. It injects:
   - The specific instructions for this file.
   - The **AST File Registry** (filtered dynamically using the Neo4j Graph to only show highly relevant APIs and function signatures from the rest of the project).
   - Past completed step summaries (retrieved via ChromaDB).
2. **Code Generation**: The `Coder` agent uses the assembled context and outputs raw code enclosed in strict XML tags (e.g., `<write_file path="...">`).
3. **Integration**: If the file is a Python module, the Orchestrator automatically generates a prompt to update `main.py` and securely imports the new module.

### Phase 3: Verification, QA, and Self-Healing
1. **Sandbox Execution**: The `Runner` securely tests the generated code (e.g., `python -m py_compile`).
2. **The Fixer Loop**: If a syntax or runtime error occurs, the Orchestrator captures the `stderr` traceback and hands it to the `Fixer` agent. The Fixer explores the workspace using `<view_file>` and patches the code using precise `<edit_file>` search/replace blocks until the error is resolved.
3. **Graph Ingestion**: Once a file is stable, the `Summarizer` agent reads the code, and the `ProjectBrain` ingests the file's AST into Neo4j and its semantic summary into ChromaDB, updating the Graphifyy knowledge base for future context queries.

---

## 🗂️ Directory & File Structure Deep Dive

Here is exactly what every core backend file does in the Context Agent ecosystem:

### `backend/`
The API and Orchestration layer.
- **`server.py`**: The FastAPI entry point. Defines all REST endpoints (`/api/project/create`, `/api/plan/approve`, `/api/execute/all`) and mounts WebSockets.
- **`orchestrator.py`**: The central state machine. Manages the lifecycle of a project, triggers the planner, iterates through plan steps, handles the Fixer fallback loops, and dispatches UI updates.
- **`ws_manager.py`**: Handles active WebSocket connections, streaming live LLM tokens, step statuses, and terminal outputs to the user.

### `core/`
The autonomous agent logic and tool-use layer.
- **`coder.py`**: Parses the LLM's XML responses (`<write_file>`, `<run_command>`) and writes the actual code to the secure project sandbox.
- **`context.py`**: The AST Context Assembler. Reads previously generated `.py` files using Python's `ast` module to extract exact function signatures, preventing LLM hallucinations during code stitching.
- **`fixer.py`**: The Self-Healing agent. Receives error tracebacks, builds context around the broken code, and autonomously issues `<edit_file>` search/replace blocks to fix bugs.
- **`llm_client.py`**: A robust wrapper for calling LLMs. Handles context-window truncation, token estimation, JSON schema enforcement, and streaming.
- **`planner.py`**: The legacy V1 flat planner.
- **`runner.py`**: The secure sandbox engine. Manages isolated virtual environments (`venv`) and executes user applications safely as subprocesses.
- **`qa_agent.py`**: A quality assurance agent that reviews code logic and structure.

### `core/planners/`
- **`master_planner.py`**: The V2 Hierarchical Planner. Uses multi-stage LLM calls to organically deduce large-scale system architectures (Subsystems -> Services -> Modules) from a single user prompt.

### `core/brain/` & `core/retrieval/` (Graphifyy Context Engine)
- **`project_brain.py`**: The main entry point for the V2 Context Engine. Orchestrates data flow into the graph and vector databases.
- **`knowledge_graph.py`**: Interfaces with Neo4j. Ingests AST file registries to map out structural dependencies (e.g., `Module A` -> `imports` -> `Function B`).
- **`semantic_store.py`**: Interfaces with ChromaDB. Stores natural language summaries of files, step descriptions, and architectural intents for similarity search.
- **`context_engine.py`**: The retrieval engine that fuses Graph queries (Neo4j) with Vector searches (ChromaDB) to dynamically filter the File Registry before passing it to the Coder agent.

### `core/agents/`
- **`summarizer.py`**: Analyzes generated files and writes ultra-dense, one-sentence functional summaries for the ChromaDB semantic store.

### `models/`
Strict data schemas ensuring type safety across the system.
- **`state.py`**: Defines `ProjectState`, `PlanStep`, and `FileEntry`.
- **`hierarchy.py`**: Defines the V2 architectural models: `ArchitectureSpec`, `SubsystemSpec`, `ServiceSpec`, and `ModuleSpec`.

### Root Files
- **`config.py`**: Centralized configuration hub (Token limits, API keys, Model names, Sandbox paths).
- **`cli.py`**: A command-line interface alternative to interact with the orchestrator.
- **`knowledge.json`**: Static memory rules and "gotchas" to guide the LLM.
- **`start.bat` / `start.sh`**: Bootstrap scripts to spin up the servers.
