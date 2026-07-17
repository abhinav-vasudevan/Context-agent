# Context Agent

An autonomous AI coding system that architects, generates, verifies, and self-heals software projects. You describe what you want to build in plain English, and the agent handles the rest from planning the architecture, writing every file, running static analysis, and fixing bugs automatically.

The system works entirely on your local machine using open-source LLMs through Ollama. No cloud API keys are needed to get started.

---

## What It Does

- Takes a natural language prompt and turns it into a fully working codebase
- Breaks large projects into small, dependency-ordered steps so nothing gets missed
- Writes each file one at a time, with full awareness of what was already written
- Runs static analysis (Ruff, Pyright) after each file to catch errors early
- Fixes errors automatically using an LLM-powered self-healing loop
- Supports ingesting existing codebases and adding new features into them
- Handles large requirement documents (PDF, TXT, MD) through chunked summarization
- Provides a real-time web dashboard with live code streaming, plan tracking, and a knowledge graph

---

## What You Need Before Starting

| Tool | Version | Purpose |
|------|---------|---------|
| **Python** | 3.10 or higher | Runs the backend server and all agent logic |
| **Node.js** | 18 or higher | Runs the React frontend dev server |
| **npm** | Comes with Node.js | Installs frontend packages |
| **Ollama** | Latest | Serves local LLM models on your machine |
| **Git** | Any recent version | Clone the repository |

### Optional (for advanced features)

| Tool | Purpose |
|------|---------|
| **Neo4j Desktop** | Knowledge graph storage for architecture visualization |
| **Ruff** | Fast Python linter (auto-installed in project venv) |
| **Pyright** | Python type checker (auto-installed in project venv) |

---

## Which LLM Model to Use

The system works with Ollama (local models) or Groq/Gemini (cloud APIs). Here are the recommended models:

### For Best Results (needs 16 GB+ RAM)

```
ollama pull qwen3.6:27b
```

**qwen3.6:27b** has built-in reasoning capabilities. It produces the most accurate code and can handle complex multi-file projects without hallucinating imports or breaking integration between files.

### For Local Systems with Limited RAM (8 GB)

```
ollama pull llama3.1:8b
```

or

```
ollama pull qwen3.5:9b
```

These smaller models work well for simple to medium projects. They may need more fix attempts on complex architectures but will still produce working code.

### Using Cloud APIs (No Local GPU Needed)

If you prefer cloud-hosted models, set your API key in the `.env` file:

- **Groq**: Set `GROQ_API_KEY` and change `USE_GROQ = True` in `config.py`
- **Google Gemini**: Set `GEMINI_API_KEY` and change `USE_GEMINI = True` in `config.py`

---

## Setup Instructions

### Step 1: Clone the Repository

```bash
git clone https://github.com/abhinav-vasudevan/Context-agent.git
cd Context-agent
git checkout v2
```

### Step 2: Install Ollama and Pull a Model

Go to [https://ollama.com](https://ollama.com) and install Ollama for your operating system.

Then pull the model you want to use:

```bash
ollama pull qwen3.6:27b
```

Make sure Ollama is running before you start the agent:

```bash
ollama serve
```

> On most systems, Ollama starts automatically after installation. You can check by opening `http://127.0.0.1:11434` in your browser — if you see a response, it is running.

### Step 3: Install and Configure Neo4j Desktop (Optional but Recommended)

The system uses Neo4j to store the project's architecture graph. Without it, the graph features will be disabled but the system will still function.

1. Download and install [Neo4j Desktop](https://neo4j.com/download/).
2. Open Neo4j Desktop and create a new Project.
3. Add a Local DBMS (Database Management System) to the project.
4. Set the password for this DBMS (default expected password is `password`, but you can change it).
5. Start the DBMS. It will run on the default bolt port `7687`.
6. Make sure the database is running before you start Context Agent.

> If you set a password other than `password`, you must update the `.env` file (see Step 6) with `NEO4J_PASSWORD=your_password`.

### Step 4: Set Up the Python Backend

#### On Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

#### On Windows

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Set Up the React Frontend

```bash
cd frontend
npm install
cd ..
```

### Step 6: Configure Environment Variables (Optional)

Copy the example file and edit it if you want to use cloud APIs:

```bash
cp .env.example .env
```

Edit `.env` and add your API keys if needed. For local Ollama usage, no changes are needed.

---

## How to Run

### Quick Start (Both Servers at Once)

#### On Linux / macOS

```bash
chmod +x start.sh
./start.sh
```

#### On Windows

Double-click `start.bat` or run in a terminal:

```powershell
.\start.bat
```

### Manual Start (Two Separate Terminals)

**Terminal 1 — Backend:**

```bash
# Linux / macOS
source venv/bin/activate
python main.py

# Windows
.\venv\Scripts\activate
python main.py
```

**Terminal 2 — Frontend:**

```bash
cd frontend
npm run dev
```

### Open the Dashboard

Once both servers are running, open your browser and go to:

**[http://localhost:5173](http://localhost:5173)**

The backend API runs at `http://127.0.0.1:8088`.

---

## How to Use

The web dashboard has three modes:

### Build Mode — Create a New Project from Scratch

1. Click **Build** on the dashboard
2. Give your project a name
3. Type a description of what you want to build (for example: "Build a task manager with user authentication and a REST API")
4. The agent generates a step-by-step architecture plan
5. Review the plan and click **Approve**
6. The agent writes all the files, installs dependencies, and runs tests automatically

### Ingest Mode — Modify an Existing Codebase

1. Click **Ingest** on the dashboard
2. Enter the full path to your existing project on your machine
3. Describe what you want to add or change
4. The agent scans your codebase, understands the architecture, and generates a plan that edits your existing files without breaking them

### Docs Mode — Upload Requirement Documents

1. Upload PDF, TXT, or MD files with project requirements
2. The agent reads and summarizes the documents
3. It uses the extracted specifications to guide planning and code generation

---

## Project Structure

```
Context-agent/
├── main.py                 # Entry point — starts the FastAPI backend
├── cli.py                  # Command-line interface (alternative to web UI)
├── config.py               # All settings: model names, ports, token limits, paths
├── requirements.txt        # Python dependencies
├── .env.example            # Template for API keys
├── .contextrules           # Rules the LLM follows during code generation
├── knowledge.json          # Ollama integration reference for generated projects
├── start.bat               # Windows startup script
├── start.sh                # Linux/macOS startup script
├── setup.sh                # One-time environment setup script
│
├── backend/                # FastAPI server and orchestration
│   ├── server.py           # REST API endpoints and WebSocket handler
│   ├── orchestrator.py     # Main workflow engine — drives the full lifecycle
│   ├── ws_manager.py       # WebSocket connection manager for live streaming
│   └── chat_agent.py       # Document QA with map-reduce chunking
│
├── core/                   # Agent logic and execution engine
│   ├── llm_client.py       # LLM wrapper (Ollama, Groq, Gemini) with streaming
│   ├── coder.py            # Parses LLM output (write_file, edit_file, run_command)
│   ├── fixer.py            # Self-healing agent — reads errors and patches code
│   ├── runner.py           # Sandbox — manages venv and runs code safely
│   ├── context.py          # AST parser — extracts function signatures for context
│   ├── analyzer.py         # Static analysis runner (Ruff, Pyright)
│   ├── planner.py          # Legacy flat planner (V1)
│   ├── checkpoint.py       # State snapshots for retry/rewind
│   └── qa_agent.py         # Quality assurance — tests the built application
│
│   ├── agents/             # Specialized sub-agents
│   │   ├── architect_agent.py      # Generates file skeletons with signatures
│   │   ├── integration_agent.py    # Wires files together, manages imports
│   │   ├── summarizer.py           # Summarizes files for the knowledge store
│   │   ├── understanding_agent.py  # Maps existing codebases during ingestion
│   │   ├── test_generator.py       # Generates unit tests from stubs
│   │   └── design_reviewer.py      # Reviews plans against design rules
│   │
│   ├── brain/              # Project knowledge storage
│   │   ├── project_brain.py    # Main brain — coordinates graph + vector stores
│   │   ├── knowledge_graph.py  # Neo4j interface for architecture graphs
│   │   └── semantic_store.py   # ChromaDB interface for semantic search
│   │
│   ├── retrieval/          # Context retrieval for code generation
│   │   └── context_engine.py   # Fuses graph + vector search for smart context
│   │
│   ├── ingestion/          # Input processing
│   │   ├── ingester.py     # Scans existing codebases
│   │   ├── doc_ingester.py # Processes uploaded documents
│   │   └── chunker.py      # Splits large text into manageable chunks
│   │
│   ├── planners/           # Planning engine
│   │   └── master_planner.py   # Hierarchical planner (Epics → Subsystems → Modules)
│   │
│   ├── templates/          # Code generation templates
│   │   ├── template_engine.py  # Jinja2 template renderer
│   │   └── files/              # Template files (.j2)
│   │
│   └── verification/       # Code quality checks
│       ├── static_analysis.py      # Ruff and Pyright runner
│       └── architecture_validator.py # Validates generated architecture
│
├── models/                 # Data models
│   ├── state.py            # ProjectState, PlanStep, FileEntry
│   └── hierarchy.py        # ArchitectureSpec, SubsystemSpec, ModuleSpec
│
├── ui/                     # Terminal UI (for CLI mode)
│   └── terminal_ui.py      # Rich-based terminal interface
│
├── frontend/               # React + Vite web dashboard
│   ├── src/
│   │   ├── App.jsx
│   │   ├── pages/
│   │   │   ├── Dashboard.jsx    # Project list and creation
│   │   │   └── Workspace.jsx    # Main workspace with chat, plan, and graph
│   │   ├── components/          # UI components (code viewer, plan panel, etc.)
│   │   ├── services/api.js      # Backend API client
│   │   └── hooks/useWebSocket.js # WebSocket hook for live updates
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
│
├── projects/               # Generated project workspaces (created at runtime)
│   └── .gitkeep
│
└── test_qa_agent.py        # Test script for the QA agent
```

---

## Tools and Frameworks Used

### Backend

| Tool | What It Does |
|------|-------------|
| **FastAPI** | Python web framework for the REST API and WebSocket endpoints |
| **Uvicorn** | ASGI server that runs FastAPI with async support |
| **Pydantic** | Data validation and settings management for all internal models |
| **httpx** | Async HTTP client for calling Ollama and cloud LLM APIs |
| **websockets** | WebSocket protocol support for real-time frontend communication |
| **Jinja2** | Template engine for generating boilerplate code files |
| **NetworkX** | Graph library used internally for dependency analysis |
| **ChromaDB** | Vector database for storing and searching file summaries |
| **Neo4j** | Graph database for storing architecture knowledge graphs |
| **PyPDF2** | PDF parser for reading uploaded requirement documents |
| **python-multipart** | File upload handling for FastAPI |
| **Rich** | Terminal formatting library for the CLI interface |
| **Pytest** | Test runner used by the QA agent to verify generated code |

### Frontend

| Tool | What It Does |
|------|-------------|
| **React 19** | UI library for building the web dashboard |
| **Vite** | Fast development server and build tool |
| **TailwindCSS** | Utility-first CSS framework for styling |
| **React Router** | Client-side routing between Dashboard and Workspace |
| **Lucide React** | Icon library for the UI |
| **react-force-graph-2d/3d** | Graph visualization for the architecture knowledge graph |
| **Three.js** | 3D rendering engine used by the graph visualizer |
| **xterm.js** | Terminal emulator component for showing process output |

### LLM Providers

| Provider | How It Works |
|----------|-------------|
| **Ollama** | Runs open-source models locally. Default and recommended |
| **Groq** | Cloud API with fast inference. Needs API key |
| **Google Gemini** | Cloud API from Google. Needs API key |

### Code Quality Tools (Used Inside Generated Projects)

| Tool | What It Does |
|------|-------------|
| **Ruff** | Lightning-fast Python linter that catches syntax and style issues |
| **Pyright** | Deep Python type checker for catching logic and signature errors |

---

## Configuration

All settings are in `config.py`. The most important ones:

| Setting | Default | Description |
|---------|---------|-------------|
| `OLLAMA_MODEL` | `qwen3.6:27b` | Which Ollama model to use |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where Ollama is running |
| `BACKEND_PORT` | `8088` | Port for the FastAPI backend |
| `USE_GROQ` | `False` | Set to `True` to use Groq cloud API |
| `USE_GEMINI` | `False` | Set to `True` to use Google Gemini |
| `MAX_FIX_ATTEMPTS` | `999999` | How many times the fixer will retry |
| `OLLAMA_NUM_CTX` | `16384` | Context window size (tokens) |

---

## Troubleshooting

### "Cannot connect to Ollama"

Make sure Ollama is running:

```bash
ollama serve
```

Check that it responds at `http://127.0.0.1:11434`.

### "Model not found"

Pull the model first:

```bash
ollama pull qwen3.6:27b
```

### Frontend shows a blank page

Make sure you ran `npm install` inside the `frontend/` directory and that `npm run dev` is running.

### Port 8088 is already in use

Another instance of the backend might be running. Kill it and restart:

```bash
# Linux / macOS
lsof -i :8088 | grep LISTEN
kill <PID>

# Windows
netstat -ano | findstr :8088
taskkill /PID <PID> /F
```

---

## License

This project is for research and educational purposes.
