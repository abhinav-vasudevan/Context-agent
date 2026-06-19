# Context Agent: Advanced Agentic Coding System

Welcome to **Context Agent**! Instead of relying on complex, non-deterministic Multi-Agent DAGs (Directed Acyclic Graphs) that easily lose context or hallucinate "code stitching," this system relies on a **Deterministic Single-Loop Orchestrator** powered by strict AST (Abstract Syntax Tree) parsing.

This README is designed to explain the internal mechanics of the system from prompt to execution.

---

## 🏗️ 1. System Architecture Overview

The system is split into a robust **Python FastAPI Backend** and a clean **React Vite Frontend**, communicating in real-time via WebSockets and REST APIs.

When a user submits a prompt, it doesn't just go to a chatbot. It enters the **Orchestrator Pipeline**:

1. **Planning Phase**: The prompt is analyzed and a strictly structured implementation plan is generated.
2. **Execution Phase**: The system iterates through the plan file-by-file.
3. **Context Assembly**: Instead of dumping the entire codebase into the LLM (which destroys the context window), the system generates an "AST File Registry" containing only the exact function signatures and class definitions of previously written files.
4. **Verification & Auto-Fixing**: Code is executed in an isolated sandbox. Syntax and runtime errors are caught, fed back to the LLM, and fixed autonomously.

---

## 🧠 2. How the Prompt is Broken Down & Planned

When you ask the system to "Build a Scientific Calculator," here is exactly what happens under the hood:

### A. The Planner Agent
The user's prompt is routed to the **Planner**. The Planner does not write code. Its sole job is to break down the user's intent into a strictly formatted Markdown plan (`plan.txt`).

### B. The Dependency Graph
The LLM generates the plan by listing files in **dependency order** (e.g., `utils.py` is planned before `main.py` because `main` depends on `utils`). 

### C. Parsing the Plan
Our Python backend intercepts the LLM's raw text and uses a custom `parse_plan()` function to extract the exact file paths and their descriptions. It creates a stateful `ProjectState` tracking which files are `PENDING`, `IN_PROGRESS`, or `COMPLETED`.

---

## ⚙️ 3. Repeated LLM Calling (The Single Loop)

Once the plan is approved by the user, the **Builder Agent** takes over. It does not try to build the whole app in one prompt. It uses a **Repeated Iteration Loop**.

For every file in the plan:
1. **Context Construction**: The backend builds a highly optimized prompt. It injects:
   - The user's original goal.
   - The specific instructions for *this exact file*.
   - The **File Registry** (more on this below).
2. **LLM Invocation**: The LLM is called (via local `qwen:14b` or Gemini). The generation is streamed live to the UI via WebSockets.
3. **Extraction**: The raw Markdown output is parsed, and the raw Python/JS code is extracted and written directly to the secure Workspace sandbox.

---

## 📂 4. The "Secret Weapon": The Concrete AST File Registry

The biggest problem with AI coding is **Code Stitching**—the LLM forgets the exact name of a function it wrote 5 minutes ago and invents a new one, breaking the app.

We solved this using Python's `ast` (Abstract Syntax Tree) module. 
Instead of sending raw code back to the LLM (which eats up tokens), our system:
1. Parses every `.py` file the LLM writes.
2. Extracts exactly the `class` names, `def` signatures, and `import` statements.
3. Compiles them into a lightweight "Registry."

**Example of what the LLM sees:**
```python
# Available Files in Workspace:
# src/math_ops.py
def add(a: float, b: float) -> float: ...
def subtract(a: float, b: float) -> float: ...
```
This guarantees the LLM knows *exactly* how to call functions it previously wrote, ensuring perfect code stitching every time while saving massive amounts of token bandwidth.

---

## 🛠️ 5. Automated Fixing Loop (Self-Healing Code)

We do not trust the LLM to write perfect code on the first try. The Context Agent features an autonomous **Verification & Fixing Loop**.

1. **Immediate Syntax Check**: The moment a Python file is written, the system runs `python -m py_compile <file>`. 
2. **Error Capture**: If the LLM made an indentation error or syntax mistake, the command fails. The Orchestrator captures the `stderr` traceback.
3. **The Fix Prompt**: The backend automatically constructs a new prompt:
   *"You wrote this code: [Code]. It threw this error: [Traceback]. Fix it."*
4. **Retry Loop**: The LLM generates a new version. This loop repeats up to `MAX_FIX_ATTEMPTS` times without any user intervention.
5. **Runtime Fixing**: Beyond syntax, the system can spin up a background task to actually *run* the user's project. If the project crashes at runtime, the exact stack trace is captured and fed back into the fixing loop.

---

## 🔒 6. Security and Sandboxing

Because the agent executes code automatically, security is paramount.
- **Venv Isolation**: Every project gets its own isolated `venv` (Virtual Environment). Dependencies are installed here, keeping your host system perfectly clean.
- **Command Blocklist**: Destructive commands (`rm -rf`, `sudo`, `mkfs`) are hard-blocked by the Python orchestrator before they ever reach the shell.
- **Explicit Permission**: You are the supervisor. The agent cannot run the application without asking for your explicit `[y/n]` permission in the UI.

---

## 🚀 7. Running the System

To see the system in action:

1. Ensure Ollama is running (`ollama serve`) with the `qwen:14b` model pulled.
2. Run the startup script:
   ```bash
   ./start.sh
   ```
3. The FastAPI Backend will boot on `http://127.0.0.1:8088`.
4. The React Vite Frontend will boot on `http://localhost:5174`.
5. Open the UI, type your prompt, and watch the Orchestrator plan, generate, and self-heal your application in real-time!

---

## 🗂️ 8. Directory & File Structure Deep Dive

Here is exactly what every file and folder does in the Context Agent ecosystem:

### `backend/`
The FastAPI server bridging the UI with the core agent logic.
- **`server.py`**: The main entry point for the backend. Defines the REST API routes (like `/api/health` and `/api/projects`) and mounts the WebSocket endpoints.
- **`orchestrator.py`**: The "Central Nervous System". It manages the state machine, triggers the Planner and Coder, and orchestrates the execution and self-healing loops.
- **`ws_manager.py`**: Manages active WebSocket connections to stream live LLM tokens and execution status updates directly to the React frontend.

### `core/`
The brain of the operation, containing all the agentic LLM logic.
- **`coder.py`**: Responsible for parsing the raw LLM responses, extracting the markdown code blocks, and securely writing them to the file system.
- **`context.py`**: The AST Context Engine. It uses Python's Abstract Syntax Tree parser to read previously generated files and build a highly condensed, concrete "File Registry" of function signatures to feed into the prompt.
- **`fixer.py`**: The Self-Healing module. It analyzes stack traces and tracebacks from failed executions, auto-installs missing Python packages, and builds the specific fix prompts for the LLM.
- **`llm_client.py`**: A robust, async wrapper around LLM APIs (Ollama, Groq, Gemini). It handles token estimation, Server-Sent Events (SSE) streaming, and exponential backoff for network resilience.
- **`planner.py`**: Analyzes the user's initial prompt and uses the LLM to generate a strict, dependency-ordered implementation plan.
- **`runner.py`**: The secure sandbox engine. It executes syntax checks (`py_compile`), manages the virtual environments (`venv`), and handles the execution of the generated user programs in non-interactive modes.

### `models/`
- **`state.py`**: Contains the Pydantic data schemas for `ProjectState`, `PlanStep`, and `FileEntry`. This ensures type safety as state is passed between the Planner, Orchestrator, and Frontend.

### `frontend/`
The React (Vite) User Interface.
- Provides a stunning UI with a `Dashboard.jsx` to manage multiple project workspaces, and a `Workspace.jsx` screen that offers a live file explorer, syntax-highlighted code viewer, and real-time terminal logs.

### `ui/`
- **`terminal_ui.py`**: A rich command-line user interface (using the `rich` library) allowing developers to use the entire Context Agent from their terminal instead of the web UI.

### `projects/`
The isolated sandbox directory where all user applications are generated. Each project gets its own sub-folder with a completely isolated Python `venv` to prevent dependency conflicts on your host machine.

### Root Files
- **`cli.py`**: The Command Line Interface entry point (run via `python cli.py`).
- **`config.py`**: The centralized configuration hub. Stores all tunable parameters, token budgets, API keys (Groq, Gemini), and LLM configurations.
- **`main.py`**: A secondary/legacy entry point.
- **`knowledge.json`**: The agent's persistent memory. It stores specific integration guidelines and "gotchas" to help the LLM avoid common coding mistakes.
- **`start.sh` / `start.bat`**: Cross-platform bootstrapping scripts that concurrently spin up both the FastAPI backend and the React frontend.
