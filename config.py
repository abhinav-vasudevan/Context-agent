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
OLLAMA_MODEL = "qwen2.5-coder:14b"
OLLAMA_NUM_CTX = 32768          # Context window size (tokens)
OLLAMA_TEMPERATURE = 0.3        # Lower = more deterministic, less hallucination
OLLAMA_REQUEST_TIMEOUT = 600    # seconds — some calls are slow on smaller models
OLLAMA_MAX_RETRIES = 3          # Retry attempts on transient failures
OLLAMA_RETRY_BACKOFF = 2.0      # Exponential backoff base (seconds)

# ── Token Budget ───────────────────────────────────────────────────────
# We reserve tokens for different context sections.
# The File Registry and current step get priority.
TOKEN_BUDGET_SYSTEM_PROMPT = 600
TOKEN_BUDGET_FILE_REGISTRY = 3000    # Enough for ~20 files with signatures
TOKEN_BUDGET_STEP_DESC = 2000
TOKEN_BUDGET_SUMMARIES = 2000
MIN_GENERATION_BUDGET = 4000         # Minimum tokens reserved for LLM output

# ── Agent Settings ────────────────────────────────────────────────────
MAX_FIX_ATTEMPTS = 5             # Max retries when fixing errors (keep low to avoid rate limit exhaustion)
MAX_PLAN_RETRIES = 2             # Max retries for plan generation
SYNTAX_CHECK_TIMEOUT = 10       # Seconds for syntax check subprocess
PROCESS_RUN_TIMEOUT = 300        # Seconds for running user projects (5 min)

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

# ── Paths ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
PROJECTS_DIR = PROJECT_ROOT / "projects"
PROJECTS_DIR.mkdir(exist_ok=True)

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
