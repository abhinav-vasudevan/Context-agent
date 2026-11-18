"""
Workspace view for the agent loop.

Decides how the project is shown to the model — the "fit or retrieve" rule:

  * FULL mode  — the source files (plus the task) fit comfortably inside the
                 context window, so the model gets every file verbatim. Nothing
                 is split, summarised or retrieved: one coherent view, exactly
                 like a single-shot prompt.
  * MAP mode   — the codebase is too large to fit. The model gets a repo map
                 (exact AST signatures for every file, zero LLM calls) and reads
                 the files it needs with READ / SEARCH / BRAIN actions.

Token counts are estimated at ~3.5 characters per token, which is close to
the Llama/Qwen tokenizers on mixed English + code.
"""

from __future__ import annotations

import ast
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

CHARS_PER_TOKEN = 3.5

# Directories never shown to (or writable by) the model.
IGNORED_DIRS = {
    "venv", ".venv", "env", ".env", ".git", "node_modules", "__pycache__",
    "site-packages", "dist", "build", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".agent_brain", ".idea", ".vscode", "lib", "Lib", "Scripts",
    "Include",
}
# Agent bookkeeping files in the workspace root — not project source.
AGENT_FILES = {"project_state.json", "plan.txt", "architecture.md"}

TEXT_EXTENSIONS = {
    ".py", ".pyi", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".md",
    ".txt", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".html", ".htm", ".css",
    ".scss", ".sh", ".bat", ".ps1", ".sql", ".env.example", ".gitignore",
    ".rs", ".go", ".java", ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb",
    ".php", ".vue", ".svelte", ".xml", ".csv",
}
MAX_FILE_BYTES = 200_000   # larger files are listed but never inlined


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def is_ignored(rel_path: str) -> bool:
    parts = Path(rel_path).parts
    if any(p in IGNORED_DIRS for p in parts[:-1]):
        return True
    if len(parts) == 1 and parts[0] in AGENT_FILES:
        return True
    return False


def list_source_files(workspace: Path) -> List[str]:
    """Relative POSIX paths of the project's text/source files, sorted."""
    out: List[str] = []
    workspace = Path(workspace)
    if not workspace.exists():
        return out
    stack = [workspace]
    while stack:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for p in entries:
            if p.is_dir():
                if p.name in IGNORED_DIRS or (p.name.startswith(".") and p.name not in (".github",)):
                    continue
                # a nested virtualenv has pyvenv.cfg
                if (p / "pyvenv.cfg").exists():
                    continue
                stack.append(p)
            elif p.is_file():
                rel = p.relative_to(workspace).as_posix()
                if is_ignored(rel):
                    continue
                if p.suffix.lower() in TEXT_EXTENSIONS or p.name in ("Dockerfile", "Makefile", "Procfile"):
                    out.append(rel)
    return sorted(out)


def read_text(workspace: Path, rel: str) -> Optional[str]:
    p = Path(workspace) / rel
    try:
        if p.stat().st_size > MAX_FILE_BYTES:
            return None
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def language_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".py": "python", ".js": "javascript", ".jsx": "jsx", ".ts": "typescript",
        ".tsx": "tsx", ".json": "json", ".md": "markdown", ".html": "html",
        ".css": "css", ".sh": "bash", ".yaml": "yaml", ".yml": "yaml",
        ".toml": "toml", ".sql": "sql", ".txt": "text",
    }.get(ext, "")


# ── Python AST outline (exact signatures, no LLM) ────────────────────────

def _sig(fn: ast.AST) -> str:
    try:
        args = ast.unparse(fn.args)  # type: ignore[attr-defined]
    except Exception:
        args = "..."
    ret = ""
    if getattr(fn, "returns", None) is not None:
        try:
            ret = " -> " + ast.unparse(fn.returns)  # type: ignore[attr-defined]
        except Exception:
            ret = ""
    prefix = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {fn.name}({args}){ret}"  # type: ignore[attr-defined]


def python_outline(source: str) -> List[str]:
    """Top-level classes (with method signatures), functions and constants."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"  (syntax error: line {e.lineno}: {e.msg})"]
    lines: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases) if node.bases else ""
            lines.append(f"  class {node.name}({bases})" if bases else f"  class {node.name}")
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    lines.append(f"      {_sig(item)}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            lines.append(f"  {_sig(node)}")
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    lines.append(f"  {t.id} = ...")
    return lines


def python_imports(source: str) -> List[str]:
    """Module names imported by a Python file (absolute and relative)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    mods: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = "." * (node.level or 0) + (node.module or "")
            mods.append(base)
            # `from pkg import module` may import a submodule
            if node.module:
                mods.extend(f"{base}.{a.name}" for a in node.names)
    return mods


def resolve_local_import(module: str, importer: str, files: List[str]) -> Optional[str]:
    """Map an import to a project file (handles `src/` layouts and relative imports)."""
    candidates: List[str] = []
    if module.startswith("."):
        level = len(module) - len(module.lstrip("."))
        rest = module.lstrip(".")
        base = Path(importer).parent
        for _ in range(level - 1):
            base = base.parent
        stem = (base / rest.replace(".", "/")) if rest else base
        candidates += [f"{stem.as_posix()}.py", f"{stem.as_posix()}/__init__.py"]
    else:
        rel = module.replace(".", "/")
        for root in ("", "src/", Path(importer).parent.as_posix() + "/"):
            root = "" if root in ("./", "/") else root
            candidates += [f"{root}{rel}.py", f"{root}{rel}/__init__.py"]
    fileset = set(files)
    for c in candidates:
        c = c.lstrip("/")
        if c in fileset:
            return c
    return None


# ── Snapshot ─────────────────────────────────────────────────────────────

@dataclass
class Snapshot:
    mode: str                                   # "full" | "map"
    files: List[str] = field(default_factory=list)
    contents: Dict[str, str] = field(default_factory=dict)
    total_tokens: int = 0

    def render(self, map_budget_tokens: int = 4000) -> str:
        if not self.files:
            return "The workspace is empty — this is a new project."
        if self.mode == "full":
            parts = [f"The workspace contains {len(self.files)} file(s). Their CURRENT contents:"]
            for rel in self.files:
                text = self.contents.get(rel)
                if text is None:
                    parts.append(f"\n--- {rel} (too large to show; use READ) ---")
                    continue
                parts.append(f"\n--- {rel} ---\n```{language_of(rel)}\n{text.rstrip()}\n```")
            return "\n".join(parts)
        return render_repo_map(self.files, self.contents, map_budget_tokens)


def render_repo_map(files: List[str], contents: Dict[str, str], budget_tokens: int) -> str:
    """Compact map of the codebase: every path, plus exact Python signatures."""
    header = (f"The codebase has {len(files)} files — too large to show in full. "
              "Below is a map with exact signatures. READ a file before editing it.\n")
    out = [header]
    used = estimate_tokens(header)
    shown = 0
    for rel in files:
        block = [rel]
        text = contents.get(rel)
        if rel.endswith(".py") and text is not None:
            block += python_outline(text)
        chunk = "\n".join(block)
        t = estimate_tokens(chunk)
        if used + t > budget_tokens:
            break
        out.append(chunk)
        used += t
        shown += 1
    if shown < len(files):
        out.append(f"... and {len(files) - shown} more files (use SEARCH or BRAIN to find them).")
    return "\n".join(out)


def take_snapshot(workspace: Path, fit_budget_tokens: int, task_tokens: int = 0) -> Snapshot:
    """Read the workspace and choose FULL or MAP mode (the fit-or-retrieve rule)."""
    files = list_source_files(workspace)
    contents: Dict[str, str] = {}
    total = 0
    for rel in files:
        text = read_text(workspace, rel)
        if text is not None:
            contents[rel] = text
            total += estimate_tokens(text) + 12
    mode = "full" if total + task_tokens <= fit_budget_tokens else "map"
    log.info("Workspace snapshot: %d files, ~%d tokens -> %s mode (budget %d)",
             len(files), total, mode.upper(), fit_budget_tokens)
    return Snapshot(mode=mode, files=files, contents=contents, total_tokens=total)
