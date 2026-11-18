"""
Context Agent — Configuration

All tunable parameters for the system.
Cross-platform compatible (Windows + Linux).
"""

import os
import platform
from pathlib import Path

# ── Groq Settings ──────────────────────────────────────────────────────
USE_GROQ = False
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = "llama-3.3-70b-versatile"
GROQ_MODELS = [
    {"id": "groq/compound", "name": "groq/compound"},
    {"id": "groq/compound-mini", "name": "groq/compound-mini"},
    {"id": "llama-3.1-8b-instant", "name": "llama-3.1-8b-instant"},
    {"id": "llama-3.3-70b-versatile", "name": "llama-3.3-70b-versatile"},
    {"id": "meta-llama/llama-4-scout-17b-16e-instruct", "name": "meta-llama/llama-4-scout-17b-16e-instruct"},
    {"id": "meta-llama/llama-prompt-guard-2-22m", "name": "meta-llama/llama-prompt-guard-2-22m"},
    {"id": "meta-llama/llama-prompt-guard-2-86m", "name": "meta-llama/llama-prompt-guard-2-86m"},
    {"id": "openai/gpt-oss-120b", "name": "openai/gpt-oss-120b"},
    {"id": "openai/gpt-oss-20b", "name": "openai/gpt-oss-20b"},
    {"id": "openai/gpt-oss-safeguard-20b", "name": "openai/gpt-oss-safeguard-20b"},
    {"id": "qwen/qwen3-32b", "name": "qwen/qwen3-32b"},
    {"id": "qwen/qwen3.6-27b", "name": "qwen/qwen3.6-27b"}
]

# ── Ollama / LLM Settings ──────────────────────────────────────────────
USE_GEMINI = False             # Set to True to use Google Gemini instead of Ollama
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "llama3.1:8b"
OLLAMA_NUM_CTX = 16384          # Context window (lowered to 16k for faster inference)
OLLAMA_TEMPERATURE = 0.3        # Lower = more deterministic, less hallucination
OLLAMA_REQUEST_TIMEOUT = 1000    # seconds — some calls are slow on smaller models
OLLAMA_MAX_RETRIES = 10          # Retry attempts on transient failures
OLLAMA_RETRY_BACKOFF = 2.0      # Exponential backoff base (seconds)

# ── Token Budget ───────────────────────────────────────────────────────
# We reserve tokens for different context sections.
# The File Registry and current step get priority.
TOKEN_BUDGET_SYSTEM_PROMPT = 5000
TOKEN_BUDGET_FILE_REGISTRY = 20000
TOKEN_BUDGET_STEP_DESC = 5000
TOKEN_BUDGET_SUMMARIES = 10000
MIN_GENERATION_BUDGET = 10000     # Ensures the LLM always has space to write its response

# ── Agent Engine (core/agent/) ────────────────────────────────────────
# "loop"     — OpenCode/Claude-Code style: one model, one conversation, actions
#              (write/edit/read/search/run), automatic checks, fixes in place.
#              Nothing is split while the project fits in the context window.
# "pipeline" — the older v2 pipeline (planner → stubs → one call per file → fixer).
AGENT_ENGINE = "loop"
AGENT_PLAN_FIRST = True          # make a short read-only plan for review before building
AGENT_CONTEXT_TOKENS = 0         # 0 = use the model's window (OLLAMA_NUM_CTX); set higher for cloud models
AGENT_OUTPUT_RESERVE = 6000      # tokens kept free for the model's reply (a whole small project)
AGENT_FIT_FRACTION = 0.6         # project fits ("full" mode) if it uses <= this share of the input budget
AGENT_MAX_STEPS = 12             # max model turns per task
AGENT_MAX_REPAIR_ROUNDS = 3      # max rounds of "checks found problems -> fix"
AGENT_SMOKE_RUN = True           # run the entry point briefly as part of the checks
AGENT_USE_PYRIGHT = True         # cross-file type checks (unknown attributes, wrong calls)
AGENT_ALLOW_RUN = True           # let the model run shell commands (sandboxed by SecurityChecker)
AGENT_THINK = False              # request "thinking" tokens (slow on CPU; for reasoning models only)
AGENT_RUN_QA = False             # also run the slow interactive QA agent after building

# ── Agent Settings ────────────────────────────────────────────────────
MAX_FIX_ATTEMPTS = 999999            # Max retries when fixing errors (effectively infinite)
MAX_SEMANTIC_FIX_ATTEMPTS = 30   # Max retries for the post-build semantic analysis loop (Ruff/Pyright/Semgrep)
MAX_STATIC_FIX_ATTEMPTS = 4      # Max verified fix rounds per lint/type/syntax/test failure during a step
FIXER_MAX_ITERATIONS = 6         # Max LLM turns inside one Fixer.fix_error agent loop (prompt grows each turn)
FIXER_PROMPT_BUDGET_CHARS = 20000 # Fixer transcript is compacted past this size (~5k tokens) to stay well inside the window
FIXER_MAX_SEARCH_FAILURES = 3    # SEARCH/REPLACE misses on a file before demanding a full-file rewrite
SPEC_EXCERPT_CHARS = 6000        # Max chars of the original user spec shown to the coder/architect per call
MAX_PLAN_RETRIES = 5             # Max retries for plan generation
SYNTAX_CHECK_TIMEOUT = 600       # Seconds for syntax check subprocess
PROCESS_RUN_TIMEOUT = 1000       # Seconds for running user projects (5 min)

# ── QA Agent Settings ─────────────────────────────────────────────────
MAX_QA_ATTEMPTS = 10             # Max autonomous test-fix cycles
MAX_QA_INTERACTIONS = 20         # Max input prompts the QA Agent will answer per run
QA_PROCESS_TIMEOUT = 1000        # Seconds before killing a QA test run

# ── Backend Server Settings ───────────────────────────────────────────
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8088
CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "*"
]

# ── Security ──────────────────────────────────────────────────────────
# Commands that are ALWAYS blocked — never executed under any circumstances
BLOCKED_COMMANDS = [
    "rm", "rm -rf", "rmdir", "del", "rd",
    "remove", "unlink", "shutil.rmtree",
    "os.remove", "os.unlink", "os.rmdir",
    "format", "mkfs",
    "sudo", "chmod", "chown",
    "shutdown", "reboot",
    "> /dev/null",  # output redirection that destroys data
]

# Patterns in generated code that trigger a security warning
DANGEROUS_CODE_PATTERNS = [
    r"\bos\.remove\b",
    r"\bos\.unlink\b",
    r"\bos\.rmdir\b",
    r"\bshutil\.rmtree\b",
    r"\bsubprocess.*rm\b",
    r"\bopen\s*\(.*,\s*['\"]w['\"]\s*\).*(?:\/|\\\\)(?!src)",  # writing outside project
]

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.resolve()
PROJECTS_DIR = PROJECT_ROOT / "projects"
CUSTOM_RULES_FILE = PROJECT_ROOT / ".contextrules"
PROJECTS_DIR.mkdir(exist_ok=True)

# ── Neo4j (Knowledge Graph) ───────────────────────────────────────────
NEO4J_URI = os.environ.get("NEO4J_URI", "neo4j://127.0.0.1:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

# ── Project Brain ─────────────────────────────────────────────────────
BRAIN_DIR_NAME = ".agent_brain"     # Created inside each project workspace

# ── Platform Detection ────────────────────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"
PYTHON_CMD = "python" if IS_WINDOWS else "python3"
PIP_CMD = "pip" if IS_WINDOWS else "pip3"
VENV_ACTIVATE = (
    "Scripts\\activate" if IS_WINDOWS else "bin/activate"
)

# ── UI Settings ───────────────────────────────────────────────────────
# Black and white theme — no colors except grayscale
UI_THEME = {
    "primary": "white",
    "secondary": "bright_black",
    "success": "white",
    "error": "white",
    "warning": "white",
    "border": "bright_black",
    "highlight": "bold white",
    "dim": "dim white",
}
