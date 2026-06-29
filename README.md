# Context Agent V2 — Autonomous Software Engineering Operating System

**Context Agent V2** is not just a chatbot, a coding assistant, or a simple code generator. It is an **Autonomous Software Engineering Operating System** designed to solve the fundamental context-window limitations of Large Language Models (LLMs). By utilizing a persistent external "Project Brain" and a hierarchical planning cascade, it enables the autonomous development, maintenance, modification, testing, refactoring, and evolution of software systems of arbitrary size.

This system is built to:
* Build production-ready applications from a single prompt.
* Work with codebases containing tens of thousands of files without hitting token limits.
* Maintain architectural understanding across months or years of development.
* Enforce security, linting, integration, and syntax correctness autonomously.

---

## 🏗️ The 8-Layer Cognitive Architecture

Context Agent V2 operates on an 8-layer architecture that separates reasoning, memory, execution, and verification into distinct cognitive sub-systems.

### LAYER 1: Orchestration Layer (`backend/orchestrator.py`)
The central nervous system. It drives the entire workflow, managing the state transitions from planning to execution, handling WebSocket communication with the frontend UI, and coordinating all other layers. It runs a deterministic loop, moving step-by-step and triggering auto-fix mechanisms if anything fails.

### LAYER 2: Planning Layer (`core/planners/`)
A hierarchical cascade that prevents the LLM from getting overwhelmed by massive requests. It scales dynamically based on the complexity of the user's prompt.
* **Master Planner**: Decomposes a user prompt into a high-level **System Vision**. It identifies massive architectural blocks (Subsystems).
* **Architecture Planner**: Defines the boundaries, constraints, and dependencies of those Subsystems. It also generates **Architectural Decision Records (ADRs)**.
* **Domain Planner**: Breaks Subsystems down into concrete logical Services.
* **Module Planner**: Breaks Services down into precise, individual file-level Modules with exact function signatures and exports.

### LAYER 3: Project Brain Layer (`core/brain/`)
The long-term persistent memory of the system. LLMs are stateless; the Project Brain is stateful. It consists of:
* **Knowledge Graph (Neo4j)**: Stores the structural relationships. It maps Nodes (Subsystems, Services, Files, Functions) via Edges (`OWNS`, `USES`, `DEPENDS_ON`, `IMPLEMENTS`). It allows the agent to answer questions like: *"If I change this database model, what UI components break?"*
* **Semantic Store (ChromaDB)**: Stores the meaning behind the code. It holds semantic summaries of every generated file and architectural decision, enabling fuzzy similarity searches (e.g., *"Find files that handle user authentication"*).
* **AST Registry**: A deterministic cache of actual Python file signatures (classes, functions, imports) parsed using the built-in `ast` module.

### LAYER 4: Context Retrieval Layer (`core/retrieval/context_engine.py`)
Replaces the naive "stuff everything into the prompt" approach. The Context Engine fuses Graph, Semantic, and AST data to build a highly focused, minimal context payload for the LLM. For any given file being generated, it dynamically fetches:
1. The overall Architecture Overview.
2. The owning Subsystem's constraints.
3. The exact AST signatures of direct dependencies.
4. Semantically similar files within a 2-hop radius.
5. Relevant Architectural Decision Records.

### LAYER 5: Engineering Layer (`core/coder.py`, `core/agents/`)
The layer responsible for actually writing and understanding code.
* **Coder**: Translates a plan step and the precise Context Engine payload into raw, runnable Python code. It is strictly forbidden from using placeholders (`# ...`).
* **Summarizer Agent**: A post-commit hook. After a file is written, it reads the raw code and extracts its semantic meaning, constraints, and risks, pushing this data back into the Project Brain (ChromaDB).
* **Integration Agent**: A pre-commit hook. Before a file is finalized, this agent verifies that the newly generated code correctly interfaces with the existing codebase (checking method signatures, async mismatches, etc.).

### LAYER 6: Verification Layer (`core/verification/`, `core/qa_agent.py`, `core/fixer.py`)
Ensures the system doesn't commit broken code.
* **Static Analyzer**: Uses deterministic tools (like Python's `ast` module) to catch syntax errors instantly before they reach runtime.
* **Architecture Validator**: Parses imports to ensure generated code doesn't violate the boundaries established in the Neo4j Knowledge Graph (e.g., catching if a UI file tries to directly import a database model instead of using an API layer).
* **QA Agent**: An autonomous testing agent that launches the generated application and uses the LLM to provide interactive inputs (stdin/stdout) exactly as a human tester would, hunting for runtime bugs.
* **Fixer**: The debugging loop. If any layer (Syntax, Integration, QA, or Execution) throws an error, the Fixer reads the traceback, isolates the buggy file, and issues targeted rewrite commands.

### LAYER 7: Knowledge Evolution Layer
Integrated within the Project Brain, this layer handles updates. As the codebase changes, the Knowledge Graph is dynamically updated with new edges, and ChromaDB is updated with new semantic summaries.

### LAYER 8: Execution Layer (`core/runner.py`)
The sandboxed runtime environment.
* **Sandboxing**: Runs all generated code inside an isolated Python virtual environment (`venv`).
* **Security Checker**: Scans commands against a strict blocklist (`rm`, `sudo`, `chmod`, `mv`, etc.) and enforces workspace-jail boundaries to prevent the AI from harming the host machine.
* **Dependency Management**: Autonomously parses and installs missing pip packages (with user permission).

---

## ⚙️ The Full Execution Flow

When a user submits a prompt, the system executes the following NHIL (No-Human-In-The-Loop) pipeline:

1. **Vision & Architecture Planning**: 
   The `MasterPlanner` converts the prompt into an `ArchitectureSpec` containing Subsystems, Services, Modules, and ADRs.
2. **Brain Ingestion**:
   The entire architecture is pushed into the Neo4j Knowledge Graph and ChromaDB Semantic Store.
3. **Execution Flattening**:
   The hierarchical architecture is flattened into sequential `PlanStep` objects.
4. **Iterative Generation Loop** (For each step):
   * **Context Retrieval**: The `ContextEngine` fetches the exact subgraph and semantic data needed for this specific file.
   * **Code Generation**: The `Coder` writes the file.
   * **Syntax Check**: The `StaticAnalyzer` verifies the code won't crash on import.
   * **Integration Check**: The `IntegrationAgent` ensures it uses other internal modules correctly.
   * **Architecture Check**: The `ArchitectureValidator` ensures it doesn't cross forbidden subsystem boundaries.
   * **Summarization**: The `SummarizerAgent` reads the file and updates the Project Brain.
   * *(If any check fails, the `Fixer` automatically kicks in to resolve it).*
5. **Dependency Installation**:
   The system identifies `requirements.txt` and requests user permission to install dependencies into the sandboxed venv.
6. **QA Testing**:
   The `QAAgent` boots up `main.py` and interacts with it, verifying the final integrated product.

---

## 🤖 Completely Automatic Auto-Fixing (No-Human-In-The-Loop)

You do **not** need to hold the agent's hand. The system is designed to be completely automatic, fighting through errors on its own until it delivers a finished, working project to you.

If an error occurs at **any point** in the pipeline, the system automatically intercepts it and fixes it:
* **Syntax Error?** The `StaticAnalyzer` catches it before runtime, sends the error trace to the `Fixer`, and the code is rewritten.
* **Missing Package?** If a runtime `ModuleNotFoundError` is thrown, the system parses the error, automatically runs `pip install <module>`, and re-runs the code.
* **Integration Mismatch?** If `main.py` calls a function with the wrong arguments, the `IntegrationAgent` detects the interface mismatch, and the `Coder` corrects it.
* **Runtime Crash during testing?** The `QAAgent` captures the full traceback and `stderr`, isolates exactly which file caused the crash, and triggers the `Fixer` loop.

The orchestrator will loop through these fixes automatically (up to a configured `MAX_FIX_ATTEMPTS`). As a user, you submit your prompt, step away, and return to a **fully tested, debugged, and functioning application**.

---

## 🔒 Security Protocols

Context Agent V2 operates with high autonomy, which necessitates strict security:
* **No Root Access**: The agent cannot execute `sudo`.
* **Restricted Commands**: The `SecurityChecker` blocks destructive commands (`rm`, `chmod`, `chown`, `mkfs`, `dd`).
* **Workspace Isolation**: All execution (`cwd`) is hard-locked to the project's specific directory within `projects/`. Path traversal (`../`) is blocked.
* **Virtual Environments**: Every project gets its own isolated `venv` to prevent polluting the host's Python installation.
* **Explicit Permission**: The system will *always* prompt the user via the UI before executing `pip install` on third-party requirements or booting up long-running tests.

---

## 📂 Data Models & State Tracking (`models/hierarchy.py`, `models/state.py`)

The system's state is fully JSON-serializable, allowing execution to be paused, resumed, or recovered after a crash.

* **ProjectState**: The massive God-object that tracks everything: the original prompt, the generated architecture, the flattened plan steps, the completion status of each step, LLM token usage metrics, and paths to the Project Brain databases.
* **ArchitectureSpec**: The root of the hierarchy. Contains `SubsystemSpec` objects and `ArchitectureDecisionRecord` (ADR) objects.
* **SubsystemSpec**: A major system block (e.g., "Networking"). Contains `ServiceSpec` objects.
* **ServiceSpec**: A logical grouping of functionality. Contains `ModuleSpec` objects.
* **ModuleSpec**: A concrete representation of a single file to be written.

---

## 🚀 Setup & Installation

### 1. Prerequisites
You must have the following installed on your host machine:
* Python 3.10+
* [Neo4j Desktop](https://neo4j.com/download/) (or run via Docker: `docker run -p 7687:7687 neo4j`)

### 2. Environment Variables
Ensure your `.env` or system environment contains:
```env
# Database Connections
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
NEO4J_DATABASE=neo4j

# LLM Providers (Choose one or multiple)
USE_GROQ=True
GROQ_API_KEY=your_groq_key
GROQ_MODEL=llama-3.3-70b-versatile

USE_GEMINI=False
GEMINI_API_KEY=your_gemini_key

# Ollama Fallback (Local)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```
*(Dependencies include `fastapi`, `uvicorn`, `httpx`, `neo4j`, `chromadb`, `pydantic`, `rich`, `websockets`)*

### 4. Run the Backend
Start the FastAPI orchestration server:
```bash
python -m backend.server
```
The backend will launch on `http://127.0.0.1:8000` and open a WebSocket connection for the frontend UI.

---

*Context Agent V2: Built to solve the context window, scale infinitely, and engineer autonomously.*
