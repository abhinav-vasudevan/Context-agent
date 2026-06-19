"""
Fixer — debugging and auto-fix loop.

Analyzes execution and syntax errors, asks the LLM for a fix,
and applies it. Handles ModuleNotFoundErrors automatically.
Cross-platform compatible (Windows + Linux).
"""

from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional, Tuple

import config
from core.llm_client import LLMClient
from core.context import ContextAssembler, FileRegistryBuilder
from core.runner import Runner, ErrorParser
from core.coder import Coder
from models.state import ProjectState

log = logging.getLogger(__name__)


def _normalize_path(p: str) -> str:
    """Normalize path separators to forward slashes for cross-platform consistency."""
    return p.replace("\\", "/")


class Fixer:
    """Analyzes errors and generates fixes."""

    def __init__(
        self,
        llm: LLMClient,
        state: ProjectState,
        workspace: Path,
        runner: Runner,
        coder: Coder,
    ):
        self.llm = llm
        self.state = state
        self.workspace = workspace
        self.runner = runner
        self.coder = coder
        self.assembler = ContextAssembler(state)

    async def fix_error(
        self,
        file_path: str,
        error_text: str,
        on_token=None,
    ) -> Tuple[bool, str]:
        """
        Attempt to fix a broken file.

        Args:
            file_path: The file that caused the error (if known)
            error_text: The stderr output or traceback
            on_token: Optional callback for streaming tokens

        Returns:
            (success, message)
        """
        parsed_error = ErrorParser.parse_traceback(error_text)

        # Determine which file to fix
        target_file = _normalize_path(file_path)
        if parsed_error["file"] and parsed_error["file"].endswith(".py"):
            # The traceback might point to absolute path or workspace path
            # Normalize all paths for cross-platform comparison
            trace_file = _normalize_path(parsed_error["file"])
            workspace_str = _normalize_path(str(self.workspace.resolve()))

            if workspace_str in trace_file:
                # Extract relative path from absolute traceback path
                target_file = trace_file.split(workspace_str)[-1].lstrip("/")
            elif "src/" in trace_file:
                target_file = "src/" + trace_file.split("src/")[-1]
            elif trace_file.endswith("main.py"):
                target_file = "main.py"

        full_target = self.workspace / target_file

        log.info("Fixer: analyzing error in %s", target_file)

        # 1. Handle ModuleNotFoundError automatically
        if parsed_error["is_import_error"] and parsed_error["missing_module"]:
            missing = parsed_error["missing_module"]
            # Ignore internal modules
            if missing == "src" or missing.startswith("src.") or missing.startswith("src/"):
                log.info("Fixer: ignoring missing internal module '%s'", missing)
                return False, f"Cannot auto-install internal module '{missing}'. Does the file exist yet?"
            else:
                log.info("Fixer: auto-installing missing module: %s", missing)
                return await self._auto_install_module(missing)

        # 2. Get the current file content
        if not full_target.exists():
            return False, f"Cannot fix: file {target_file} does not exist"

        current_content = full_target.read_text(encoding="utf-8")

        # 3. Build prompt
        ctx = self.assembler.build_fixer_prompt(
            file_path=target_file,
            file_content=current_content,
            error_text=error_text,
        )

        # 4. Generate fix — filter out <think>/<brief_plan> blocks from UI stream
        chunks = []
        in_hidden_block = False
        stream_buffer = ""
        
        def filtered_on_token(token: str):
            nonlocal in_hidden_block, stream_buffer
            stream_buffer += token
            
            if not in_hidden_block:
                for tag in ("<think>", "<brief_plan>"):
                    if tag in stream_buffer:
                        in_hidden_block = True
                        pre_tag = stream_buffer.split(tag)[0]
                        if pre_tag and on_token:
                            on_token(pre_tag)
                        stream_buffer = stream_buffer.split(tag, 1)[1]
                        break
                else:
                    if len(stream_buffer) > 13:
                        safe_str = stream_buffer[:-13]
                        stream_buffer = stream_buffer[-13:]
                        if on_token:
                            on_token(safe_str)
                            
            if in_hidden_block:
                for tag in ("</think>", "</brief_plan>"):
                    if tag in stream_buffer:
                        in_hidden_block = False
                        stream_buffer = stream_buffer.split(tag, 1)[1]
                        break
        
        try:
            async for chunk in self.llm.generate_stream(
                prompt=ctx["prompt"],
                system=ctx["system"],
                on_token=filtered_on_token if on_token else None,
            ):
                chunks.append(chunk)
            
            # Flush remaining buffer
            if not in_hidden_block and stream_buffer and on_token:
                on_token(stream_buffer)
                
        except Exception as e:
            return False, f"LLM Generation Error: {str(e)}"

        raw_output = "".join(chunks)

        if not raw_output.strip():
            return False, "LLM returned empty output"

        # 5. Extract and apply fixed code
        fixed_code = self.coder._extract_code(raw_output, target_file)

        if len(fixed_code) < 10:
            return False, "LLM failed to generate a valid fix"

        # Safety Check: Prevent overwriting with a truncated diff/snippet
        if "# ..." in fixed_code or "# existing" in fixed_code.lower() or "# ... existing" in fixed_code.lower():
            return False, "LLM returned a placeholder snippet instead of the full file. You MUST output the ENTIRE file without using '# ...' placeholders."

        if len(fixed_code) < len(current_content) * 0.4 and len(current_content) > 200:
            return False, "LLM returned a truncated file. You MUST output the ENTIRE file contents, not just a partial snippet."

        # Save fixed file
        full_target.write_text(fixed_code, encoding="utf-8")
        log.info("Fixer: applied fix to %s", target_file)

        # 6. Syntax check the fix immediately
        syntax_result = await self.runner.syntax_check(target_file)
        if not syntax_result.success:
            log.warning("Fixer: fix introduced a syntax error: %s", syntax_result.error)
            return False, f"Fix introduced Syntax Error:\n{syntax_result.error}"

        # 7. Update registry
        entry = FileRegistryBuilder.parse_file(full_target, target_file)
        if entry:
            self.coder._update_registry(entry)

        return True, f"Successfully applied fix to {target_file}"

    async def _auto_install_module(self, module_name: str) -> Tuple[bool, str]:
        """Automatically pip install a missing module."""
        # Simple heuristic mapping (e.g. cv2 -> opencv-python)
        pkg_map = {
            "cv2": "opencv-python",
            "bs4": "beautifulsoup4",
            "PIL": "Pillow",
            "yaml": "PyYAML",
            "dotenv": "python-dotenv",
            "sklearn": "scikit-learn",
            "jwt": "PyJWT",
            "serial": "pyserial",
            "usb": "pyusb",
            "gi": "PyGObject",
        }

        # Extract the base package name (e.g., from.module import X -> from)
        base_module = module_name.split(".")[0]
        pip_package = pkg_map.get(base_module, base_module)

        result = await self.runner.install_package(pip_package)

        if result.success:
            return True, f"Auto-installed missing dependency: {pip_package}"
        else:
            return False, f"Failed to auto-install {pip_package}:\n{result.error}"
