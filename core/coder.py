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
        stub_content: Optional[str] = None,
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

        system_prompt = "You are an elite Software Engineer. You must output the entire file content. Never use placeholders like '# ...' or '// ...'."
        
        prompt = f"TASK:\n{step.description}\n\nFILE PATH:\n{step.file_path}\n\nCONTEXT:\n{context_text}\n\n"
        
        if stub_content:
            prompt += f"EXISTING SKELETON:\n{stub_content}\n\n"
            prompt += "Implement the actual logic inside the provided skeleton. You MUST return the complete file."
        else:
            prompt += "Write the complete, runnable code for the requested file now."

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
        log.info("Coder: generating code for step %d (%s) via Agent Loop", step.step_number, step.file_path)

        ctx = self.assembler.build_coder_prompt(step)
        current_prompt = ctx["prompt"]
        system_prompt = ctx["system"]
        
        max_iterations = 5
        final_code = ""
        
        for iteration in range(max_iterations):
            log.info("Coder: loop iteration %d/%d", iteration + 1, max_iterations)
            chunks = []
            try:
                async for chunk in self.llm.generate_stream(
                    prompt=current_prompt,
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

            current_prompt += f"\n\nASSISTANT:\n{raw_output}\n\n"
            system_reply = "SYSTEM:\n"
            action_taken = False
            
            # Check for <write_file>
            write_matches = list(re.finditer(r'<write_file\s+path=["\']([^"\']+)["\']>(.*?)</write_file>', raw_output, re.IGNORECASE | re.DOTALL))
            for m in write_matches:
                fpath = m.group(1).strip()
                code = m.group(2).strip()
                full_path = self.workspace / fpath
                
                if not self._syntax_runner.security.is_within_workspace(full_path, self.workspace):
                    system_reply += f"--- SECURITY BLOCKED: Path traversal attempt to {fpath} ---\n"
                    action_taken = True
                    continue
                    
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(code, encoding="utf-8")
                system_reply += f"--- Successfully wrote to {fpath} ---\n"
                action_taken = True
                final_code = code

            # Check for <edit_file>
            edit_matches = list(re.finditer(r'<edit_file\s+path=["\']([^"\']+)["\']>(.*?)</edit_file>', raw_output, re.IGNORECASE | re.DOTALL))
            for m in edit_matches:
                fpath = m.group(1).strip()
                edit_blocks = m.group(2)
                full_path = self.workspace / fpath
                
                if not self._syntax_runner.security.is_within_workspace(full_path, self.workspace):
                    system_reply += f"--- SECURITY BLOCKED: Path traversal attempt to {fpath} ---\n"
                    action_taken = True
                    continue
                
                if not full_path.exists():
                    system_reply += f"--- Edit Failed: {fpath} does not exist ---\n"
                    action_taken = True
                    continue
                    
                content = full_path.read_text(encoding="utf-8")
                blocks = re.findall(r'<<<<<<<\s*SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>>\s*REPLACE', edit_blocks, re.DOTALL)
                
                if not blocks:
                    system_reply += f"--- Edit Failed for {fpath}: No valid SEARCH/REPLACE blocks found ---\n"
                    action_taken = True
                    continue
                    
                success_count = 0
                for search_text, replace_text in blocks:
                    if search_text in content:
                        content = content.replace(search_text, replace_text)
                        success_count += 1
                    else:
                        system_reply += f"--- Edit Warning for {fpath}: Could not find exact SEARCH block. Make sure to copy the EXACT lines. ---\n"
                        
                if success_count > 0:
                    full_path.write_text(content, encoding="utf-8")
                    system_reply += f"--- Successfully edited {fpath} ({success_count}/{len(blocks)} blocks applied) ---\n"
                    final_code = content
                action_taken = True

            # Check for <run_command>
            run_matches = list(re.finditer(r'<run_command>\s*(.*?)\s*</run_command>', raw_output, re.IGNORECASE | re.DOTALL))
            for m in run_matches:
                cmd = m.group(1).strip()
                system_reply += f"--- Running: {cmd} ---\n"
                result = await self._syntax_runner.run_shell_command(cmd)
                if result.success:
                    system_reply += "SUCCESS\n"
                else:
                    system_reply += f"FAILED (Exit {result.exit_code})\n"
                if result.stdout:
                    system_reply += f"STDOUT:\n{result.stdout}\n"
                if result.stderr or result.error:
                    system_reply += f"STDERR/ERROR:\n{result.stderr or result.error}\n"
                system_reply += "\n"
                action_taken = True

            if "<done>" in raw_output.lower():
                break
                
            if not action_taken:
                system_reply += "You did not use <write_file>, <edit_file>, <run_command>, or <done>. Please output valid XML tags to proceed.\n"
                
            current_prompt += system_reply

        # Fallback if no file was written
        if not final_code:
            final_code = self._extract_code(raw_output, step.file_path)
            if final_code:
                file_path = self.workspace / step.file_path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(final_code, encoding="utf-8")

        if not final_code:
            return False, "Failed to generate any valid code or write_file."

        # Parse and update File Registry
        file_path = self.workspace / step.file_path
        entry = FileRegistryBuilder.parse_file(file_path, step.file_path)
        if entry:
            self._update_registry(entry)

        # Generate summary
        summary = await self._generate_summary(step.file_path, final_code)
        step.summary = summary
        self.state.step_summaries.append(summary)

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
            match = re.search(r'^```(?:markdown|md|text)?\s*\n(.*?)(?:\n\s*```|\Z)', raw_output.strip(), re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1).strip()
            return raw_output.strip()

        # Look for code blocks with backticks (```python, ```javascript, ```jsx, etc). Allow unclosed blocks (EOF).
        lang_hint = self._get_lang_hint(file_path)
        if lang_hint:
            lang_blocks = re.findall(r'```' + lang_hint + r'\s*\n(.*?)(?:\n\s*```|\Z)', raw_output, re.DOTALL | re.IGNORECASE)
            if lang_blocks:
                return lang_blocks[-1].strip()
        # Generic: match any fenced code block
        blocks_backticks = re.findall(r'```(?:python|py|javascript|js|jsx|typescript|ts|tsx|css|html|json|sh|bash)?\s*\n(.*?)(?:\n\s*```|\Z)', raw_output, re.DOTALL | re.IGNORECASE)
        if blocks_backticks:
            return blocks_backticks[-1].strip()

        # Look for python code blocks with triple single quotes ('''python or python ''')
        blocks_quotes = re.findall(r"'''(?:python|py)?\s*\n(.*?)(?:\n\s*'''|\Z)", raw_output, re.DOTALL | re.IGNORECASE)
        if not blocks_quotes:
            # Also catch `python '''` which Ollama sometimes does
            blocks_quotes = re.findall(r"(?:python|py)?\s*'''\s*\n(.*?)(?:\n\s*'''|\Z)", raw_output, re.DOTALL | re.IGNORECASE)
            
        if blocks_quotes:
            return blocks_quotes[-1].strip()
            
        # Fallback: try generic code blocks without newlines (sometimes just ``` code ```)
        blocks_inline = re.findall(r'```(.*?)(?:\n\s*```|```|\Z)', raw_output, re.DOTALL)
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

    @staticmethod
    def _get_lang_hint(file_path: str) -> str:
        """Return the markdown fence language hint for a file extension."""
        ext_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'jsx',
            '.ts': 'typescript',
            '.tsx': 'tsx',
            '.css': 'css',
            '.html': 'html',
            '.json': 'json',
            '.sh': 'bash',
        }
        for ext, lang in ext_map.items():
            if file_path.endswith(ext):
                return lang
        return ''

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
