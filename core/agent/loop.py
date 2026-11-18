"""
AgentLoop — the Context Agent's main engine (OpenCode / Claude Code style).

One model, one conversation, a loop:

    look at the workspace → act (write / edit / read / search / run)
    → see the results → act again → ... → DONE → automatic checks
    → if the checks find problems, fix them in the same conversation

Context policy — "fit or retrieve" (core/agent/workspace.py):
  * If the project and task fit inside the context window, nothing is split:
    the model sees every file verbatim and usually writes the whole project
    in one reply.
  * Only when the codebase is too large does the agent switch to a repo map
    (exact AST signatures) + READ / SEARCH / BRAIN (Neo4j + ChromaDB) to pull
    in just the files it needs.
  * When the conversation itself grows past the window, it is "rebased":
    rebuilt from the task, the plan, a progress note and the CURRENT workspace
    (the files on disk are the ground truth, so nothing important is lost).

Reference: reference/opencode/packages/core/src/session/ (runner, compaction).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Tuple

import config
from core.agent import prompts
from core.agent.actions import ActionExecutor, ActionResult, parse_reply
from core.agent.diagnostics import run_diagnostics
from core.agent.workspace import estimate_tokens, python_outline, read_text, take_snapshot

log = logging.getLogger(__name__)

AsyncFn = Callable[..., Awaitable[None]]


@dataclass
class AgentCallbacks:
    on_token: Optional[Callable[[str], None]] = None
    on_thinking: Optional[Callable[[str], None]] = None
    on_status: Optional[AsyncFn] = None              # async (message)
    on_llm_done: Optional[AsyncFn] = None            # async (full reply text)
    on_file_changed: Optional[AsyncFn] = None        # async (rel_path)
    before_checks: Optional[Callable[[], Awaitable[None]]] = None   # e.g. install requirements
    wait_if_paused: Optional[Callable[[], Awaitable[None]]] = None
    should_stop: Optional[Callable[[], bool]] = None


@dataclass
class AgentResult:
    success: bool
    summary: str = ""
    mode: str = "full"
    files_changed: List[str] = field(default_factory=list)
    steps: int = 0
    llm_calls: int = 0
    repair_rounds: int = 0
    diagnostics_history: List[int] = field(default_factory=list)   # problems found per check
    final_problems: List[str] = field(default_factory=list)
    stopped_reason: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _cfg(name: str, default):
    return getattr(config, name, default)


class AgentLoop:
    def __init__(self, llm, workspace: Path, venv_path: Optional[Path] = None, brain=None,
                 callbacks: Optional[AgentCallbacks] = None, entry_hint: str = ""):
        self.llm = llm
        self.workspace = Path(workspace).resolve()
        self.venv_path = Path(venv_path) if venv_path else None
        self.brain = brain
        self.cb = callbacks or AgentCallbacks()
        self.entry_hint = entry_hint
        self.context_tokens = int(_cfg("AGENT_CONTEXT_TOKENS", 0) or getattr(llm, "num_ctx", 0)
                                  or _cfg("OLLAMA_NUM_CTX", 16384))
        self.output_reserve = int(_cfg("AGENT_OUTPUT_RESERVE", 6000))
        brain_ok = bool(brain is not None and (getattr(brain, "semantic", None) is not None))
        self.executor = ActionExecutor(self.workspace, self.venv_path,
                                       brain_query=self._brain_query if brain_ok else None,
                                       allow_run=_cfg("AGENT_ALLOW_RUN", True))

    # ── budgets ──────────────────────────────────────────────────────
    @property
    def input_budget(self) -> int:
        """Tokens available for the conversation (window minus reply room and system prompt)."""
        return max(2000, self.context_tokens - self.output_reserve - estimate_tokens(prompts.SYSTEM_PROMPT))

    def _fit_budget(self, task: str, plan_text: str) -> int:
        frac = float(_cfg("AGENT_FIT_FRACTION", 0.6))
        return int((self.input_budget - estimate_tokens(task) - estimate_tokens(plan_text)) * frac)

    @staticmethod
    def _conv_tokens(messages: List[dict]) -> int:
        return sum(estimate_tokens(m["content"]) + 4 for m in messages)

    async def _status(self, msg: str):
        log.info("Agent: %s", msg)
        if self.cb.on_status:
            await self.cb.on_status(msg)

    async def _llm(self, messages: List[dict], system: str) -> str:
        reply = await self.llm.chat(
            messages, system=system, on_token=self.cb.on_token, on_thinking=self.cb.on_thinking,
            disable_think=not _cfg("AGENT_THINK", False),
        )
        if self.cb.on_llm_done:
            await self.cb.on_llm_done(reply)
        return reply

    # ── planning (read-only, like OpenCode's plan mode) ──────────────
    async def plan(self, task: str) -> Tuple[str, List[Tuple[str, str]]]:
        snap = take_snapshot(self.workspace, self._fit_budget(task, ""), estimate_tokens(task))
        await self._status("Planning the implementation...")
        reply = await self._llm([{"role": "user", "content": prompts.plan_message(task, snap.render())}],
                                prompts.PLAN_SYSTEM_PROMPT)
        return reply.strip(), parse_plan_files(reply)

    # ── main loop ────────────────────────────────────────────────────
    async def run(self, task: str, plan_text: str = "", planned_files: Optional[List[str]] = None,
                  notes: str = "") -> AgentResult:
        t0 = time.time()
        max_steps = int(_cfg("AGENT_MAX_STEPS", 12))
        max_repairs = int(_cfg("AGENT_MAX_REPAIR_ROUNDS", 3))
        planned = [p for p in (planned_files or []) if p]

        snap = take_snapshot(self.workspace, self._fit_budget(task, plan_text),
                             estimate_tokens(task) + estimate_tokens(plan_text))
        result = AgentResult(success=False, mode=snap.mode)
        messages = [{"role": "user", "content": prompts.initial_message(
            task, snap.render(self._map_budget()), plan_text, snap.mode, notes)}]
        changed: List[str] = []
        unchecked = False            # files changed since the last automatic check
        nudges = 0
        missing_prompts = 0

        for step in range(1, max_steps + 1):
            if self.cb.should_stop and self.cb.should_stop():
                result.stopped_reason = "cancelled"
                break
            if self.cb.wait_if_paused:
                await self.cb.wait_if_paused()
            if self._conv_tokens(messages) > self.input_budget:
                messages = self._rebase(task, plan_text, notes, changed, messages)

            result.steps = step
            await self._status("Writing code..." if step == 1 else f"Working (step {step})...")
            reply = await self._llm(messages, prompts.SYSTEM_PROMPT)
            result.llm_calls += 1
            parsed = parse_reply(reply)
            messages.append({"role": "assistant", "content": reply})

            results: List[ActionResult] = []
            for action in parsed.actions:
                r = await self.executor.execute(action)
                results.append(r)
                if r.ok and r.path:
                    unchecked = True
                    if r.path not in changed:
                        changed.append(r.path)
                    if self.cb.on_file_changed:
                        await self.cb.on_file_changed(r.path)
            if parsed.summary:
                result.summary = parsed.summary

            truncated = next((a.arg for a in parsed.actions if a.truncated), None)
            if truncated is None and getattr(self.llm, "last_done_reason", None) == "length" and parsed.writes:
                truncated = parsed.writes[-1].arg
            failed = [r for r in results if not r.ok]
            asked = parsed.queries

            if truncated:
                messages.append({"role": "user", "content": prompts.results_message(
                    _render(results), prompts.truncated_message(truncated))})
                continue
            if asked or failed:
                follow = "Fix the failed actions above and continue." if failed else ""
                messages.append({"role": "user", "content": prompts.results_message(_render(results), follow)})
                continue
            if not parsed.actions and not parsed.done:
                nudges += 1
                if nudges > 2:
                    result.stopped_reason = "model produced no actions"
                    break
                messages.append({"role": "user", "content":
                                 "You did not write any action blocks. Do the task now: write the files with "
                                 "### FILE blocks (complete content), then ### DONE."})
                continue

            missing = [p for p in planned if not (self.workspace / p).exists()]
            if missing and missing_prompts < 2:
                missing_prompts += 1
                messages.append({"role": "user", "content": prompts.results_message(
                    _render(results), prompts.continue_message(missing))})
                continue

            # The model is done (explicitly, or it wrote files and has nothing left to do).
            if unchecked and max_repairs >= 0:
                if self.cb.before_checks:
                    await self.cb.before_checks()
                await self._status("Running automatic checks...")
                diag = await run_diagnostics(self.workspace, self.venv_path, self.entry_hint,
                                             smoke_run=_cfg("AGENT_SMOKE_RUN", True),
                                             use_pyright=_cfg("AGENT_USE_PYRIGHT", True))
                unchecked = False
                result.diagnostics_history.append(len(diag.problems))
                result.final_problems = list(diag.problems)
                if diag.problems and result.repair_rounds < max_repairs:
                    result.repair_rounds += 1
                    await self._status(f"Checks found {len(diag.problems)} problem(s); fixing "
                                       f"(round {result.repair_rounds}/{max_repairs})...")
                    messages.append({"role": "user", "content": prompts.diagnostics_message(diag.render())})
                    continue
            result.stopped_reason = result.stopped_reason or "done"
            break
        else:
            result.stopped_reason = "max steps reached"
            if unchecked:
                diag = await run_diagnostics(self.workspace, self.venv_path, self.entry_hint,
                                             smoke_run=_cfg("AGENT_SMOKE_RUN", True),
                                             use_pyright=_cfg("AGENT_USE_PYRIGHT", True))
                result.diagnostics_history.append(len(diag.problems))
                result.final_problems = list(diag.problems)

        result.files_changed = changed
        result.success = bool(changed or result.summary) and not result.final_problems \
            and result.stopped_reason in ("done",)
        result.seconds = round(time.time() - t0, 1)
        log.info("Agent finished: %s, %d step(s), %d LLM call(s), %d repair round(s), %d file(s), %.0fs",
                 result.stopped_reason, result.steps, result.llm_calls, result.repair_rounds,
                 len(changed), result.seconds)
        return result

    # ── context management ───────────────────────────────────────────
    def _map_budget(self) -> int:
        return max(1500, int(self.input_budget * 0.45))

    def _rebase(self, task: str, plan_text: str, notes: str, changed: List[str],
                messages: List[dict]) -> List[dict]:
        """Rebuild the conversation from ground truth when it outgrows the window."""
        snap = take_snapshot(self.workspace, self._fit_budget(task, plan_text),
                             estimate_tokens(task) + estimate_tokens(plan_text))
        progress = ("Progress so far (earlier conversation was compacted): "
                    + (f"files written or changed: {', '.join(changed)}." if changed else "no files written yet."))
        last_user = messages[-1]["content"] if messages and messages[-1]["role"] == "user" else ""
        content = prompts.initial_message(task, snap.render(self._map_budget()), plan_text, snap.mode,
                                          (notes + "\n" + progress).strip())
        if last_user:
            content += "\n\n" + last_user
        log.info("Agent: conversation compacted (%d -> ~%d tokens, %s mode)",
                 self._conv_tokens(messages), estimate_tokens(content), snap.mode)
        return [{"role": "user", "content": content}]

    # ── BRAIN action: knowledge graph + semantic search + AST ───────
    async def _brain_query(self, question: str) -> str:
        lines: List[str] = []
        try:
            hits = self.brain.semantic.query_similar_files(question, n_results=6) or []
        except Exception as e:
            hits = []
            log.debug("semantic query failed: %s", e)
        seen = []
        for h in hits:
            path = h.get("file_path") or h.get("metadata", {}).get("file_path")
            if path and path not in seen:
                seen.append(path)
        graph = getattr(self.brain, "graph", None)
        for path in seen[:6]:
            lines.append(f"{path}")
            text = read_text(self.workspace, path)
            if text is not None and path.endswith(".py"):
                lines += python_outline(text)[:15]
            if graph is not None and graph.is_available:
                try:
                    rel = graph.get_related_files(path, depth=1)
                    near = [r.get("path") for r in rel if r.get("path")][:6]
                    if near:
                        lines.append(f"  related: {', '.join(near)}")
                except Exception:
                    pass
        return "\n".join(lines) if lines else "No relevant files found. Try SEARCH."


def _render(results: List[ActionResult]) -> str:
    if not results:
        return "(no actions)"
    out = []
    for r in results:
        mark = "OK" if r.ok else "FAILED"
        if r.kind in ("FILE", "EDIT"):
            out.append(f"[{mark}] {r.message}")
        else:
            out.append(f"[{mark}] {r.kind} {r.arg}\n{r.message}")
    return "\n\n".join(out)


_PLAN_LINE = re.compile(r"^\s*[-*\d.)]+\s*`?([A-Za-z0-9_./\\-]+\.[A-Za-z0-9]+|[A-Za-z0-9_./\\-]*(?:Dockerfile|Makefile))`?\s*[:\-–—]\s*(.*)$")


def parse_plan_files(plan_text: str) -> List[Tuple[str, str]]:
    """Extract `- path: description` lines from the '## Files' section of a plan."""
    section = plan_text
    m = re.search(r"^#+\s*Files\s*$", plan_text, re.MULTILINE | re.IGNORECASE)
    if m:
        section = plan_text[m.end():]
        nxt = re.search(r"^#+\s", section, re.MULTILINE)
        if nxt:
            section = section[:nxt.start()]
    files: List[Tuple[str, str]] = []
    for line in section.splitlines():
        lm = _PLAN_LINE.match(line)
        if lm:
            path = lm.group(1).replace("\\", "/").lstrip("./")
            if path and path not in [f for f, _ in files]:
                files.append((path, lm.group(2).strip()))
    return files
