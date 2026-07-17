# Context Agent — Approach Document

---

## Table of Contents

1. [What This System Does](#1-what-this-system-does)
2. [The Core Problem It Solves](#2-the-core-problem-it-solves)
3. [Design Decision: Why a Single Orchestrator Loop](#3-design-decision-why-a-single-orchestrator-loop)
4. [System Architecture Overview](#4-system-architecture-overview)
5. [How the Planner Breaks Down Large Projects](#5-how-the-planner-breaks-down-large-projects)
6. [How the Context Engine Keeps the LLM Accurate](#6-how-the-context-engine-keeps-the-llm-accurate)
7. [How Code Gets Written and Verified](#7-how-code-gets-written-and-verified)
8. [How the Self-Healing Loop Works](#8-how-the-self-healing-loop-works)
9. [How Existing Codebases Are Ingested](#9-how-existing-codebases-are-ingested)
10. [How Large Documents Are Processed](#10-how-large-documents-are-processed)
11. [How Follow-Up Requests Work](#11-how-follow-up-requests-work)
12. [The Web Dashboard and Real-Time Communication](#12-the-web-dashboard-and-real-time-communication)
13. [Security and Sandboxing](#13-security-and-sandboxing)
14. [Every Tool, Framework, and Library Used](#14-every-tool-framework-and-library-used)
15. [Recommended LLM Models](#15-recommended-llm-models)
16. [Directory and File Reference](#16-directory-and-file-reference)
17. [How to Run the System](#17-how-to-run-the-system)

---

## 1. What This System Does

Context Agent is an AI-powered coding system. You tell it what software you want to build, and it does the rest:

- It plans the architecture, deciding which files to create and in what order
- It writes each file, one at a time, with full awareness of the files already written
- It checks every file for syntax errors, type mismatches, and code quality issues
- It fixes errors automatically and keeps trying until the code is clean
- It tests the final application and patches any runtime bugs

The system runs entirely on your local machine. It uses open-source language models through Ollama, so no internet connection or API keys are needed for basic operation.

---

## 2. The Core Problem It Solves

Every large language model has a hard limit on how many tokens (words and code symbols) it can read and write in a single request. This is called the **context window**. For chatbots answering questions, this limit rarely matters. For a system that writes entire software projects, it is the biggest obstacle.

The context window causes three specific failure modes:

### Failure Mode 1 — The Input Is Too Large

If an existing codebase has tens of thousands of lines of code, you cannot paste it all into the LLM prompt. The model either rejects the input outright or silently forgets earlier parts. This causes it to hallucinate function names, invent imports that do not exist, and break integration between files.

### Failure Mode 2 — The Output Is Too Large

If the user asks for a complex application, the model cannot write all the files in one response. It hits its output token limit and stops mid-file or mid-function, producing broken code.

### Failure Mode 3 — Updating Existing Code

Once a project is built, users want to add features or fix things. Traditional agents attempt to rewrite entire files from scratch to make a small change. This breaks existing functionality and wastes tokens.

### How Context Agent Solves All Three

| Problem | Solution |
|---------|----------|
| Input too large | The AST File Registry compresses the codebase into function signatures. The Neo4j graph filters to only the files relevant to the current step. |
| Output too large | The Hierarchical Planner breaks the project into single-file steps. Each step is one LLM call. |
| Updating existing code | The system injects the full source of existing files into the prompt and forces the LLM to use surgical edit operations instead of rewrites. |

---

## 3. Design Decision: Why a Single Orchestrator Loop

The most common pattern in AI coding systems is the multi-agent approach: a "Coder Agent" writes code, a "Reviewer Agent" checks it, a "Tester Agent" runs it, and they pass work back and forth. In practice, this approach has a specific weakness — the agents frequently lose track of what the codebase actually looks like. The Coder invents a function call, the Reviewer sends it back, and the Coder guesses a different wrong function. The root cause is not the multi-agent pattern itself; it is that no agent has a reliable, up-to-date map of the codebase.

Context Agent uses a different approach: a single orchestrator loop that controls every phase in a predictable sequence. The same orchestrator plans, writes code, runs analysis, and fixes bugs. At every phase, it has direct access to the AST File Registry — a deterministic map of every function signature, class definition, and import in the project. Because this map is built by parsing actual files (not by asking the LLM), it is always accurate.

This design is simpler, more predictable, and produces fewer cascading failures than multi-agent systems.

---

## 4. System Architecture Overview

The system is made of four main layers:

### Layer 1 — The Web Interface

A React dashboard served by Vite. It provides a real-time chat-style interface where you type prompts, see the plan, watch code being generated live, and monitor progress.

### Layer 2 — The API Server

A FastAPI backend that accepts REST requests and maintains WebSocket connections. It forwards all user actions to the orchestrator and streams results back to the frontend.

### Layer 3 — The Orchestrator

The central state machine. It manages the full lifecycle of a project — creating workspaces, generating plans, executing steps, running the fixer loop, and saving state. All other components are called by the orchestrator.

### Layer 4 — The Agent Layer

A collection of specialized modules that each handle one specific task:

| Agent | Responsibility |
|-------|---------------|
| **Master Planner** | Generates the architecture and breaks it into steps |
| **Coder** | Writes code by parsing LLM output into file operations |
| **Fixer** | Reads error messages and generates search/replace patches |
| **Runner** | Creates sandboxed virtual environments and executes code safely |
| **Context Engine** | Assembles the right context for each code generation step |
| **Integration Agent** | Wires files together by managing imports and references |
| **Summarizer** | Generates concise summaries of each file for the knowledge store |
| **Understanding Agent** | Maps the architecture of existing codebases during ingestion |
| **Architect Agent** | Generates skeleton files with function signatures before full generation |
| **QA Agent** | Tests the finished application and reports bugs |
| **Analyzer** | Runs Ruff and Pyright to catch lint and type errors |

---

## 5. How the Planner Breaks Down Large Projects

The planner works in stages:

### Stage 1 — Complexity Analysis

The planner reads the user's prompt and classifies the project into one of four scales:

- **Simple**: A single script or small utility (less than 5 files)
- **Medium**: A structured application with multiple modules (5 to 15 files)
- **Large**: A multi-subsystem application with distinct feature areas
- **Massive**: An enterprise-scale system with many independent domains

### Stage 2 — Epic Generation (Large and Massive Projects Only)

For large projects, the planner generates a queue of Epics. Each Epic is a self-contained feature domain with its own subsystem, public API contract, and list of dependencies on other epics. Epics are processed one at a time during execution.

### Stage 3 — Architecture Generation

For each scope (the whole project for simple/medium, or one Epic at a time for large/massive), the planner generates:

- **Subsystems**: High-level domains (for example, "Authentication", "Database", "API")
- **Services**: Components within each subsystem (for example, "UserService", "TokenService")
- **Modules**: Individual files with their purpose, file path, and which other modules they depend on

### Stage 4 — Step Flattening

The hierarchical architecture is flattened into a linear sequence of plan steps. Each step targets exactly one file and includes:

- A step number
- The file path (relative to the workspace root)
- A description of what the file should contain
- Which previous steps it depends on

The dependency order ensures that when the LLM writes step 5, all the files it needs to import from (steps 1 through 4) already exist.

---

## 6. How the Context Engine Keeps the LLM Accurate

When the coder writes a file, it needs to know what functions and classes are available in the other files. Sending the full source code of every file would overflow the context window. The Context Engine solves this with two complementary techniques:

### The AST File Registry

After each file is written, the system parses it using Python's `ast` module (Abstract Syntax Tree). It extracts:

- Every function name and its full signature (arguments and return type)
- Every class name and its methods
- Every import statement

This produces a compact text representation that looks like:

```
── app/auth.py ──
Functions:
  - create_token(user_id: str, secret: str) -> str
  - verify_token(token: str, secret: str) -> dict
Classes:
  - AuthManager
      Methods: login(email, password), logout(user_id)
Imports:
  - from app.models import User
  - import jwt
```

This compressed view is a fraction of the size of the actual source code, but it gives the LLM everything it needs to write correct imports and function calls.

### The Knowledge Graph (Neo4j)

As files are written, the system stores their relationships in a Neo4j graph database. Each file is a node, and edges represent imports, dependencies, and shared data structures.

When assembling context for a new file, the Context Engine queries the graph to find only the files that are directly related to the one being written. If step 7 is writing `api/routes.py`, the engine retrieves the AST signatures of `models/user.py`, `services/auth.py`, and `config.py` — but not `utils/logging.py` or `tests/test_auth.py`, because they are not directly connected.

### The Semantic Store (ChromaDB)

In addition to structural relationships, the system stores natural language summaries of each file in ChromaDB. When the graph alone does not provide enough context (for example, when the file being written does not have obvious structural dependencies), the engine performs a similarity search to find files that are semantically related to the current task.

---

## 7. How Code Gets Written and Verified

Each plan step goes through this sequence:

### Phase 0 — Skeleton Scaffolding

Before any real code is written, the Architect Agent generates empty stubs for every file in the current scope. Each stub contains class names and function signatures with `pass` statements. This guarantees that imports work correctly from the very first step — no "Module Not Found" errors during generation.

### Phase 1 — Code Generation

For each step, the system:

1. Assembles context using the Context Engine (AST registry + graph + semantic search)
2. Reads the existing file if one was created during scaffolding
3. Builds a prompt that includes the step description, the context, and the current file content
4. Sends the prompt to the LLM with strict instructions to use XML tool tags
5. Parses the LLM response and applies the file operations

The LLM communicates using three XML tools:

- `<write_file>`: Creates a new file or completely overwrites an existing one
- `<edit_file>`: Applies a precise search/replace block within an existing file
- `<run_command>`: Executes a shell command in the sandboxed workspace

When an existing file is injected into the prompt, the LLM is explicitly instructed to use `<edit_file>` instead of `<write_file>` to avoid destroying previously written code.

### Phase 2 — Dependency Installation

After all files are written, the system checks for `requirements.txt` and `package.json`. If found, it asks for permission and then installs Python and Node.js dependencies.

### Phase 3 — Verification

Each Python file goes through:

1. **Integration check**: The Integration Agent verifies that imports and function calls match the actual signatures in the codebase
2. **Static analysis**: Ruff checks for syntax and style issues. Pyright checks for type errors.
3. **Test execution**: If test files were generated, Pytest runs them

Any failures trigger the self-healing loop.

### Phase 4 — QA Testing

The QA Agent runs the finished application and interacts with it programmatically. It sends inputs, reads outputs, and checks for crashes or unexpected behavior. If it finds bugs, they go to the fixer.

---

## 8. How the Self-Healing Loop Works

When an error is detected (syntax error, type error, runtime crash, test failure), the fixer takes over:

1. **Error targeting**: The fixer reads the error traceback and identifies which file contains the actual bug. It traces through the stack to find the deepest file within the workspace.

2. **Context assembly**: It reads the full source of the broken file and assembles context from related files using the AST registry.

3. **Fix generation**: It sends the error, the file content, and the context to the LLM. The LLM responds with `<edit_file>` blocks containing precise search/replace patches.

4. **Fix application**: The patches are applied to the file.

5. **Verification**: The file is re-checked (syntax, lint, type check, or re-execution depending on the error type).

6. **Retry or escalate**: If the error persists, the loop repeats with the new error message. The system keeps track of previous fix attempts to avoid repeating the same fix. If the maximum number of attempts is reached, the step is paused and the user is notified.

The fixer also handles a special case automatically: if the error is a missing Python package (`ModuleNotFoundError`), it installs the package using pip before retrying.

---

## 9. How Existing Codebases Are Ingested

When a user points the system at an existing project directory:

1. **File scanning**: The Repository Ingester walks through all files in the directory, skipping hidden folders, virtual environments, and cache directories.

2. **Architecture understanding**: The Understanding Agent reads the codebase and generates a structured analysis. It identifies the entry point (for example, `main.py` or `src/index.js`), maps out the module structure, and documents the key architectural patterns.

3. **AST extraction**: Every Python file is parsed to extract function signatures, class definitions, and imports. These are stored in the File Registry.

4. **Summarization**: The Summarizer Agent writes a concise description of each file. These summaries are stored in ChromaDB for semantic search.

5. **Graph ingestion**: File relationships (imports, dependencies) are stored in the Neo4j knowledge graph.

After ingestion, when the user asks for a change, the planner generates steps that use `<edit_file>` operations to modify existing files instead of creating new ones from scratch.

---

## 10. How Large Documents Are Processed

Users can upload requirement documents (PDF, TXT, MD). These documents can be much larger than the LLM context window, so they go through a map-reduce pipeline:

1. **Parsing**: PDF files are read with PyPDF2. Text and markdown files are read directly.

2. **Chunking**: The Recursive Character Chunker splits the document into segments of approximately 8,000 characters each, with a 400-character overlap between chunks to preserve context at boundaries.

3. **Chunk summarization (Map phase)**: Each chunk is sent to the LLM individually with a prompt asking for a concise summary of the key requirements, features, and technical details.

4. **Consolidation (Reduce phase)**: All chunk summaries are combined and sent to the LLM again, asking it to produce a single master specification that captures every requirement.

5. **Storage**: The master specification is stored in the project state and in ChromaDB. When the planner generates the architecture, it receives this specification as part of its input.

This approach allows the system to process documents of any length — hundreds of pages if needed — while only ever sending small chunks to the LLM at a time.

---

## 11. How Follow-Up Requests Work

After a project is built, users can send follow-up requests through the chat interface. The system classifies each request into one of three types:

### Bug Fix

If the user pastes an error message or describes a broken feature, the system routes it directly to the fixer. It identifies the target file from the error traceback and enters the self-healing loop.

### Feature Update

If the user asks for a new feature ("add a login page") or a structural change ("switch the database from SQLite to PostgreSQL"), the Master Planner generates new plan steps. These steps are appended to the existing plan with proper dependency ordering. The user reviews and approves them, and then execution resumes.

The planner has full awareness of the existing codebase through the File Registry and knowledge graph. New steps use `<edit_file>` for existing files and `<write_file>` only for genuinely new files.

### Document Task

If the user asks a question about uploaded documents or wants to summarize them, the Chat Agent handles it using the map-reduce chunking pipeline.

---

## 12. The Web Dashboard and Real-Time Communication

The frontend is a React application built with Vite and styled with TailwindCSS. It connects to the backend through two channels:

### REST API

All user actions (create project, generate plan, approve, upload files) are sent as HTTP requests to FastAPI endpoints.

### WebSocket

A persistent WebSocket connection streams real-time updates from the backend to the frontend:

- **LLM token streaming**: Each token generated by the LLM is sent to the frontend as it is produced, creating a live typing effect
- **Step status updates**: As each step starts, completes, or fails, the UI updates the plan panel
- **Process output**: Terminal output from running code is streamed to the output panel
- **Error notifications**: Errors are highlighted in real-time

The WebSocket manager handles multiple simultaneous connections and gracefully handles disconnections.

---

## 13. Security and Sandboxing

The system takes several measures to prevent generated code from causing damage:

### Blocked Commands

A list of dangerous commands is maintained in `config.py`. The system never executes:

- File deletion commands (`rm`, `del`, `rmdir`)
- Permission changes (`chmod`, `chown`, `sudo`)
- System commands (`shutdown`, `reboot`, `format`)

### Dangerous Code Patterns

Before any generated Python code is written to disk, it is scanned for patterns like:

- `os.remove()`, `shutil.rmtree()`, `os.unlink()`
- `subprocess` calls containing `rm`
- Writing to files outside the project directory

If any pattern is found, a security warning is raised.

### Virtual Environment Isolation

Every generated project runs inside its own Python virtual environment. This isolates its dependencies from the system Python and from other projects.

### Process Timeouts

All executed processes have hard timeouts. A syntax check times out after 600 seconds. A project run times out after 1000 seconds. This prevents infinite loops from hanging the system.

---

## 14. Every Tool, Framework, and Library Used

### Python Backend

| Library | Version | Purpose |
|---------|---------|---------|
| **FastAPI** | 0.110+ | Web framework for REST API endpoints and WebSocket support |
| **Uvicorn** | 0.27+ | ASGI server that runs the FastAPI application |
| **Pydantic** | 2.5+ | Data validation and type-safe models for all internal state |
| **httpx** | 0.27+ | Async HTTP client for calling Ollama REST API and cloud LLM providers |
| **websockets** | 12.0+ | WebSocket protocol support for real-time streaming |
| **Rich** | 13.7+ | Terminal UI library for the command-line interface with formatted output |
| **Jinja2** | 3.1+ | Template engine for generating boilerplate code skeletons |
| **NetworkX** | 3.0+ | Graph analysis library for internal dependency calculations |
| **ChromaDB** | 0.4+ | Vector database for storing and searching file summaries by similarity |
| **Neo4j Python Driver** | 5.0+ | Driver for connecting to Neo4j graph database |
| **PyPDF2** | 3.0+ | PDF file parser for reading uploaded requirement documents |
| **python-multipart** | 0.0.6+ | Handles multipart form data (file uploads) in FastAPI |
| **Pytest** | 8.0+ | Testing framework used by the QA Agent to verify generated code |
| **google-generativeai** | 0.4+ | Google Gemini API client (optional, for cloud LLM) |

### React Frontend

| Library | Version | Purpose |
|---------|---------|---------|
| **React** | 19.x | UI component library for the web dashboard |
| **Vite** | 8.x | Development server and production build tool |
| **TailwindCSS** | 3.4 | Utility-first CSS framework for styling all UI components |
| **React Router DOM** | 7.x | Client-side routing between Dashboard and Workspace pages |
| **Lucide React** | 1.17+ | Icon library used for all UI icons |
| **react-force-graph-2d** | 1.29+ | 2D force-directed graph visualization for the knowledge graph |
| **react-force-graph-3d** | 1.29+ | 3D force-directed graph visualization (alternative view) |
| **Three.js** | 0.185+ | 3D rendering engine used by react-force-graph-3d |
| **xterm.js** | 6.0+ | Terminal emulator component for displaying process output |
| **PostCSS** | 8.5+ | CSS processing tool required by TailwindCSS |
| **Autoprefixer** | 10.5+ | Adds vendor prefixes to CSS for browser compatibility |
| **ESLint** | 10.x | JavaScript linting tool for frontend code quality |

### LLM Providers

| Provider | How It Connects | Notes |
|----------|----------------|-------|
| **Ollama** | HTTP API at `http://127.0.0.1:11434` | Default provider. Runs models locally. No API key needed. |
| **Groq** | Cloud REST API | Very fast inference. Requires `GROQ_API_KEY` in `.env` file. |
| **Google Gemini** | Cloud REST API via `google-generativeai` library | Requires `GEMINI_API_KEY` in `.env` file. |

### Code Quality Tools (Used Inside Generated Projects)

| Tool | Purpose |
|------|---------|
| **Ruff** | Fast Python linter. Catches syntax errors, unused imports, and code style violations. |
| **Pyright** | Python type checker. Catches mismatched function signatures, wrong argument types, and logic errors. |

### Infrastructure and Storage

| Component | Purpose |
|-----------|---------|
| **Neo4j** | Graph database that stores the project architecture as nodes (files) and edges (imports, dependencies). Used by the Context Engine to find related files. |
| **ChromaDB** | Vector database that stores natural language summaries of each file. Used for semantic similarity search when graph context is not enough. |
| **Python venv** | Standard library virtual environment. Every generated project gets its own isolated environment. |
| **Python AST** | Standard library module for parsing Python source code into abstract syntax trees. Used to extract function signatures and class definitions. |

---

## 15. Recommended LLM Models

The quality of generated code depends heavily on the LLM model used. Here are the recommended options:

### For the Best Results

**Model**: `qwen3.6:27b`

This model has built-in reasoning capabilities. Before generating code, it thinks through the problem internally, which leads to more accurate implementations, fewer integration errors, and better architectural decisions. It requires approximately 16 GB of RAM.

```bash
ollama pull qwen3.6:27b
```

### For Local Systems with Limited Resources

**Model**: `llama3.1:8b` or `qwen3.5:9b`

These smaller models run on systems with 8 GB of RAM. They handle simple to medium projects well. For complex multi-file projects, they may need more fix attempts, but the self-healing loop will keep trying until the code is clean.

```bash
ollama pull llama3.1:8b
ollama pull qwen3.5:9b
```

### For Cloud-Based Usage

If you have API keys for Groq or Google Gemini, you can use cloud-hosted models for the fastest inference without needing local GPU resources. Configure this in `config.py` and `.env`.

---

## 16. Directory and File Reference

### Root Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point. Starts the FastAPI backend server. |
| `cli.py` | Command-line interface. An alternative to the web dashboard for terminal users. |
| `config.py` | All configuration settings: model names, API keys, token limits, ports, security rules, and paths. Uses `pathlib.Path` for cross-platform compatibility. |
| `requirements.txt` | Python package dependencies. Install with `pip install -r requirements.txt`. |
| `.env.example` | Template for environment variables. Copy to `.env` and fill in API keys if using cloud providers. |
| `.contextrules` | Rules that the LLM must follow during code generation. Defines coding standards, plan format, and debugging behavior. |
| `knowledge.json` | Reference configuration for Ollama integration that gets injected into generated projects. |
| `test_qa_agent.py` | Test script that creates a sample calculator app and runs the QA Agent against it. |
| `start.bat` | Windows startup script. Launches both backend and frontend servers. |
| `start.sh` | Linux/macOS startup script. Launches both servers in background with signal handling. |
| `setup.sh` | One-time setup script. Creates venv, installs dependencies, and sets up the frontend. |

### `backend/` — API and Orchestration Layer

| File | Purpose |
|------|---------|
| `server.py` | FastAPI application. Defines all REST endpoints and the WebSocket handler. Starts Uvicorn. |
| `orchestrator.py` | The central state machine. Manages project lifecycle, triggers all agents, handles the fix loop, and dispatches UI updates through WebSocket. |
| `ws_manager.py` | Manages active WebSocket connections. Provides methods for sending typed messages (status, tokens, errors, file updates) to all connected clients. |
| `chat_agent.py` | Handles document QA tasks. Uses map-reduce chunking to process large documents and answer user questions. |

### `core/` — Agent Logic and Execution Engine

| File | Purpose |
|------|---------|
| `llm_client.py` | Wrapper for all LLM communication. Handles Ollama HTTP API, Groq, and Gemini. Manages streaming, token estimation, context window truncation, and JSON schema enforcement. |
| `coder.py` | Parses LLM XML tool output (`<write_file>`, `<edit_file>`, `<run_command>`) and applies changes to the workspace. |
| `fixer.py` | Self-healing agent. Receives error tracebacks and generates search/replace patches. Tracks previous fix attempts to avoid loops. |
| `runner.py` | Sandbox engine. Creates Python virtual environments, installs packages, runs Python files and shell commands with output capture and timeout handling. |
| `context.py` | AST context assembler. Parses Python files to extract function signatures, class definitions, and imports. Builds the File Registry string. |
| `analyzer.py` | Static analysis runner. Invokes Ruff and Pyright inside the project virtual environment and aggregates their output. |
| `planner.py` | Legacy V1 flat planner. Generates a simple linear sequence of steps. Kept for backward compatibility. |
| `checkpoint.py` | State snapshot manager. Saves progress after each step so execution can resume after crashes or restarts. |
| `qa_agent.py` | Quality assurance agent. Launches the built application, sends LLM-generated test inputs, and reports crashes or unexpected behavior. |

### `core/agents/` — Specialized Sub-Agents

| File | Purpose |
|------|---------|
| `architect_agent.py` | Generates skeleton files with class names and function signatures (stubs). Ensures imports work before real code is written. |
| `integration_agent.py` | Verifies that newly written files are properly wired into the project. Checks imports and function call signatures against the File Registry. |
| `summarizer.py` | Reads completed files and writes concise functional summaries for storage in ChromaDB. |
| `understanding_agent.py` | Analyzes existing codebases during ingestion. Identifies entry points, maps module structure, and documents architectural patterns. |
| `test_generator.py` | Reads skeleton files and generates unit tests based on the function signatures and project requirements. |
| `design_reviewer.py` | Reviews generated architecture plans against the rules in `.contextrules`. Suggests improvements. |

### `core/brain/` — Project Knowledge Storage

| File | Purpose |
|------|---------|
| `project_brain.py` | Main coordinator for the knowledge layer. Routes data to the graph database and vector store. |
| `knowledge_graph.py` | Neo4j interface. Creates nodes for files and edges for import relationships. Provides graph traversal queries. |
| `semantic_store.py` | ChromaDB interface. Stores file summaries as vector embeddings and provides similarity search. |

### `core/retrieval/` — Context Retrieval

| File | Purpose |
|------|---------|
| `context_engine.py` | Fuses graph queries (Neo4j) with vector searches (ChromaDB) to build the most relevant context for each code generation step. |

### `core/ingestion/` — Input Processing

| File | Purpose |
|------|---------|
| `ingester.py` | Repository scanner. Walks through an existing codebase, filters out non-code files, and triggers understanding and summarization. |
| `doc_ingester.py` | Document processor. Reads PDFs and text files, chunks them, and stores them in ChromaDB. |
| `chunker.py` | Text splitter. Implements recursive character chunking with configurable size and overlap. |

### `core/planners/` — Planning Engine

| File | Purpose |
|------|---------|
| `master_planner.py` | The V2 hierarchical planner. Uses multi-stage LLM calls to generate architectures with subsystems, services, and modules. Handles both monolithic and JIT epic planning. |

### `core/templates/` — Code Templates

| File | Purpose |
|------|---------|
| `template_engine.py` | Jinja2-based template renderer for generating boilerplate code files. |
| `files/*.j2` | Template files for common patterns: API endpoints, models, services. |

### `core/verification/` — Code Quality

| File | Purpose |
|------|---------|
| `static_analysis.py` | Runs Ruff and Pyright on individual files and returns structured results. |
| `architecture_validator.py` | Validates that generated architecture conforms to project rules and constraints. |

### `models/` — Data Models

| File | Purpose |
|------|---------|
| `state.py` | Defines `ProjectState` (complete project snapshot), `PlanStep` (individual plan items), `FileEntry` (AST registry entries), and `StepStatus` enum. |
| `hierarchy.py` | Defines the V2 architecture models: `ArchitectureSpec`, `SubsystemSpec`, `ServiceSpec`, `ModuleSpec`, and `EpicSpec`. |

### `ui/` — Terminal Interface

| File | Purpose |
|------|---------|
| `terminal_ui.py` | Rich-based terminal interface for the CLI mode. Provides formatted output, progress bars, and input prompts. |

### `frontend/` — React Web Dashboard

| Directory | Contents |
|-----------|----------|
| `src/pages/Dashboard.jsx` | Project list and creation page |
| `src/pages/Workspace.jsx` | Main workspace with chat input, plan viewer, code viewer, and graph |
| `src/components/` | Reusable UI components: CodeViewer, PlanPanel, OutputPanel, ThinkingPanel, ArchitectureGraph, modals |
| `src/services/api.js` | REST API client with methods for all backend endpoints |
| `src/hooks/useWebSocket.js` | React hook that manages the WebSocket connection and dispatches incoming messages |

---

## 17. How to Run the System

### Requirements

- Python 3.10 or higher
- Node.js 18 or higher
- Ollama installed and running

### Setup

```bash
# Clone and enter the project
git clone https://github.com/abhinav-vasudevan/Context-agent.git
cd Context-agent
git checkout v2

# Pull the recommended model
ollama pull qwen3.6:27b
```

#### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cd frontend && npm install && cd ..
```

#### Windows

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
cd frontend
npm install
cd ..
```

### Running

#### Linux / macOS

```bash
./start.sh
```

#### Windows

```powershell
.\start.bat
```

Open **http://localhost:5173** in your browser.

The backend runs at **http://127.0.0.1:8088**.
