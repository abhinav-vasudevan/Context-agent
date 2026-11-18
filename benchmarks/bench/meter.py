"""
LLM call meter — records every LLM call the agent makes, without modifying it.

`core/llm_client.py` already logs two lines per Ollama call:
    "LLM request (Ollama): model=%s, prompt_len=%d, system_len=%d"
    "LLM response: %d prompt + %d completion tokens, %.1fs"
This module attaches a logging.Handler to that logger, pairs the two lines,
and works out which agent component made the call by walking the call stack
(the async-generator frames are chained to their consumer, so the caller is on
the stack when the log line is emitted).

Token fields:
  prompt_tokens      Ollama's prompt_eval_count (tokens actually evaluated;
                     can be lower than the prompt size when Ollama reuses its
                     prompt cache).
  input_chars        len(prompt) + len(system) exactly as sent.
  est_input_tokens   input_chars / CHARS_PER_TOKEN — the prompt size used for
                     the context-window analysis (cache-independent).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

# Llama-3 tokenizer averages ~3.6 chars/token on mixed English + Python.
# The report recalibrates this from the run's own (cache-free) calls.
CHARS_PER_TOKEN = 3.6

_REQ = re.compile(r"LLM request \((\w+)\): model=(\S+), prompt_len=(\d+), system_len=(\d+)")
_RESP = re.compile(r"LLM response: (\d+) prompt \+ (\d+) completion tokens, ([\d.]+)s")

# file-name fragment -> component label (first match walking the stack outward)
_COMPONENTS = [
    ("master_planner", "planner"),
    ("architect_agent", "scaffolding"),
    ("integration_agent", "integration_check"),
    ("summarizer", "summarizer"),
    ("understanding_agent", "understanding"),
    ("qa_agent", "qa"),
    ("fixer", "fixer"),
    ("coder", "coder"),
    ("chat_agent", "chat"),
    ("agent/loop", "agent"),
    ("orchestrator", "orchestrator"),
    ("baseline_runner", "baseline"),
]


def _component() -> str:
    for frame in reversed(traceback.extract_stack()):
        fn = frame.filename.replace("\\", "/")
        if "/llm_client.py" in fn or "/logging/" in fn or "/bench/meter.py" in fn:
            continue
        for frag, label in _COMPONENTS:
            if frag in fn:
                return label
    return "other"


class LLMMeter(logging.Handler):
    """Collects one JSON record per LLM call and appends it to a JSONL file."""

    def __init__(self, out_path: Path):
        super().__init__(level=logging.INFO)
        self.out_path = Path(out_path)
        self.out_path.parent.mkdir(parents=True, exist_ok=True)
        self.context: dict = {}
        self._pending: list[dict] = []
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def set_context(self, **ctx):
        self.context = ctx

    def emit(self, record: logging.LogRecord):
        try:
            msg = record.getMessage()
        except Exception:
            return
        m = _REQ.search(msg)
        if m:
            with self._lock:
                self._pending.append({
                    "provider": m.group(1),
                    "model": m.group(2),
                    "prompt_chars": int(m.group(3)),
                    "system_chars": int(m.group(4)),
                    "component": _component(),
                    "t_start": time.time(),
                })
            return
        m = _RESP.search(msg)
        if m:
            # Pair with the MOST RECENT request. A request that failed and was
            # retried (e.g. the client's first try with think=True on a model
            # that doesn't support it) logs a request line with no response;
            # FIFO pairing would shift every later record by one.
            with self._lock:
                req = self._pending[-1] if self._pending else {}
                self._pending.clear()
            input_chars = req.get("prompt_chars", 0) + req.get("system_chars", 0)
            rec = {
                **self.context,
                **req,
                "component": req.get("component") or _component(),
                "input_chars": input_chars,
                "est_input_tokens": round(input_chars / CHARS_PER_TOKEN),
                "prompt_tokens": int(m.group(1)),
                "completion_tokens": int(m.group(2)),
                "seconds": float(m.group(3)),
            }
            self.records.append(rec)
            with self._lock, open(self.out_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")


_installed: Optional[LLMMeter] = None


def install(out_path: Path) -> LLMMeter:
    """Attach the meter to core.llm_client's logger (idempotent per path)."""
    global _installed
    logger = logging.getLogger("core.llm_client")
    if _installed is not None:
        logger.removeHandler(_installed)
    _installed = LLMMeter(out_path)
    logger.addHandler(_installed)
    logger.setLevel(logging.INFO)
    return _installed
