"""
Coder — handles code generation and updates the File Registry.

Takes a step from the plan, asks the LLM to write the code, extracts
the raw code, saves it to the workspace, and updates the File Registry.
"""

from __future__ import annotations
import logging
import re
from pathlib import Path
from typing import Optional, Tuple

from core.llm_client import LLMClient
from core.context import ContextAssembler, FileRegistryBuilder
from core.runner import Runner
from models.state import ProjectState, PlanStep, FileEntry

log = logging.getLogger(__name__)


class Coder:
    """Generates code and manages file state."""

    def __init__(self, llm: LLMClient, state: ProjectState, workspace: Path):
        self.llm = llm
        self.state = state
        self.workspace = workspace
        self.assembler = ContextAssembler(state)
        # Temporary runner just for syntax checking
        self._syntax_runner = Runner(workspace)

    async def generate_code_v2(
        self,
        step: PlanStep,
        context_text: str,
        on_token=None,
        on_thinking=None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Generate code for a single plan step using V2 context.
        
        Args:
            step: The PlanStep to execute
            context_text: The focused context built by ContextEngine
            on_token: Optional callback for streaming content tokens
            on_thinking: Optional callback for streaming thinking tokens
            
        Returns:
            (success, error_message)
        """
        log.info("Coder: generating code for step %d (%s) using V2 context", step.step_number, step.file_path)

        system_prompt = "You are an elite Software Engineer. You must output the entire file content. Never use placeholders like '# ...'."
        prompt = f"TASK:\n{step.description}\n\nFILE PATH:\n{step.file_path}\n\nCONTEXT:\n{context_text}\n\nWrite the complete, runnable Python code now."

        chunks = []
        try:
            async for chunk in self.llm.generate_stream(
                prompt=prompt,
                system=system_prompt,
                on_token=on_token,
                on_thinking=on_thinking,
            ):
                chunks.append(chunk)
        except Exception as e:
            return False, f"LLM Generation Error: {str(e)}"

        raw_output = "".join(chunks)
        
        if not raw_output.strip():
            return False, "LLM returned empty output"

        code = self._extract_code(raw_output, step.file_path)

        if "# ..." in code or "# existing" in code.lower() or "# ... existing" in code.lower():
            return False, "LLM returned a placeholder snippet. You MUST output the ENTIRE file without using '# ...' placeholders."

        file_path = self.workspace / step.file_path
        
        if not step.file_path or step.file_path.endswith("/") or file_path.is_dir() or file_path == self.workspace:
            file_path.mkdir(parents=True, exist_ok=True)
            step.summary = f"Created directory {step.file_path}"
            return True, None
            
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")
        
        log.info("Coder: saved file %s (%d bytes)", step.file_path, len(code))

        if step.file_path.endswith(".py"):
            syntax_result = await self._syntax_runner.syntax_check(step.file_path)
            if not syntax_result.success:
                log.warning("Coder: Syntax error in generated code: %s", syntax_result.error)
                return False, f"Syntax Error:\n{syntax_result.error}"

        return True, None

    async def generate_code(
        self,
        step: PlanStep,
        on_token=None,
        on_thinking=None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Generate code for a single plan step.
        
        Args:
            step: The PlanStep to execute
            on_token: Optional callback for streaming content tokens
            on_thinking: Optional callback for streaming thinking tokens
            
        Returns:
            (success, error_message)
        """
        log.info("Coder: generating code for step %d (%s)", step.step_number, step.file_path)

        # 1. Build prompt
        ctx = self.assembler.build_coder_prompt(step)

        # 2. Call LLM
        chunks = []
        try:
            async for chunk in self.llm.generate_stream(
                prompt=ctx["prompt"],
                system=ctx["system"],
                on_token=on_token,
                on_thinking=on_thinking,
            ):
                chunks.append(chunk)
                
        except Exception as e:
            return False, f"LLM Generation Error: {str(e)}"

        raw_output = "".join(chunks)
        
        if not raw_output.strip():
            return False, "LLM returned empty output"

        # 3. Extract clean code
        code = self._extract_code(raw_output, step.file_path)

        # Safety Check: Prevent generating truncated placeholder snippets
        if "# ..." in code or "# existing" in code.lower() or "# ... existing" in code.lower():
            return False, "LLM returned a placeholder snippet. You MUST output the ENTIRE file without using '# ...' placeholders."

        # 4. Save to workspace
        file_path = self.workspace / step.file_path
        
        # If the planner mistakenly created a step for a directory instead of a file
        if not step.file_path or step.file_path.endswith("/") or file_path.is_dir() or file_path == self.workspace:
            file_path.mkdir(parents=True, exist_ok=True)
            step.summary = f"Created directory {step.file_path}"
            return True, None
            
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(code, encoding="utf-8")
        
        log.info("Coder: saved file %s (%d bytes)", step.file_path, len(code))

        # 5. Syntax check immediately (only for python files)
        if step.file_path.endswith(".py"):
            syntax_result = await self._syntax_runner.syntax_check(step.file_path)
            if not syntax_result.success:
                log.warning("Coder: Syntax error in generated code: %s", syntax_result.error)
                return False, f"Syntax Error:\n{syntax_result.error}"

        # 6. Parse and update File Registry
        entry = FileRegistryBuilder.parse_file(file_path, step.file_path)
        if entry:
            self._update_registry(entry)

        # 7. Generate a concrete summary
        summary = await self._generate_summary(step.file_path, code)
        step.summary = summary
        self.state.step_summaries.append(summary)

        return True, None

    async def update_main_integration(
        self,
        new_file_entry: FileEntry,
        on_token=None,
        on_thinking=None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Update main.py to import and use a newly created module.
        """
        main_path = self.workspace / "main.py"
        if not main_path.exists():
            return False, "main.py does not exist yet"

        if not new_file_entry.classes and not new_file_entry.functions:
            return True, "Skipped integration: module exports no classes or functions"

        current_main = main_path.read_text(encoding="utf-8")
        
        ctx = self.assembler.build_main_update_prompt(current_main, new_file_entry)

        chunks = []
        async for chunk in self.llm.generate_stream(
            prompt=ctx["prompt"],
            system=ctx["system"],
            on_token=on_token,
            on_thinking=on_thinking,
        ):
            chunks.append(chunk)

        raw_output = "".join(chunks)
        code = self._extract_code(raw_output, "main.py")

        # Basic safety check: if LLM returned nothing or something tiny, don't overwrite
        if len(code) < 10:
            return False, "LLM returned invalid main.py update"

        # Save updated main.py
        main_path.write_text(code, encoding="utf-8")
        
        # Syntax check
        syntax_result = await self._syntax_runner.syntax_check("main.py")
        if not syntax_result.success:
            # Revert main.py
            main_path.write_text(current_main, encoding="utf-8")
            return False, f"Syntax Error in updated main.py:\n{syntax_result.error}"

        # Update registry
        entry = FileRegistryBuilder.parse_file(main_path, "main.py")
        if entry:
            self._update_registry(entry)

        return True, None

    def _update_registry(self, new_entry: FileEntry):
        """Update or add a file entry in the project registry."""
        for i, existing in enumerate(self.state.file_registry):
            if existing.path == new_entry.path:
                self.state.file_registry[i] = new_entry
                return
        self.state.file_registry.append(new_entry)

    def _extract_code(self, raw_output: str, file_path: str = "") -> str:
        """
        Extract clean code from LLM output.
        Removes markdown fences and surrounding prose unless it's a markdown file.
        """
        # Strip <think> blocks if present, even if unclosed
        raw_output = re.sub(r'<think>.*?(?:</think>|\Z)', '', raw_output, flags=re.DOTALL | re.IGNORECASE).strip()
        # Also strip Ollama CLI format if the model natively outputs it
        raw_output = re.sub(r'Thinking\.\.\..*?(?:\.\.\.done thinking\.|\Z)', '', raw_output, flags=re.DOTALL | re.IGNORECASE).strip()

        if file_path.endswith(".md") or file_path.endswith(".txt"):
            match = re.search(r'^```(?:markdown|md|text)?\s*\n(.*?)(?:```|\Z)', raw_output.strip(), re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            return raw_output.strip()

        # Look for python code blocks with backticks (```python or ```). Allow unclosed blocks (EOF).
        blocks_backticks = re.findall(r'```(?:python|py)?\s*\n(.*?)(?:```|\Z)', raw_output, re.DOTALL | re.IGNORECASE)
        if blocks_backticks:
            return blocks_backticks[-1].strip()

        # Look for python code blocks with triple single quotes ('''python or python ''')
        blocks_quotes = re.findall(r"'''(?:python|py)?\s*\n(.*?)(?:'''|\Z)", raw_output, re.DOTALL | re.IGNORECASE)
        if not blocks_quotes:
            # Also catch `python '''` which Ollama sometimes does
            blocks_quotes = re.findall(r"(?:python|py)?\s*'''\s*\n(.*?)(?:'''|\Z)", raw_output, re.DOTALL | re.IGNORECASE)
            
        if blocks_quotes:
            return blocks_quotes[-1].strip()
            
        # Fallback: try generic code blocks without newlines (sometimes just ``` code ```)
        blocks_inline = re.findall(r'```(.*?)(?:```|\Z)', raw_output, re.DOTALL)
        if blocks_inline:
            return blocks_inline[-1].strip()
            
        # If no markdown blocks, check if the output starts with prose
        # A simple heuristic: if it doesn't look like code, we return it as is 
        # and hope the syntax checker catches it, prompting a fix
        
        # Strip simple conversational prefixes
        cleaned = re.sub(r'^(Here is|Below is|This is|The following is)[^\n]*\n+', '', raw_output, flags=re.IGNORECASE).strip()
        
        # Strip trailing conversational suffixes
        cleaned = re.sub(r'\n+(Let me know|This code|I have|Feel free)[^\n]*$', '', cleaned, flags=re.IGNORECASE).strip()
        
        # Final catch: If the LLM just printed `python` or `python '''` at the very beginning of the file
        cleaned = re.sub(r'^(?:python|py)?\s*(?:```|r?\'\'\'|r?""")?\s*\n', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n\s*(?:```|r?\'\'\'|r?""")?\s*$', '', cleaned)
        
        return cleaned

    async def _generate_summary(self, file_path: str, code: str) -> str:
        """Generate a concrete 1-sentence summary of the code."""
        ctx = self.assembler.build_summary_prompt(file_path, code)
        summary = await self.llm.generate(prompt=ctx["prompt"], system=ctx["system"])
        # Strip any <think> blocks that reasoning models inject
        summary = re.sub(r'<think>.*?</think>', '', summary, flags=re.DOTALL)
        summary = re.sub(r'<think>.*$', '', summary, flags=re.DOTALL)
        summary = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', summary, flags=re.DOTALL)
        summary = re.sub(r'Thinking\.\.\..*$', '', summary, flags=re.DOTALL)
        # Clean up any surrounding quotes or extra text
        return summary.strip(' \n"\'')
