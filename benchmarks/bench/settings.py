"""
Benchmark settings.

Everything that differs from the agent's normal configuration is listed here
and applied at runtime by the harness — the agent's own source files are never
modified. Every override is written into each run's results so it can be
reported alongside the numbers.
"""

from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BENCH_DIR.parent
TASKS_DIR = BENCH_DIR / "tasks"
RESULTS_DIR = BENCH_DIR / "results"

# ── Model ────────────────────────────────────────────────────────────────
# Base model the agent is configured with (config.OLLAMA_MODEL).
BASE_MODEL = "llama3.1:8b"
# Derived Ollama tag = BASE_MODEL + "PARAMETER num_thread 8". Same weights, it
# only pins the CPU thread count (measured fastest on the i5-1240P and leaves
# cores free so the laptop stays responsive). Baseline and agent both use it.
BENCH_MODEL = "llama3.1-bench:8b"
NUM_THREAD = 8

# ── Safety caps (runtime overrides of config.py) ─────────────────────────
# config.MAX_FIX_ATTEMPTS is 999999 (effectively infinite): an unfixable error
# would keep a CPU-only laptop at 100% for hours. Capped for the benchmark.
CONFIG_OVERRIDES = {
    "MAX_FIX_ATTEMPTS": 4,          # was 999999
    "MAX_QA_ATTEMPTS": 2,           # was 10
    "MAX_QA_INTERACTIONS": 8,       # was 20
    "QA_PROCESS_TIMEOUT": 120,      # was 1000 s
    "PROCESS_RUN_TIMEOUT": 120,     # was 1000 s
}

# Hard wall-clock limit for one agent project run (seconds). If hit, the run
# is recorded as a timeout and graded on whatever files exist.
AGENT_RUN_TIMEOUT = 3 * 60 * 60   # counted across resumed sessions

# Pause between task runs so the CPU can cool down (seconds).
COOLDOWN_SECONDS = 90

# ── Grading ──────────────────────────────────────────────────────────────
PER_TEST_TIMEOUT = 60       # seconds per hidden test (each runs in its own process)
