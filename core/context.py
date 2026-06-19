"""
Context Engine — File Registry + Context Assembler.

This is the MOST IMPORTANT module in the Context Agent.
It solves the #1 problem from the old system: code stitching.

The File Registry uses Python's `ast` module to parse generated files
and extract ACTUAL class names, function signatures, and imports —
NOT summaries or prose. This concrete data is injected into every
LLM prompt so the model always knows exactly what files exist and
how to import from them.

The Context Assembler builds the final LLM prompt for each step,
managing token budgets to stay within the context window.
"""

from __future__ import annotations
import ast
import logging
import re
import sys
from pathlib import Path
from typing import Optional, List

import config
from core.llm_client import LLMClient
from models.state import FileEntry, ProjectState, PlanStep

log = logging.getLogger(__name__)

# Python version check for AST compatibility
_PY_39_PLUS = sys.version_info >= (3, 9)


class FileRegistryBuilder:
    """
    Parses Python files using the `ast` module to extract concrete
    structural information. This is deterministic — no LLM calls.

    What it extracts:
      - Class names and their methods (with argument signatures)
      - Top-level function names (with argument signatures)
      - Import statements
      - Module-level constants (ALL_CAPS variable names)
    """

    @staticmethod
    def parse_file(file_path: Path, relative_path: str) -> Optional[FileEntry]:
        """
        Parse a Python file and return a FileEntry with extracted structure.

        Args:
            file_path: Absolute path to the .py file
            relative_path: Relative path within workspace (e.g. "src/calc.py")

        Returns:
            FileEntry with parsed structure, or None if parsing fails
        """
        if not file_path.exists():
            return None

        try:
            source = file_path.read_text(encoding="utf-8")
        except Exception as e:
            log.warning("Cannot read file %s: %s", file_path, e)
            return None

        # Only parse Python files with ast
        if not relative_path.endswith(".py"):
            return FileEntry(path=relative_path)

        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            log.warning("Syntax error in %s: %s", relative_path, e)
            # Still return a basic entry — the file exists even if broken
            return FileEntry(
                path=relative_path,
                imports=FileRegistryBuilder._extract_imports_regex(source),
            )

        entry = FileEntry(path=relative_path)

        for node in ast.iter_child_nodes(tree):
            # ── Imports ───────────────────────────────────────────
            if isinstance(node, ast.Import):
                for alias in node.names:
                    entry.imports.append(f"import {alias.name}")

            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names = ", ".join(a.name for a in node.names)
                entry.imports.append(f"from {module} import {names}")

            # ── Classes ───────────────────────────────────────────
            elif isinstance(node, ast.ClassDef):
                entry.classes.append(node.name)
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(item.name)
                        # Build signature for class methods
                        sig = FileRegistryBuilder._build_signature(item)
                        entry.function_signatures[f"{node.name}.{item.name}"] = sig
                entry.class_methods[node.name] = methods

            # ── Functions ─────────────────────────────────────────
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                entry.functions.append(node.name)
                sig = FileRegistryBuilder._build_signature(node)
                entry.function_signatures[node.name] = sig

            # ── Constants (ALL_CAPS names) ────────────────────────
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        entry.constants.append(target.id)

        return entry

    @staticmethod
    def _build_signature(func_node) -> str:
        """Build a human-readable function signature from an AST FunctionDef."""
        name = func_node.name
        args = []

        for arg in func_node.args.args:
            arg_name = arg.arg
            # Skip 'self' and 'cls'
            if arg_name in ("self", "cls"):
                continue
            # Try to get type annotation
            if arg.annotation:
                ann_str = FileRegistryBuilder._annotation_to_str(arg.annotation)
                if ann_str:
                    args.append(f"{arg_name}: {ann_str}")
                else:
                    args.append(arg_name)
            else:
                args.append(arg_name)

        # Check for return type
        returns = ""
        if func_node.returns:
            ret_str = FileRegistryBuilder._annotation_to_str(func_node.returns)
            if ret_str:
                returns = f" -> {ret_str}"

        return f"{name}({', '.join(args)}){returns}"

    @staticmethod
    def _annotation_to_str(node) -> str:
        """
        Convert an AST annotation node to a readable string.
        Compatible with Python 3.8+.
        """
        # Try ast.unparse first (Python 3.9+)
        if _PY_39_PLUS and hasattr(ast, "unparse"):
            try:
                return ast.unparse(node)
            except Exception:
                pass

        # Fallback for Python 3.8
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            parts = []
            current = node
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            return ".".join(reversed(parts))
        elif isinstance(node, ast.Constant):
            return repr(node.value)
        elif isinstance(node, ast.Subscript):
            # Handle things like List[str], Optional[int]
            value_str = FileRegistryBuilder._annotation_to_str(node.value)
            # Python 3.8 uses ast.Index wrapper, 3.9+ uses the slice directly
            slice_node = node.slice
            if not _PY_39_PLUS and hasattr(ast, "Index") and isinstance(slice_node, ast.Index):
                slice_node = slice_node.value
            slice_str = FileRegistryBuilder._annotation_to_str(slice_node)
            return f"{value_str}[{slice_str}]" if value_str and slice_str else value_str or ""
        elif isinstance(node, ast.Tuple):
            elts = [FileRegistryBuilder._annotation_to_str(e) for e in node.elts]
            return ", ".join(e for e in elts if e)

        return ""

    @staticmethod
    def _extract_imports_regex(source: str) -> List[str]:
        """Fallback: extract imports using regex when AST parsing fails."""
        imports = []
        for line in source.split("\n"):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                imports.append(stripped)
        return imports


class ContextAssembler:
    """
    Builds the LLM prompt for each step, managing token budgets.

    The prompt is assembled in priority order:
    1. System prompt (PINNED — never truncated)
    2. File Registry (PINNED — the LLM MUST see all existing files and APIs)
    3. Current step description
    4. Previous step summaries (compressed if needed)
    5. Error context (if in fix mode)

    This replaces the old system's ContextBuilder which used abstract summaries
    that lost concrete details like function names and import paths.
    """

    # ── System prompts ────────────────────────────────────────────────

    CODER_SYSTEM_PROMPT = """You are a Python code generator. Your ONLY job is to output the requested code.

CRITICAL THINKING RULE (HIGHEST PRIORITY):
- Do NOT use <think> tags. Do NOT use long reasoning blocks.
- You MUST start your response with a `<brief_plan> ... </brief_plan>` block.
- This block MUST be MAX 15-20 words (2 short sentences). Going over = FAILURE.
- Example: `<brief_plan>Create Calculator class with add, subtract, multiply, divide methods. Use error handling for division.</brief_plan>`
- After <brief_plan>, output ONLY the code block. NOTHING else.

ABSOLUTE RULES — violating ANY means failure:
1. Your `<brief_plan>` block MUST be under 20 words. No essays, no long reasoning, no step-by-step analysis.
2. After the brief plan, you MUST output EXACTLY ONE Markdown code block (```python ... ```) containing the complete file.
3. DO NOT output multiple code blocks. DO NOT output any test scripts, usage examples, or `main.py` updates.
4. NO explanations, preamble, or "Here is the code" text outside of the brief plan.
5. The ENTIRE content inside the code block must be valid Python.
6. Write ONE complete, self-contained file.
7. Use the FILE REGISTRY to import from existing project files — do NOT redefine things that already exist. Pay close attention to function signatures and class definitions in the registry!
8. Every function and class must have a REAL implementation — NO empty pass stubs, NO "# TODO" placeholders.
9. NEVER use placeholders like `# ... existing code ...` or `# ... rest of file ...`. You MUST write out every single line of code so the file can be saved directly.
10. Add brief inline comments where logic is non-obvious.
11. NEVER import from `main.py` inside any `src/` modules. This causes Circular Imports! `main.py` should import from `src/`, not the other way around.
12. MANDATORY: Ensure all required standard libraries (like `requests`, `subprocess`, `json`) are explicitly imported at the top of the file.
13. MANDATORY: When calling functions or classes, meticulously check their signatures and ensure ALL required positional arguments are provided.
14. MANDATORY: If creating `main.py`, you MUST include a proper execution block `if __name__ == "__main__":` that completely instantiates the system and starts its main loop.
15. MANDATORY: NEVER use hardcoded placeholder values, dummy variables, or "example usage" data in your final code (e.g., `height = 175`). You MUST dynamically fetch inputs, use arguments, or parse user input correctly to wire up functions. The code must be production-ready!

WRONG (will be rejected):
Here is the code:
```python
class Calc: pass
```
Here is a test script:
```python
import sys
```

CORRECT:
<brief_plan>
[Very brief 2-3 sentence plan]
</brief_plan>
```python
[Complete code for exactly ONE file]
```
"""

    MARKDOWN_SYSTEM_PROMPT = """You are a technical documentation generator. You output ONLY raw Markdown or Text content.

ABSOLUTE RULES — violating ANY means failure:
1. Output ONLY raw Markdown/Text content.
2. DO NOT wrap the output in a giant ```markdown fence. Just output the raw text directly.
3. NO explanations, preamble, or "Here is the readme" text.
4. Your output is saved directly as a .md or .txt file.
"""

    PLANNER_SYSTEM_PROMPT = """You are an expert project planner and system architect.
Your job is to take a user's high-level request and produce a VERY DETAILED, step-by-step implementation plan.

MANDATORY RULES:
1. Step 1 MUST ALWAYS be creating `main.py` at the root. It MUST be a completely empty skeleton with NO imports. Just `if __name__ == "__main__":` and `pass`.
2. All other source files MUST go inside `src/` directory. Do NOT create nested directories like `src/src/` or `src/components/`. All source files MUST be placed directly inside `src/` (e.g., `src/calculator.py`).
3. There MUST be only ONE step for `main.py`. The system will automatically update it later, so do NOT create an 'update main.py' step.
4. The LAST step MUST be creating `README.md`.
5. Each step produces EXACTLY ONE file.
6. Steps must be numbered sequentially and have clear dependencies.
7. IMPORTANT: You MAY build interactive applications using `input()` or `while True:` loops. If you do, ensure you handle exceptions gracefully and provide clear prompts so the user knows what to type. If generating a script without interactivity, you MUST include simple hardcoded test calls inside an `if __name__ == "__main__":` block to verify functionality.
8. MANDATORY README.md Rules:
   - NEVER include fake git clone instructions or assume a git repository exists. Only document how to activate the venv and run the code.
   - ALWAYS explicitly mention what the AI actually built (the features, the system).
   - ALWAYS explain exactly how to use it (the commands, the inputs).
   - ALWAYS explain any terminology used in the system interface (e.g., if there's a chat prompt, explain what "User:", "Bot:", "Agent:" means and what the user is expected to type).
9. MANDATORY: Be explicitly precise about function signatures and required positional arguments in the Architecture and Descriptions so the coder knows exactly how to wire components together!
10. MANDATORY: Explicitly instruct the coder to NEVER use hardcoded placeholder values or dummy data in the final integration (e.g. main.py). The system MUST be wired up dynamically using actual user inputs or API responses.
11. CRITICAL: DO NOT use `<think>` tags, `<brief_plan>` tags, reasoning blocks, or preamble. You MUST start your response directly with `# [Project Title]`.

OUTPUT FORMAT — FOLLOW THIS EXACTLY:
You MUST structure your response EXACTLY like the template below. Do NOT deviate from this structure in any way. Do NOT use markdown code blocks to wrap the plan. Do NOT add conversational preamble like "Here is your plan". Every plan you output must be character-for-character identical in structure to this template.

=== BEGIN TEMPLATE ===

# [Project Title]

[One paragraph: what the system does, who it's for, and how it behaves.]

## Requirements & Acceptance Criteria

1. **[Requirement Name]** — [Detailed description of what this requirement means and how it will be verified.]
2. **[Requirement Name]** — [Description.]
(continue numbering...)

## Technical Architecture

**Data Structures:**
- [List all key data structures, classes, and their relationships]

**Key Modules:**
- `src/[module].py` — [What this module does and its public API]
(list all modules)

**Edge Cases & Challenges:**
- [List all edge cases the implementation must handle]

## Implementation Plan

---
STEP 1: Create main.py entry point
FILE: main.py
DEPENDS: none
DESCRIPTION:
Create a completely empty main.py file. Only include `if __name__ == "__main__":` followed by `pass`. Do NOT add any imports — the system will automatically wire this up as modules are created.

---
STEP 2: [Short Title]
FILE: src/[filename].py
DEPENDS: 1
DESCRIPTION:
[Detailed multi-line description. Include: class names, method signatures with argument types, return types, algorithm logic, data validation rules, error handling requirements, and edge cases to handle.]

---
STEP 3: [Short Title]
FILE: src/[filename].py
DEPENDS: 1, 2
DESCRIPTION:
[Detailed description...]

(continue for all implementation steps...)

---
STEP N: Create README.md
FILE: README.md
DEPENDS: 1, 2, ..., N-1
DESCRIPTION:
Create comprehensive documentation. Include: project description, how to activate venv, how to run, all features built, usage examples, and any manual setup required.

=== END TEMPLATE ===

FORMATTING RULES (violating any means failure):
- Use `#` for the project title, `##` for section headers. Nothing else.
- Write `---` on its own line BEFORE every STEP block (including STEP 1).
- Write `STEP N:` (uppercase, followed by colon and space) on its own line.
- Write `FILE:` (uppercase, followed by colon and space) on the NEXT line.
- Write `DEPENDS:` (uppercase, followed by colon and space) on the NEXT line.
- Write `DESCRIPTION:` (uppercase, followed by colon) on the NEXT line, with the actual description starting on the NEXT line after that.
- Do NOT use `**STEP**`, `### STEP`, `Step`, or any other formatting for step headers. Only `STEP N: Title`.
- Do NOT merge FILE and DEPENDS on the same line.
- Do NOT wrap the plan in a markdown code block.
- Do NOT number the steps with `1.`, `2.` format — use `STEP 1:`, `STEP 2:` format only."""

    FIXER_SYSTEM_PROMPT = """You are an expert Python debugger. You are given:
1. A Python file that has an error
2. The error traceback
3. The project's File Registry (showing all existing files and their APIs)

Your job: output the COMPLETE FIXED Python file. The entire file content, not just the fix.

CRITICAL THINKING RULE (HIGHEST PRIORITY):
- Do NOT use <think> tags. Do NOT use long reasoning blocks.
- Your `<brief_plan>` MUST be MAX 15-20 words. Going over = FAILURE.

RULES:
1. You MUST start your response with a `<brief_plan> ... </brief_plan>` block. This block MUST be under 20 words. Example: `<brief_plan>Fix missing import for requests module and correct function signature.</brief_plan>`
2. After the brief plan, you MUST output EXACTLY ONE Markdown code block (```python ... ```) containing the FULL, corrected file. Do NOT output partial files or diffs.
3. NEVER use placeholders like `# ... existing code ...` or `# ... rest of file ...`. You MUST write out every single line of code so the file can be saved directly. Omit nothing!
4. Keep all existing logic that is NOT related to the bug.
5. Use the FILE REGISTRY to ensure imports are correct AND to check exactly what arguments are required by functions or methods you are calling. Do not guess function signatures!
6. To fix Circular Imports (`ImportError: cannot import name...`), NEVER import `main.py` from any file inside `src/`. Remove the circular import completely.
7. CRITICAL: DO NOT output any conversational text like "Here is the fixed code" or "The error was caused by...". All reasoning MUST be strictly inside the `<brief_plan>` block. The REST of the output MUST be ONLY the markdown code block containing the Python code."""

    SUMMARY_SYSTEM_PROMPT = """Summarize what this code file does in ONE concrete sentence.
Include: file path, class names, function names, and what they do.
Be SPECIFIC — use actual names from the code, not generic descriptions.

WRONG: "Implements a calculator module"
RIGHT: "src/calculator.py defines class Calculator with methods add(a,b), subtract(a,b), multiply(a,b), divide(a,b) that perform basic arithmetic operations"

Output ONLY the one-sentence summary, nothing else."""

    def __init__(self, state: ProjectState):
        self.state = state
        self.knowledge = ""
        try:
            knowledge_path = config.PROJECT_ROOT / "knowledge.json"
            if knowledge_path.exists():
                import json
                data = json.loads(knowledge_path.read_text(encoding="utf-8"))
                self.knowledge = "\n\n=== GLOBAL KNOWLEDGE BASE ===\n" + json.dumps(data, indent=2) + "\n=============================\n"
        except Exception as e:
            log.warning("Failed to load knowledge.json: %s", e)

    def build_coder_prompt(self, step: PlanStep) -> dict:
        """
        Build the complete prompt for code generation.

        Returns:
            {"system": str, "prompt": str}
        """
        budget = config.OLLAMA_NUM_CTX
        parts = []
        used = LLMClient.count_tokens(self.CODER_SYSTEM_PROMPT)

        # 1. File Registry (PINNED — always included in full)
        registry_str = self.state.get_file_registry_string()
        registry_tokens = LLMClient.count_tokens(registry_str)
        parts.append(registry_str)
        used += registry_tokens

        # 2. Current step description (PINNED)
        step_block = self._format_step_block(step)
        step_tokens = LLMClient.count_tokens(step_block)
        parts.append(step_block)
        used += step_tokens

        # 3. Previous step summaries (compressed if needed)
        summaries = self.state.get_completed_summaries()
        if summaries:
            summary_block = f"\nCOMPLETED STEPS:\n{summaries}\n"
            summary_tokens = LLMClient.count_tokens(summary_block)
            remaining = budget - used - config.MIN_GENERATION_BUDGET
            if summary_tokens <= remaining:
                parts.append(summary_block)
                used += summary_tokens
            elif remaining > 200:
                # Truncate summaries to fit
                truncated = LLMClient.truncate_to_tokens(summary_block, remaining)
                parts.append(truncated)
                used += LLMClient.count_tokens(truncated)

        generation_budget = budget - used
        log.info(
            "Context for step '%s': used=%d tokens, generation_budget=%d",
            step.title, used, generation_budget,
        )

        system_prompt = self.MARKDOWN_SYSTEM_PROMPT if step.file_path.endswith((".md", ".txt")) else self.CODER_SYSTEM_PROMPT
        if self.knowledge:
            system_prompt += self.knowledge

        return {
            "system": system_prompt,
            "prompt": "\n\n".join(parts),
        }

    def build_fixer_prompt(
        self,
        file_path: str,
        file_content: str,
        error_text: str,
    ) -> dict:
        """
        Build the prompt for fixing a broken file.
        Includes the File Registry so the fixer knows correct import paths.
        """
        parts = []

        # File Registry
        parts.append(self.state.get_file_registry_string())

        # The broken file
        parts.append(f"FILE WITH ERROR: {file_path}")
        parts.append(f"```\n{file_content}\n```")

        # The error
        parts.append(f"ERROR:\n{error_text}")

        # Instruction
        parts.append(
            "Output the COMPLETE FIXED file content. "
            "Fix only the error above. Use the FILE REGISTRY for correct imports."
        )

        return {
            "system": self.FIXER_SYSTEM_PROMPT,
            "prompt": "\n\n".join(parts),
        }

    def build_planner_prompt(self, user_prompt: str) -> dict:
        """Build the prompt for plan generation."""
        prompt = f"""Create an EXTREMELY DETAILED implementation plan for the following project.

CRITICAL REMINDERS:
1. Start your response with `# [Project Title]` — NO preamble, NO thinking blocks, NO conversational text.
2. Step 1 MUST be main.py — completely empty except for `if __name__ == "__main__":` with `pass`. No imports.
3. All source files go in `src/`. Flat structure only (e.g., `src/math.py`, NOT `src/utils/math.py`).
4. Only ONE step for `main.py`. The system auto-updates it later.
5. Last step MUST be README.md.
6. Follow the EXACT format: `---` then `STEP N:` then `FILE:` then `DEPENDS:` then `DESCRIPTION:` each on separate lines.

USER REQUEST:
{user_prompt}

Output a comprehensive `## Requirements & Acceptance Criteria` section with numbered requirements, a `## Technical Architecture` section with data structures, modules, and edge cases, then the `## Implementation Plan` with STEP/FILE/DEPENDS/DESCRIPTION blocks separated by `---`.
"""
        return {
            "system": self.PLANNER_SYSTEM_PROMPT + self.knowledge,
            "prompt": prompt,
        }

    def build_summary_prompt(self, file_path: str, code_content: str) -> dict:
        """Build the prompt for generating a step summary."""
        # Truncate code if too long
        max_code_tokens = 2000
        if LLMClient.count_tokens(code_content) > max_code_tokens:
            code_content = LLMClient.truncate_to_tokens(code_content, max_code_tokens)

        return {
            "system": self.SUMMARY_SYSTEM_PROMPT,
            "prompt": f"File: {file_path}\n\n{code_content}",
        }

    def build_main_update_prompt(
        self,
        current_main_content: str,
        new_file_entry: FileEntry,
    ) -> dict:
        """
        Build the prompt for updating main.py to import a new module.
        This is called after each src/ file is generated.
        """
        system = """You are updating a Python main.py file to import and use a newly created module.

RULES:
1. Output the COMPLETE updated main.py file.
2. IF the new module provides classes or functions, add an import statement for it (e.g. `from src.<module> import <Class/function>`).
3. IF it provides classes or functions, add a usage example or integration in the `if __name__ == "__main__"` block.
4. IF the new module does NOT provide any classes or functions (e.g. it is just an empty script or entry point), DO NOT add any imports and DO NOT modify `main.py` except returning it exactly as it was.
5. Keep ALL existing imports and code — only ADD the new integration.
6. NO markdown, NO explanations. Output only raw Python code.
7. MANDATORY: Meticulously check the function signatures and class definitions of the new module. Ensure ALL required positional arguments are provided when you instantiate classes or call functions!
8. NEVER pass undefined variables as arguments. Always initialize necessary dependencies first.
"""

        prompt = f"""Current main.py content:
{current_main_content}

New module to integrate:
{new_file_entry.to_registry_string()}

FILE REGISTRY (all existing files):
{self.state.get_file_registry_string()}

Output the COMPLETE updated main.py with the new import and usage added."""

        return {
            "system": system,
            "prompt": prompt,
        }

    # ── Private helpers ───────────────────────────────────────────────

    def _format_step_block(self, step: PlanStep) -> str:
        """Format the current step description for the LLM."""
        block = "YOUR TASK:\n"
        block += f"Title: {step.title}\n"
        block += f"File to create: {step.file_path}\n"
        block += f"Description:\n{step.description}\n"

        if step.depends_on:
            # Include summaries of dependency steps
            dep_summaries = []
            for dep_num in step.depends_on:
                for s in self.state.plan_steps:
                    if s.step_number == dep_num and s.summary:
                        dep_summaries.append(f"  Step {dep_num}: {s.summary}")
            if dep_summaries:
                block += "\nDEPENDENCY CONTEXT (these steps are already completed):\n"
                block += "\n".join(dep_summaries)
                block += "\n"

        return block


class SmartChunker:
    """
    Splits large prompts into manageable chunks when the user prompt
    exceeds the context window. Splits by paragraphs and sentences,
    NOT randomly in the middle of words.
    """

    @staticmethod
    def needs_chunking(text: str) -> bool:
        """Check if the text exceeds the safe input size."""
        tokens = LLMClient.count_tokens(text)
        # Leave room for system prompt and generation
        safe_limit = config.OLLAMA_NUM_CTX - config.MIN_GENERATION_BUDGET - config.TOKEN_BUDGET_SYSTEM_PROMPT
        return tokens > safe_limit

    @staticmethod
    def chunk(text: str, max_tokens_per_chunk: int = 0) -> List[str]:
        """
        Split text into chunks that fit within the context window.
        Preserves paragraph and sentence boundaries.
        """
        if not max_tokens_per_chunk:
            max_tokens_per_chunk = (
                config.OLLAMA_NUM_CTX
                - config.TOKEN_BUDGET_SYSTEM_PROMPT
                - config.MIN_GENERATION_BUDGET
            ) // 2  # Use half the available budget per chunk

        # Split by double newlines (paragraphs) first
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_tokens = 0

        for para in paragraphs:
            para_tokens = LLMClient.count_tokens(para)

            if current_tokens + para_tokens > max_tokens_per_chunk:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_tokens = 0

                # If a single paragraph is too large, split by sentences
                if para_tokens > max_tokens_per_chunk:
                    sentences = re.split(r'(?<=[.!?])\s+', para)
                    for sent in sentences:
                        sent_tokens = LLMClient.count_tokens(sent)
                        if current_tokens + sent_tokens > max_tokens_per_chunk:
                            if current_chunk:
                                chunks.append("\n\n".join(current_chunk))
                            current_chunk = [sent]
                            current_tokens = sent_tokens
                        else:
                            current_chunk.append(sent)
                            current_tokens += sent_tokens
                else:
                    current_chunk.append(para)
                    current_tokens = para_tokens
            else:
                current_chunk.append(para)
                current_tokens += para_tokens

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks if chunks else [text]
