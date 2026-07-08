# Context Agent: Advanced Agentic Coding System

**Context Agent**! This is a deterministic, highly-structured AI agent framework designed to architect, generate, and self-heal complex software projects autonomously. Instead of relying on unpredictable Multi-Agent DAGs that frequently lose context or hallucinate "code stitching," this system relies on a **Hierarchical Master Planner** and a **Concrete Context Engine** powered by Python AST parsing, Neo4j Graph Databases, and ChromaDB Vector Storage.

---

## 🛠️ Tools & Frameworks Used

- **FastAPI & Uvicorn**: The robust backend server handling REST API routes and WebSocket connections for real-time streaming, served by Uvicorn for high-performance async execution.
- **React & Vite**: A completely unified frontend Dashboard and Workspace UI that seamlessly switches between "Create Workspace" (from scratch), "Ingest Codebase" (existing projects), and "Docs Operations" (pure RAG).
- **Python AST**: Used to deterministically parse generated Python files and extract true function signatures, classes, and imports.
- **Neo4j (Graphifyy)**: The core graph database that powers Graphifyy. It stores the project's entire knowledge graph (AST nodes, files, dependencies, symbols) for advanced Graph RAG and context filtering.
- **ChromaDB & RecursiveCharacterChunker**: Acts as the semantic vector database to store file summaries, architecture specs, and natural language logic. Handles massive multi-document Map-Reduce chunking (e.g., PDFs, TXT, MD) to bypass LLM context constraints when summarizing or merging user requirements.
- **OKF (Open Knowledge Format by Google)**: A highly-structured, strict markdown-based formatting paradigm. Files are stored in `.agent_brain/knowledge/*.md` and act as persistent, immutable system constraints. OKF allows the injection of architectural guardrails, specific coding guidelines, and domain knowledge directly into the LLM's primary system prompt, guaranteeing that the agent adheres to overarching project rules at every step of generation.
- **Ollama / LiteLLM**: The core LLM client layer. Interacts with local models (e.g., `llama3.1:8b`, `qwen3.6:27b`) or cloud APIs (Groq, Gemini), managing streaming, JSON enforcement, and token limits.
- **Pydantic & Dataclasses**: Enforces strict data models for internal agent state validation (`ProjectState`, `PlanSteps`, `ArchitectureSpecs`).
- **Pytest & Venv**: The secure sandbox engine (`core/runner.py`) provisions isolated `venv` virtual environments for every project and uses `pytest` and `py_compile` to autonomously verify code execution and capture stack traces.
- **XML Tooling & Surgical Editing**: The Coder and Fixer agents interact with the workspace exclusively via strict XML tools:
  - `<write_file>`: For writing complete new files or completely overwriting existing ones.
  - `<edit_file>`: For precise SEARCH/REPLACE blocks. Crucially, the Context Engine dynamically reads the exact content of existing files into the prompt, forcing the LLM to use `edit_file` to surgically inject new features or patch bugs into the middle of massive files without deleting the surrounding code or breaking old functionality.
  - `<run_command>`: For securely executing terminal commands in the sandboxed workspace.

---

## 🚀 Getting Started (How to Run)

To run the Context Agent locally on your machine, you need to spin up both the FastAPI backend and the React/Vite frontend.

1. **Prerequisites**: Ensure you have Python 3.10+ and Node.js installed. Ensure you have Ollama running locally (e.g., `ollama run qwen3.6:27b`).
2. **Start the System**:
   From the root of the project, run the bootstrap script:
   ```bash
   ./start.sh
   ```
   *(On Windows, run `start.bat`)*
3. **Access the Dashboard**:
   Once the servers boot, open your browser and navigate to:
   **[http://localhost:5173](http://localhost:5173)**

---

## 🎮 How to Use the System

The unified frontend Dashboard offers three distinct operational modes based on your goals:

### 1. Build Mode (Create from Scratch)
- Select the **Build** tab.
- Enter a high-level prompt (e.g., "Build a multi-user JWT chat app").
- The system will analyze the prompt, run the `MasterPlanner`, and generate a hierarchical Epic-based architecture.
- Review the queued steps in the UI and click **Approve Plan** to start the autonomous code generation loop.

### 2. Ingest Mode (Modify Existing Codebase)
- Select the **Ingest** tab.
- Provide the **absolute path** to an existing project on your local machine (e.g., `/home/user/my_legacy_project`).
- Provide an instruction (e.g., "Add Google OAuth login").
- The system will first trigger the `UnderstandingAgent` to map out your existing AST and find your entry points. It will then generate an update plan that uses surgical `<edit_file>` operations to seamlessly weave the new feature into your existing code.

### 3. Docs Mode (Requirement Ingestion)
- Select the **Docs** tab.
- Upload massive requirement documents (PDF, TXT, MD).
- The system uses Map-Reduce chunking to semantically digest the documents and consolidate them into a dense master specification that guides the `MasterPlanner`.

---

## 🧠 How We Break the Context Window

Traditional AI coding agents fail on large codebases because they attempt to cram the entire project into the LLM's context window, leading to hallucination or catastrophic forgetting. **Context Agent completely shatters this limitation using a three-pronged approach:**

1. **Output Scaling (Hierarchical Planner)**: The agent never writes a full app in one prompt. A Master Planner deduces the architecture and breaks it into a strict, dependency-ordered sequence of single-file generation steps.
2. **Input Scaling (Neo4j Graph + AST Registry)**: As the project grows to thousands of lines, the agent never reads the raw code of previously generated files. Instead, it maintains an **AST File Registry** (extracting only exact function/class signatures and imports). To compress this even further, the **Neo4j Knowledge Graph** dynamically queries the closest relational neighbors (`MATCH (f:File)-[*1..2]-(other_f:File)`) to the file currently being worked on. The LLM receives *only* the exact API signatures of the files it actually needs to integrate with, keeping the context window incredibly small, cheap, and deterministically accurate.
3. **Behavioral Scaling (Google OKF Integration)**: As a system scales, the LLM often forgets overarching architectural patterns, security rules, and code style. Instead of eating up the standard prompt context with these rules, we utilize Google's **Open Knowledge Format (OKF)**. By storing strict `.md` files in `.agent_brain/knowledge/`, these rules are embedded deeply and immutably into the absolute highest priority layer of the LLM's system prompt. This guarantees permanent, unshakeable alignment with the project's core philosophy regardless of how long the generation loop runs.

---

## 🏗️ The Complete Flow: From Prompt to Final Project

### Phase 1: Ingestion & Complexity Analysis
1. **Codebase Ingestion (For Existing Projects)**: If pointing to an existing directory, the `RepositoryIngester` and the `UnderstandingAgent` scan the entire source code. They intelligently map the architecture and extract the exact starting entry point (e.g., `main.py`, `src/index.js`), completely eliminating hardcoded defaults. The AI is forced to stitch its new features seamlessly into this discovered architecture.
2. **Document Ingestion (Map-Reduce)**: If the user uploads massive requirement documents (PDFs, TXT), the system automatically chunks them using `RecursiveCharacterChunker` and extracts global master specifications, solving context window overflows before planning even begins.
3. **Scale Classification & Hierarchical Planning (V2 Architecture)**: For large projects, the `MasterPlanner` deduces overarching architectural constraints and breaks the system down into concrete **Epics** and **Subsystems**, then queues them.

### Phase 2: Scaffolding, Testing, & Code Generation
Once the plan is approved, the `Orchestrator` begins the execution loop step-by-step:
1. **Scaffolding (Skeleton Generation)**: The `ArchitectAgent` rapidly generates "stubs" or skeletons for every file in the Epic. These stubs contain only class names and function signatures with `pass` statements. This guarantees perfect imports and prevents "Module Not Found" errors during code generation.
2. **Test Generation (TDD)**: The `TestGeneratorAgent` reads the empty stubs and generates failing Unit Tests for every module based on the requirements.
3. **Context Assembly**: For each file, the `ContextAssembler` builds the LLM prompt. It injects the specific instructions and the **AST File Registry** (filtered dynamically using the Neo4j Graph). **Critically, if the file already exists, it injects the exact raw source code into the prompt and orders the LLM to use `<edit_file>`.**
4. **Code Generation**: The `CoderAgent` uses the assembled context to write the actual raw code logic enclosed in strict XML tags (`<write_file>` or `<edit_file>`).
5. **Integration**: The `IntegrationAgent` automatically wires the files together and securely imports the new modules.

### Phase 3: Verification, Deep Semantic Analysis, and Self-Healing
1. **Sandbox Execution**: The `Runner` securely tests the generated code (e.g., `python -m py_compile`).
2. **The Deep Semantic Analyzer (`core/analyzer.py`)**: Before the Fixer attempts any repair, the Orchestrator invokes the `StaticAnalyzer` which orchestrates three industry-grade semantic analysis tools running securely in the venv:
   - **Ruff** (`ruff check`): Executes lightning-fast analysis to catch syntax violations and basic linting errors.
   - **Pyright** (`pyright`): Performs deep semantic type-checking to catch logic errors, mismatched function signatures, and complex inheritance issues across the whole project graph.
   - **Semgrep** (`semgrep scan`): Scans the codebase for security vulnerabilities, hardcoded secrets, and complex AST-level anti-patterns.
3. **Deep Semantic Fixer Loop**: The Analyzer extracts the JSON output from all three tools and aggregates them into a highly structured Fix Prompt. The `Fixer` agent acts as an advanced automated debugger, exploring the workspace using `<view_file>`, cross-referencing semantic errors, and patching the code using precise `<edit_file>` search-and-replace blocks. It repeats this autonomously until all three semantic analyzers pass perfectly.
4. **Interactive State Rewind & Retry**: At any point during execution, if a step fails or produces conceptually flawed code, the user can hit the **Retry (`re`)** button in the UI. The Orchestrator gracefully intercepts this, instantly cancels the active LLM generation, rewinds the step status, and autonomously restarts the execution pipeline.
5. **Graph Ingestion**: Once a file is stable, the `Summarizer` agent reads the code, and the `ProjectBrain` ingests the file's AST into Neo4j and its semantic summary into ChromaDB, updating the Graphifyy knowledge base for future context queries.

---

## 🗂️ Directory & File Structure Deep Dive

Here is exactly what every core backend file does in the Context Agent ecosystem:

### `backend/`
The API and Orchestration layer.
- **`server.py`**: The FastAPI entry point. Defines all REST endpoints (`/api/project/create`, `/api/project/ingest`, `/api/plan/approve`, `/api/execute/all`) and mounts WebSockets.
- **`orchestrator.py`**: The central state machine. Manages the lifecycle of a project, triggers document and codebase ingestions, runs the planner, iterates through plan steps, handles the Fixer fallback loops, and dispatches UI updates.
- **`ws_manager.py`**: Handles active WebSocket connections, streaming live LLM tokens, step statuses, and terminal outputs to the user.
- **`chat_agent.py`**: The interactive chat agent that supports chunk-based Document RAG processing for massive files (Map-Reduce summarization).

### `core/`
The autonomous agent logic and execution layer.
- **`coder.py`**: Parses the LLM's XML responses (`<write_file>`, `<edit_file>`, `<run_command>`) and dynamically applies changes to the secure project sandbox.
- **`context.py`**: The AST Context Assembler. Reads previously generated `.py` files to extract exact function signatures, preventing LLM hallucinations. For existing files, it mandates surgical `<edit_file>` operations over destructive overwrites.
- **`fixer.py`**: The Self-Healing agent. Receives error tracebacks and autonomously issues search/replace blocks to fix bugs.
- **`llm_client.py`**: A robust wrapper for calling LLMs. Handles context-window truncation, token estimation, JSON schema enforcement, and streaming.
- **`runner.py`**: The secure sandbox engine. Manages isolated virtual environments (`venv`) and executes user applications safely as subprocesses.
- **`analyzer.py`**: The Static Semantic Analyzer. Orchestrates Pyright, Ruff, and Semgrep to deeply analyze generated code before triggering the `fixer.py` loop.
- **`checkpoint.py`**: Manages state snapshots for the interactive rewind/retry features.
- **`planner.py`**: The legacy V1 flat planner (superseded by `master_planner.py`).
- **`qa_agent.py`**: A quality assurance agent that reviews code logic and structure.

### `core/agents/`
Specialized sub-agents that handle specific lifecycle phases.
- **`architect_agent.py`**: Generates initial stubs/skeletons containing only class and function signatures.
- **`design_reviewer.py`**: Critiques generated implementation plans against OKF design constraints.
- **`integration_agent.py`**: Automatically wires generated files together and securely manages imports.
- **`summarizer.py`**: Analyzes generated files and writes ultra-dense functional summaries for the ChromaDB semantic store.
- **`test_generator.py`**: Reads empty stubs and generates failing Unit Tests for TDD workflows.
- **`understanding_agent.py`**: Traces execution paths in existing codebases to find true entry points (`<entry_point>`) and architect maps during codebase ingestion.

### `core/planners/`
- **`master_planner.py`**: The V2 Hierarchical Planner. Uses multi-stage LLM calls to organically deduce large-scale system architectures (Subsystems -> Services -> Modules) from a single user prompt.

### `core/brain/` & `core/retrieval/` (Graphifyy Context Engine)
- **`project_brain.py`**: The main entry point for the V2 Context Engine. Orchestrates data flow into the graph and vector databases.
- **`knowledge_graph.py`**: Interfaces with Neo4j. Ingests AST file registries to map out structural dependencies.
- **`semantic_store.py`**: Interfaces with ChromaDB. Stores natural language summaries for similarity search.
- **`context_engine.py`**: The retrieval engine that fuses Graph queries (Neo4j) with Vector searches (ChromaDB) to dynamically filter the File Registry.

### `core/ingestion/`
Tools for processing user inputs before generation.
- **`ingester.py`**: Scans user-provided codebases, triggering the `UnderstandingAgent` to automatically deduce entry points and architecture constraints for legacy project integration.
- **`doc_ingester.py`**: Manages the pipeline for parsing requirement documents.
- **`chunker.py` / `parser.py`**: Tools for recursive character chunking and parsing massive multi-format files (PDF, TXT, MD) into digestible segments for the LLM.

### `models/`
Strict data schemas ensuring type safety across the system.
- **`state.py`**: Defines `ProjectState`, `PlanStep`, and `FileEntry`.
- **`hierarchy.py`**: Defines the V2 architectural models: `ArchitectureSpec`, `SubsystemSpec`, `ServiceSpec`, and `ModuleSpec`.

### Root Files
- **`config.py`**: Centralized configuration hub (Token limits, API keys, Model names, Sandbox paths).
- **`cli.py`**: A command-line interface alternative to interact with the orchestrator.
- **`start.bat` / `start.sh`**: Bootstrap scripts to spin up the servers.
- **`fix_graph.py`**: Utility script to manually re-ingest a project's architecture into Neo4j for debugging.
