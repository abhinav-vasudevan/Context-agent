"""
Action protocol for the agent loop.

The model acts on the workspace by writing plain-text action blocks:

    ### FILE: path/to/file.py
    ```python
    <complete file content>
    ```

    ### EDIT: path/to/file.py
    <<<<<<< SEARCH
    <exact lines from the current file>
    =======
    <replacement lines>
    >>>>>>> REPLACE

    ### READ: path/to/file.py [start-end]
    ### SEARCH: <regex>
    ### BRAIN: <question>
    ### RUN: <shell command>
    ### DONE
    <short summary>

A text protocol is used instead of JSON tool calls because small local models
(7–8B) are far more reliable at emitting fenced code than at escaping whole
files inside JSON strings. The parser is deliberately lenient about header
style (##/###/####, backticks or bold around paths) so formatting slips don't
lose work.

Edits follow OpenCode's rules (reference/opencode/.../tool/plugin/edit.ts):
exact match first, then whitespace-tolerant matching; the match must be
unique; on a miss the error shows the closest lines so the next attempt can
succeed without re-reading the file.
"""

from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Tuple

from core.agent.workspace import IGNORED_DIRS, AGENT_FILES, list_source_files, read_text

log = logging.getLogger(__name__)

ACTION_KINDS = ("FILE", "EDIT", "READ", "SEARCH", "BRAIN", "RUN", "DONE")
_HEADER = re.compile(
    r"^[ \t]*(?:#{2,4}|\*\*)[ \t]*(FILE|EDIT|READ|SEARCH|BRAIN|RUN|DONE)\b[ \t]*:?[ \t]*(.*?)[ \t]*(?:\*\*)?[ \t]*$",
    re.MULTILINE,
)
_FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")

READ_MAX_LINES = 400
READ_MAX_CHARS = 16_000
SEARCH_MAX_HITS = 40
RUN_TIMEOUT = 90
RUN_MAX_CHARS = 4_000


@dataclass
class Action:
    kind: str
    arg: str = ""
    body: str = ""
    truncated: bool = False        # FILE block whose closing fence never arrived


@dataclass
class ActionResult:
    kind: str
    arg: str
    ok: bool
    message: str
    path: Optional[str] = None     # file written/edited


@dataclass
class ParsedReply:
    actions: List[Action] = field(default_factory=list)
    done: bool = False
    summary: str = ""

    @property
    def writes(self) -> List[Action]:
        return [a for a in self.actions if a.kind in ("FILE", "EDIT")]

    @property
    def queries(self) -> List[Action]:
        return [a for a in self.actions if a.kind in ("READ", "SEARCH", "BRAIN", "RUN")]


def _clean_path(raw: str) -> str:
    p = raw.strip().strip("`'\"*").strip()
    p = p.split()[0] if p else p        # drop trailing words like "(new file)"
    p = p.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _strip_fences(body: str) -> Tuple[str, bool]:
    """Return the code inside the first opening fence and the LAST closing
    fence of a block (so fenced examples inside a README survive).
    Second value is True if the block opened a fence but never closed it."""
    lines = body.split("\n")
    # skip leading blank / prose lines until the opening fence
    start = None
    for i, line in enumerate(lines):
        if _FENCE.match(line):
            start = i
            break
        if line.strip() and i > 3:
            break
    if start is None:
        text = body.strip("\n")
        return (text + "\n" if text else ""), False
    fence = _FENCE.match(lines[start]).group(1)
    end = None
    for j in range(len(lines) - 1, start, -1):
        s = lines[j].strip()
        if s.startswith(fence[0] * 3) and set(s) <= {fence[0]}:
            end = j
            break
    if end is None:
        return "\n".join(lines[start + 1:]).rstrip() + "\n", True
    return "\n".join(lines[start + 1:end]).rstrip("\n") + "\n", False


def parse_reply(text: str) -> ParsedReply:
    reply = ParsedReply()
    headers = list(_HEADER.finditer(text))
    for i, m in enumerate(headers):
        kind, arg = m.group(1).upper(), m.group(2).strip()
        body_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[m.end():body_end].lstrip("\n")
        if kind == "DONE":
            reply.done = True
            reply.summary = (arg + "\n" + body).strip()[:2000]
            continue
        if kind == "FILE":
            path = _clean_path(arg)
            if not path:
                continue
            content, truncated = _strip_fences(body)
            # A FILE block that is the last thing in the reply and never closed
            # its fence was cut off by the output limit.
            is_last = i + 1 == len(headers)
            reply.actions.append(Action("FILE", path, content, truncated=truncated and is_last))
        elif kind == "EDIT":
            path = _clean_path(arg)
            if path:
                reply.actions.append(Action("EDIT", path, body))
        else:
            if kind == "READ":
                arg = arg.strip("`'\"*")
            elif kind == "RUN":
                arg = arg.strip().strip("`")
                if not arg:                      # command on the next line / in a fence
                    inner, _ = _strip_fences(body)
                    arg = inner.strip().split("\n")[0] if inner.strip() else ""
            if arg:
                reply.actions.append(Action(kind, arg, body))
    return reply


# ── Edit matching (exact → whitespace-tolerant), unique match required ──

_EDIT_BLOCK = re.compile(
    r"<{5,9}\s*SEARCH\s*\n(.*?)\n?={5,9}\s*\n(.*?)\n?>{5,9}\s*REPLACE", re.DOTALL)


def _find_all(hay: str, needle: str) -> List[int]:
    out, i = [], hay.find(needle)
    while i != -1 and needle:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def _line_spans(source_lines: List[str], search_lines: List[str], norm) -> List[int]:
    n = len(search_lines)
    target = [norm(s) for s in search_lines]
    hits = []
    for i in range(len(source_lines) - n + 1):
        if [norm(s) for s in source_lines[i:i + n]] == target:
            hits.append(i)
    return hits


def apply_edit(source: str, search: str, replace: str) -> Tuple[Optional[str], str]:
    """Return (new_source, "") or (None, error message with a hint)."""
    if search.strip() == "":
        return None, "SEARCH block is empty. Use ### FILE to write the whole file instead."
    # 1. exact
    hits = _find_all(source, search)
    if len(hits) == 1:
        return source[:hits[0]] + replace + source[hits[0] + len(search):], ""
    if len(hits) > 1:
        return None, (f"SEARCH text matches {len(hits)} places. Include more surrounding lines "
                      "so it identifies exactly one location.")
    # 2./3. line-based: ignore trailing whitespace, then leading indentation too
    src_lines = source.split("\n")
    s_lines = search.split("\n")
    r_lines = replace.split("\n")
    for norm in (str.rstrip, str.strip):
        spans = _line_spans(src_lines, s_lines, norm)
        if len(spans) == 1:
            i = spans[0]
            # keep the file's indentation when the model dropped it
            if norm is str.strip and src_lines[i].strip():
                file_indent = src_lines[i][: len(src_lines[i]) - len(src_lines[i].lstrip())]
                model_indent = s_lines[0][: len(s_lines[0]) - len(s_lines[0].lstrip())]
                if file_indent != model_indent:
                    r_lines = [
                        (file_indent + ln[len(model_indent):] if ln.startswith(model_indent) else file_indent + ln.lstrip())
                        if ln.strip() else ln
                        for ln in r_lines
                    ]
            new = src_lines[:i] + r_lines + src_lines[i + len(s_lines):]
            return "\n".join(new), ""
        if len(spans) > 1:
            return None, (f"SEARCH text matches {len(spans)} places. Include more surrounding lines "
                          "so it identifies exactly one location.")
    return None, "SEARCH text not found in the file. " + _miss_hint(src_lines, s_lines)


def _miss_hint(src_lines: List[str], s_lines: List[str]) -> str:
    """Show the region of the file that best matches the SEARCH block (numbered)."""
    if not src_lines or not s_lines:
        return ""
    n = len(s_lines)
    key = "\n".join(s.strip() for s in s_lines)
    best, best_i = 0.0, 0
    for i in range(0, max(1, len(src_lines) - n + 1)):
        cand = "\n".join(s.strip() for s in src_lines[i:i + n])
        r = difflib.SequenceMatcher(None, key, cand).quick_ratio()
        if r > best:
            best, best_i = r, i
    if best < 0.4:
        return "Copy the SEARCH lines exactly from the current file (READ it first)."
    lo, hi = max(0, best_i - 2), min(len(src_lines), best_i + n + 2)
    shown = "\n".join(f"{k + 1}: {src_lines[k]}" for k in range(lo, hi))
    return f"The closest lines in the current file are:\n{shown}\nCopy them exactly (without the line numbers)."


# ── Executor ─────────────────────────────────────────────────────────────

BrainFn = Callable[[str], Awaitable[str]]


class ActionExecutor:
    """Applies parsed actions to the workspace, safely."""

    def __init__(self, workspace: Path, venv_path: Optional[Path] = None,
                 brain_query: Optional[BrainFn] = None, allow_run: bool = True):
        self.workspace = Path(workspace).resolve()
        self.venv_path = Path(venv_path) if venv_path else None
        self.brain_query = brain_query
        self.allow_run = allow_run

    # -- path safety --------------------------------------------------
    def _safe_path(self, rel: str) -> Tuple[Optional[Path], str]:
        if not rel or rel.startswith("~") or re.match(r"^[A-Za-z]:", rel):
            return None, f"Invalid path '{rel}': use a path relative to the project root."
        full = (self.workspace / rel).resolve()
        try:
            full.relative_to(self.workspace)
        except ValueError:
            return None, f"Path '{rel}' is outside the project."
        parts = Path(rel).parts
        if any(p in IGNORED_DIRS for p in parts) or (len(parts) == 1 and parts[0] in AGENT_FILES):
            return None, f"Path '{rel}' is reserved and cannot be modified."
        return full, ""

    async def execute(self, action: Action) -> ActionResult:
        try:
            if action.kind == "FILE":
                return self._write(action)
            if action.kind == "EDIT":
                return self._edit(action)
            if action.kind == "READ":
                return self._read(action)
            if action.kind == "SEARCH":
                return self._search(action)
            if action.kind == "BRAIN":
                return await self._brain(action)
            if action.kind == "RUN":
                return await self._run(action)
        except Exception as e:  # never let one bad action kill the loop
            log.exception("Action %s %s failed", action.kind, action.arg)
            return ActionResult(action.kind, action.arg, False, f"Internal error: {e}")
        return ActionResult(action.kind, action.arg, False, "Unknown action")

    def _write(self, a: Action) -> ActionResult:
        if a.truncated:
            return ActionResult("FILE", a.arg, False,
                                f"Your reply was cut off while writing {a.arg}; the file was NOT saved.")
        full, err = self._safe_path(a.arg)
        if not full:
            return ActionResult("FILE", a.arg, False, err)
        content = a.body
        stripped = content.strip()
        placeholder = re.search(r"^\s*(#|//)\s*\.\.\.\s*(rest|existing|remaining|same|unchanged)?", content,
                                re.MULTILINE | re.IGNORECASE)
        if placeholder and len(stripped.splitlines()) < 400 and full.exists():
            return ActionResult("FILE", a.arg, False,
                                f"{a.arg} contains a placeholder ('{placeholder.group(0).strip()}'). "
                                "Write the COMPLETE file, or use ### EDIT for a small change.")
        full.parent.mkdir(parents=True, exist_ok=True)
        existed = full.exists()
        full.write_text(content, encoding="utf-8")
        n = len(content.splitlines())
        return ActionResult("FILE", a.arg, True,
                            f"{'Updated' if existed else 'Created'} {a.arg} ({n} lines).", path=a.arg)

    def _edit(self, a: Action) -> ActionResult:
        full, err = self._safe_path(a.arg)
        if not full:
            return ActionResult("EDIT", a.arg, False, err)
        if not full.exists():
            return ActionResult("EDIT", a.arg, False,
                                f"{a.arg} does not exist. Use ### FILE to create it.")
        blocks = _EDIT_BLOCK.findall(a.body)
        if not blocks:
            return ActionResult("EDIT", a.arg, False,
                                "No <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block found.")
        source = full.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        for k, (search, replace) in enumerate(blocks, 1):
            new, msg = apply_edit(source, search, replace)
            if new is None:
                applied = f" (blocks 1-{k - 1} were applied)" if k > 1 else ""
                if k > 1:
                    full.write_text(source, encoding="utf-8")
                return ActionResult("EDIT", a.arg, False, f"Edit block {k} failed{applied}: {msg}",
                                    path=a.arg if k > 1 else None)
            source = new
        full.write_text(source, encoding="utf-8")
        return ActionResult("EDIT", a.arg, True, f"Edited {a.arg} ({len(blocks)} change(s)).", path=a.arg)

    def _read(self, a: Action) -> ActionResult:
        m = re.match(r"(.+?)(?:\s+(?:lines?\s*)?(\d+)\s*[-:]\s*(\d+))?$", a.arg.strip())
        rel = _clean_path(m.group(1)) if m else _clean_path(a.arg)
        full = (self.workspace / rel)
        if full.is_dir():
            files = [f for f in list_source_files(self.workspace) if f.startswith(rel.rstrip("/") + "/")]
            return ActionResult("READ", rel, True, f"Directory {rel}:\n" + "\n".join(files[:200]))
        text = read_text(self.workspace, rel)
        if text is None:
            return ActionResult("READ", rel, False, f"File not found or too large: {rel}")
        lines = text.split("\n")
        start = int(m.group(2)) if m and m.group(2) else 1
        end = int(m.group(3)) if m and m.group(3) else min(len(lines), start + READ_MAX_LINES - 1)
        end = min(end, len(lines), start + READ_MAX_LINES - 1)
        body = "\n".join(f"{i}: {lines[i - 1]}" for i in range(max(1, start), end + 1))
        if len(body) > READ_MAX_CHARS:
            body = body[:READ_MAX_CHARS] + "\n[... truncated]"
        more = f"\n[{len(lines) - end} more lines — READ {rel} {end + 1}-{end + READ_MAX_LINES}]" if end < len(lines) else ""
        return ActionResult("READ", rel, True, f"{rel} (lines {start}-{end} of {len(lines)}):\n{body}{more}")

    def _search(self, a: Action) -> ActionResult:
        try:
            rx = re.compile(a.arg)
        except re.error:
            rx = re.compile(re.escape(a.arg))
        hits = []
        for rel in list_source_files(self.workspace):
            text = read_text(self.workspace, rel)
            if text is None:
                continue
            for n, line in enumerate(text.split("\n"), 1):
                if rx.search(line):
                    hits.append(f"{rel}:{n}: {line.strip()[:160]}")
                    if len(hits) >= SEARCH_MAX_HITS:
                        break
            if len(hits) >= SEARCH_MAX_HITS:
                break
        if not hits:
            return ActionResult("SEARCH", a.arg, True, f"No matches for /{a.arg}/.")
        extra = " (first 40 shown)" if len(hits) >= SEARCH_MAX_HITS else ""
        return ActionResult("SEARCH", a.arg, True, f"Matches for /{a.arg}/{extra}:\n" + "\n".join(hits))

    async def _brain(self, a: Action) -> ActionResult:
        if not self.brain_query:
            return ActionResult("BRAIN", a.arg, False, "The knowledge graph is not available; use SEARCH and READ.")
        text = await self.brain_query(a.arg)
        return ActionResult("BRAIN", a.arg, True, text or "No results.")

    async def _run(self, a: Action) -> ActionResult:
        if not self.allow_run:
            return ActionResult("RUN", a.arg, False, "Running commands is disabled.")
        from core.runner import SecurityChecker
        blocked = SecurityChecker.check_command(a.arg)
        if blocked:
            return ActionResult("RUN", a.arg, False, blocked)
        code, out = await run_command(a.arg, self.workspace, self.venv_path, RUN_TIMEOUT)
        status = "timed out" if code is None else f"exit code {code}"
        return ActionResult("RUN", a.arg, code == 0, f"$ {a.arg}\n({status})\n{out}")


def venv_env(workspace: Path, venv_path: Optional[Path]) -> dict:
    env = os.environ.copy()
    if venv_path and Path(venv_path).exists():
        bin_dir = Path(venv_path) / ("Scripts" if os.name == "nt" else "bin")
        env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["VIRTUAL_ENV"] = str(venv_path)
    env["PYTHONPATH"] = str(Path(workspace).resolve())
    env["PYTHONIOENCODING"] = "utf-8"
    return env


async def run_command(command: str, workspace: Path, venv_path: Optional[Path],
                      timeout: int) -> Tuple[Optional[int], str]:
    """Run a non-interactive shell command (stdin closed). Returns (exit code or None on timeout, output)."""
    proc = await asyncio.create_subprocess_shell(
        command, cwd=str(workspace), env=venv_env(workspace, venv_path),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        code = proc.returncode
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        out, code = b"", None
    text = (out or b"").decode("utf-8", errors="replace")
    if len(text) > RUN_MAX_CHARS:
        text = text[:RUN_MAX_CHARS // 2] + "\n[... output truncated ...]\n" + text[-RUN_MAX_CHARS // 2:]
    return code, text
