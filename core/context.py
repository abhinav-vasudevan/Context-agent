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

    CODER_SYSTEM_PROMPT = """You are an elite, autonomous Software Engineer. Your job is to implement the requested plan step using XML tools.

CRITICAL THINKING RULE (HIGHEST PRIORITY):
- Use <think> tags to reason about your implementation before writing code.

AVAILABLE TOOLS:
You must use the following XML tools to interact with the workspace:

1. `<write_file path="path/to/file.py">`
Use this to write the complete content of a new or existing file.
Format:
<write_file path="core/math.py">
def add(a, b):
    return a + b
</write_file>

2. `<run_command>`
Use this to securely execute shell commands in the project workspace (e.g. `pytest`, `python -m unittest`, `pip install`).
Format: `<run_command>pytest tests/test_api.py</run_command>`. The system will reply with the output.

3. `<done>`
Use this ONLY when you have fully implemented the requested code AND verified it runs correctly (if tests are possible).

ABSOLUTE RULES — violating ANY means failure:
1. You MUST use `<write_file>` to output code. NEVER use markdown code blocks like ```python.
2. The ENTIRE content inside `<write_file>` must be valid Python.
3. Use the FILE REGISTRY to import from existing project files. Pay close attention to function signatures!
4. Every function and class must have a REAL implementation — NO empty pass stubs, NO "# TODO" placeholders.
5. NEVER use placeholders like `# ... existing code ...`. You MUST write out every single line of code so the file can be saved directly.
6. MANDATORY: Ensure all required standard libraries (like `requests`, `json`) are explicitly imported at the top of the file.
7. MANDATORY: NEVER use hardcoded dummy variables.

Output your valid XML tools now."""

    MARKDOWN_SYSTEM_PROMPT = """You are a technical documentation generator. You output ONLY raw Markdown or Text content.

ABSOLUTE RULES — violating ANY means failure:
1. Output ONLY raw Markdown/Text content.
2. DO NOT wrap the output in a giant ```markdown fence. Just output the raw text directly.
3. NO explanations, preamble, or "Here is the readme" text.
4. Your output is saved directly as a .md or .txt file.
"""

    ARCHITECT_SYSTEM_PROMPT = """You are an elite Software Architect.
Your job is to read a user's prompt and output a MASSIVE, highly detailed architectural blueprint (`architecture.md`).
You MUST use deep Chain-of-Thought reasoning to organically deduce the full scale of the system.
If the user asks for a simple script, design a simple script. 
If the user asks for an Operating System, an AI Agent, or a complex application, you MUST deduce the massive, multi-module architecture required to make it production-ready. Do NOT be lazy. Output thousands of words if necessary. Your blueprint must be EXHAUSTIVE.

MANDATORY SECTIONS:
1. `# System Architecture` (At least 500 words explaining the core design philosophy).
2. `## Core Components` (List EVERY module needed, e.g., `core/memory.py`, `backend/config.py`, `utils/helpers.py`, `core/error_handlers.py`, etc. For EACH file, write a 200+ word deep-dive explaining its exact logic, function signatures, and internal behaviors).
3. `## Data Structures` (Define all exact JSON schemas, classes, and state properties).
4. `## Edge Cases & Error Handling`

DO NOT write actual code files. Just write the highly detailed design document.
"""

    PLANNER_SYSTEM_PROMPT = """You are an expert project planner.
Your job is to take a detailed Architectural Blueprint and translate it into a strict, step-by-step implementation plan.

MANDATORY RULES:
1. Step 1 MUST ALWAYS be creating `main.py` at the root. It MUST be a completely empty skeleton with NO imports. Just `if __name__ == "__main__":` and `pass`.
2. All other source files MUST be placed in feature-based subdirectories (e.g., `core/`, `backend/`, `frontend/`, `models/`). Do NOT put everything in a flat directory. Use a deep, modular structure.
3. There MUST be only ONE step for `main.py`. The system will automatically update it later, so do NOT create an 'update main.py' step.
4. The LAST step MUST be creating `README.md`.
5. Each step produces EXACTLY ONE file.
6. Steps must be numbered sequentially and have clear dependencies.
7. DYNAMIC SCALING (CRITICAL ARCHITECTURE RULE): You must dynamically decide the number of files based on the complexity of the request.
   - For a simple script or calculator: generate 1-3 files.
   - For a complex application (e.g., an AI agent, an OS, a web backend): You MUST output AT LEAST 10-15 STEPS (files). Break the logic down heavily into modular components across domains (e.g., `core/memory.py`, `backend/server.py`, `models/state.py`, `utils/config.py`). If you group logic into giant files or output fewer than 10 files for a complex request, you will FAIL. ALWAYS aim for an exhaustive, production-ready architecture.
8. MANDATORY README.md Rules:
   - NEVER include fake git clone instructions or assume a git repository exists. Only document how to activate the venv and run the code.
   - ALWAYS explicitly mention what the AI actually built (the features, the system).
   - ALWAYS explain exactly how to use it (the commands, the inputs).
   - ALWAYS explain any terminology used in the system interface (e.g., if there's a chat prompt, explain what "User:", "Bot:", "Agent:" means and what the user is expected to type).
9. MANDATORY: Be explicitly precise about function signatures and required positional arguments in the Architecture and Descriptions so the coder knows exactly how to wire components together!
10. MANDATORY: Explicitly instruct the coder to NEVER use hardcoded placeholder values or dummy data in the final integration (e.g. main.py). The system MUST be wired up dynamically using actual user inputs or API responses.
11. MANDATORY: ALWAYS include a step to generate a `requirements.txt` file listing all third-party dependencies.
12. CRITICAL: DO NOT output conversational preamble like 'Here is your plan'. You MUST start your response directly with `# [Project Title]`.

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
STEP N: Create requirements.txt
FILE: requirements.txt
DEPENDS: [all relevant steps]
DESCRIPTION:
Output a plain text list of pip packages required (one per line, e.g. requests==2.31.0). DO NOT WRITE A PYTHON SCRIPT. JUST THE PACKAGE NAMES.

---
STEP N+1: Create README.md
FILE: README.md
DEPENDS: [all previous steps]
DESCRIPTION:
Create comprehensive documentation. Include: project description, how to activate venv, how to install dependencies from requirements.txt, how to run, all features built, usage examples, and any manual setup required.

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

    FIXER_SYSTEM_PROMPT = """You are an autonomous Python debugging agent. You are given:
1. The error traceback
2. The project's File Registry (showing all existing files and their APIs)
3. A History of previously attempted fixes (to prevent you from repeating mistakes)

Your job: Explore the codebase, find the bug, and fix it using XML tools.

AVAILABLE TOOLS:
You can use the following XML tags to interact with the system. You can use multiple tools in a single response.

1. `<view_file>path/to/file.py</view_file>`
Use this to read the contents of any file in the workspace. The system will reply with the file contents.

2. `<edit_file path="path/to/file.py">`
Use this to apply precise SEARCH/REPLACE blocks.
Format inside the tag:
<<<<<<< SEARCH
[exact lines to replace]
=======
[new lines]
>>>>>>> REPLACE
`</edit_file>`

3. `<run_command>`
Use this to run terminal commands (e.g., `pytest`, `python main.py`, `pip install x`) securely within the project sandbox to verify your fixes. 
Format inside the tag: `<run_command>pytest test_api.py</run_command>`. The system will reply with stdout/stderr.

4. `<done>`
Use this when you believe the bug is fixed and you want the system to test the code.

CRITICAL RULES:
1. NEVER guess! If you see an error in `main.py` calling `src/utils.py`, use `<view_file>src/utils.py</view_file>` to see the actual function signature before trying to fix it.
2. If `<edit_file>` fails due to a bad SEARCH block, try again or use the fallback: `<edit_file path="..." fallback="true"> [Full file contents] </edit_file>`.
3. Only use `<done>` when you have actually made edits using `<edit_file>`.

EXAMPLE WORKFLOW:
<view_file>src/main.py</view_file>
<view_file>src/config.py</view_file>
... (System returns file contents) ...
<edit_file path="src/main.py">
<<<<<<< SEARCH
from src.config import get_cfg
=======
from src.config import Config
>>>>>>> REPLACE
</edit_file>
<done>
"""

    SUMMARY_SYSTEM_PROMPT = """Summarize what this code file does in ONE concrete sentence.
Include: file path, class names, function names, and what they do.
Be SPECIFIC — use actual names from the code, not generic descriptions.

WRONG: "Implements a calculator module"
RIGHT: "src/calculator.py defines class Calculator with methods add(a,b), subtract(a,b), multiply(a,b), divide(a,b) that perform basic arithmetic operations"

Output ONLY the one-sentence summary, nothing else."""

    def __init__(self, state: ProjectState):
        self.state = state
        self.knowledge = ""
        self.custom_rules = ""
        self.brain = None
        
        try:
            from core.brain.project_brain import ProjectBrain
            self.brain = ProjectBrain(config.PROJECT_ROOT)
        except Exception as e:
            log.warning("Failed to initialize ProjectBrain: %s", e)
            
        try:
            # Load OKF Markdown files
            knowledge_dir = config.PROJECT_ROOT / ".agent_brain" / "knowledge"
            if knowledge_dir.exists():
                okf_texts = []
                for md_file in knowledge_dir.glob("*.md"):
                    content = md_file.read_text(encoding="utf-8").strip()
                    if content:
                        okf_texts.append(f"--- Rule from {md_file.name} ---\n{content}\n")
                
                if okf_texts:
                    self.custom_rules = "\n\n=== STRICT PROJECT RULES (OKF) ===\nYou MUST follow these rules exactly on every request:\n\n" + "\n".join(okf_texts) + "\n====================================\n"
        except Exception as e:
            log.warning("Failed to load OKF knowledge base: %s", e)

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
        
        # Phase 3: Use Graphifyy/Neo4j graph to filter registry if possible
        if self.brain and getattr(self.brain, "graph", None) and self.brain.graph.is_available:
            try:
                # Query Neo4j for files connected to this step's file
                query = f"""
                MATCH (f:File)-[*1..2]-(other_f:File)
                WHERE f.path CONTAINS '{Path(step.file_path).name}'
                RETURN DISTINCT other_f.path AS related_file
                LIMIT 15
                """
                records = self.brain.graph.execute_query(query)
                if records:
                    related_paths = [r["related_file"] for r in records]
                    filtered_registry = []
                    for entry in self.state.file_registry:
                        if entry.path == step.file_path or any(Path(p).name in entry.path for p in related_paths):
                            filtered_registry.append(entry.to_registry_string())
                    if filtered_registry:
                        registry_str = "FILE REGISTRY (Graph-Filtered):\n" + "=" * 45 + "\n" + "\n\n".join(filtered_registry)
                        log.info("Successfully filtered registry using Graphifyy Neo4j data.")
            except Exception as e:
                log.warning("Failed to filter registry using Graphifyy: %s", e)
        
        registry_tokens = LLMClient.count_tokens(registry_str)
        parts.append(registry_str)
        used += registry_tokens

        # 2. Current step description (PINNED)
        step_block = self._format_step_block(step)
        step_tokens = LLMClient.count_tokens(step_block)
        parts.append(step_block)
        used += step_tokens

        # 3. Architecture Blueprint (compressed if needed)
        arch = self.state.architecture_text
        if arch:
            arch_block = f"\n=== SYSTEM ARCHITECTURE BLUEPRINT ===\n{arch}\n=====================================\n"
            arch_tokens = LLMClient.count_tokens(arch_block)
            remaining_for_arch = budget - used - config.MIN_GENERATION_BUDGET - 1000 # Leave room for summaries
            if arch_tokens <= remaining_for_arch:
                parts.append(arch_block)
                used += arch_tokens
            elif remaining_for_arch > 500:
                truncated_arch = LLMClient.truncate_to_tokens(arch_block, remaining_for_arch)
                parts.append(truncated_arch)
                used += LLMClient.count_tokens(truncated_arch)

        # 4. Previous step summaries (compressed if needed)
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
        if self.custom_rules:
            system_prompt += self.custom_rules

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
        registry_str = self.state.get_file_registry_string()
        if self.brain and getattr(self.brain, "graph", None) and self.brain.graph.is_available:
            try:
                query = f"""
                MATCH (f:File)-[*1..2]-(other_f:File)
                WHERE f.path CONTAINS '{Path(file_path).name}'
                RETURN DISTINCT other_f.path AS related_file
                LIMIT 15
                """
                records = self.brain.graph.execute_query(query)
                if records:
                    related_paths = [r["related_file"] for r in records]
                    filtered_registry = []
                    for entry in self.state.file_registry:
                        if entry.path == file_path or any(Path(p).name in entry.path for p in related_paths):
                            filtered_registry.append(entry.to_registry_string())
                    if filtered_registry:
                        registry_str = "FILE REGISTRY (Graph-Filtered):\n" + "=" * 45 + "\n" + "\n\n".join(filtered_registry)
            except Exception as e:
                log.warning("Failed to filter registry for fixer using Graphifyy: %s", e)
                
        parts.append(registry_str)

        # The broken file
        parts.append(f"FILE WITH ERROR: {file_path}")
        parts.append(f"```\n{file_content}\n```")

        # The error
        parts.append(f"ERROR:\n{error_text}")

        # Fix History (Memory)
        if self.state.fix_history:
            history_lines = ["PREVIOUS FIXES ATTEMPTED IN THIS PROJECT (Do not repeat failed approaches):"]
            # Show the last 5 fixes
            for i, record in enumerate(self.state.fix_history[-5:]):
                history_lines.append(f"--- Attempt {i+1} ---")
                history_lines.append(f"Error was: {record.get('error_message', '')[:300]}")
                history_lines.append(f"Files changed: {', '.join(record.get('fixed_files', []))}")
                history_lines.append(f"Summary: {record.get('summary', '')}")
            parts.append("\n".join(history_lines))

        # Instruction
        parts.append(
            "Use the provided XML tags (<view_file>, <edit_file>, <done>) to explore the codebase and fix the error autonomously."
        )

        system_prompt = self.FIXER_SYSTEM_PROMPT
        if self.custom_rules:
            system_prompt += self.custom_rules

        return {
            "system": system_prompt,
            "prompt": "\n\n".join(parts),
        }

    def build_architect_prompt(self, user_prompt: str) -> dict:
        """Build the prompt for the Architecture generation phase."""
        system_prompt = self.ARCHITECT_SYSTEM_PROMPT + self.knowledge
        if self.custom_rules:
            system_prompt += self.custom_rules

        return {
            "system": system_prompt,
            "prompt": f"USER REQUEST:\n{user_prompt}\n\nOutput your hyper-detailed architectural design blueprint now.",
        }

    def build_planner_prompt(self, user_prompt: str, architecture_text: str) -> dict:
        """Build the prompt for plan generation."""
        prompt = f"""Create an EXTREMELY DETAILED implementation plan for the following project based on the Architectural Blueprint.

CRITICAL REMINDERS:
1. Start your response with `# [Project Title]` — NO preamble, NO thinking blocks, NO conversational text.
2. Step 1 MUST be main.py — completely empty except for `if __name__ == "__main__":` with `pass`. No imports.
3. All source files go in `src/`. Flat structure only (e.g., `src/math.py`, NOT `src/utils/math.py`).
4. Only ONE step for `main.py`. The system auto-updates it later.
5. Last step MUST be README.md.
6. Follow the EXACT format: `---` then `STEP N:` then `FILE:` then `DEPENDS:` then `DESCRIPTION:` each on separate lines.

USER REQUEST:
{user_prompt}

=== ARCHITECTURAL BLUEPRINT (TRANSLATE THIS INTO STEPS) ===
{architecture_text}
===========================================================

Output the `## Implementation Plan` with STEP/FILE/DEPENDS/DESCRIPTION blocks separated by `---`.
"""
        system_prompt = self.PLANNER_SYSTEM_PROMPT + self.knowledge
        if self.custom_rules:
            system_prompt += self.custom_rules

        return {
            "system": system_prompt,
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
3. IF it provides classes or functions, actually INTEGRATE it in the `if __name__ == "__main__"` block by wiring it up to the existing system.
4. IF the new module does NOT provide any classes or functions (e.g. it is just an empty script or entry point), DO NOT add any imports and DO NOT modify `main.py` except returning it exactly as it was.
5. Keep ALL existing imports and code — only ADD the new integration.
6. NO markdown, NO explanations. Output only raw Python code.
7. MANDATORY: Meticulously check the function signatures and class definitions of the new module. Ensure ALL required positional arguments are provided when you instantiate classes or call functions!
8. NEVER pass undefined variables as arguments. Always initialize necessary dependencies first.
9. CRITICAL RULE: NEVER use dummy data, placeholders, or hardcoded fake paths like `example.txt` or `Hello World`. You MUST use real relative paths inside the workspace, or dynamically generate data, or bind it properly to the actual application logic.
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
