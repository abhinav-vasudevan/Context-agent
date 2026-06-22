"""
Fixer — debugging and auto-fix loop.

Analyzes execution and syntax errors, asks the LLM for a fix,
and applies it. Handles ModuleNotFoundErrors automatically.
Cross-platform compatible (Windows + Linux).
"""

from __future__ import annotations
import logging
import re
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
    ) -> Tuple[bool, str, list[str]]:
        """
        Attempt to fix a broken file (can optionally fix multiple files).

        Args:
            file_path: The file that caused the error (if known)
            error_text: The stderr output or traceback
            on_token: Optional callback for streaming tokens

        Returns:
            (success, message, list_of_modified_files)
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
                return False, f"Cannot auto-install internal module '{missing}'. Does the file exist yet?", []
            else:
                log.info("Fixer: auto-installing missing module: %s", missing)
                success, msg = await self._auto_install_module(missing)
                return success, msg, []

        # 2. Get the current file content
        if not full_target.exists():
            return False, f"Cannot fix: file {target_file} does not exist", []

        current_content = full_target.read_text(encoding="utf-8")

        # 3. Build prompt
        ctx = self.assembler.build_fixer_prompt(
            file_path=target_file,
            file_content=current_content,
            error_text=error_text,
        )

        # 4. Agentic Loop
        max_iterations = 5
        current_prompt = ctx["prompt"]
        system_prompt = ctx["system"]
        fixed_files_list = []
        brief_plan = "Fixed bugs."
        
        for iteration in range(max_iterations):
            log.info("Fixer: agent loop iteration %d/%d", iteration + 1, max_iterations)
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
                    prompt=current_prompt,
                    system=system_prompt,
                    on_token=filtered_on_token if on_token else None,
                ):
                    chunks.append(chunk)
                
                if not in_hidden_block and stream_buffer and on_token:
                    on_token(stream_buffer)
            except Exception as e:
                return False, f"LLM Generation Error: {str(e)}", []
                
            raw_output = "".join(chunks)
            if not raw_output.strip():
                return False, "LLM returned empty output", []
                
            # Extract brief plan for the history summary
            plan_match = re.search(r'<brief_plan>(.*?)</brief_plan>', raw_output, re.DOTALL | re.IGNORECASE)
            if plan_match:
                brief_plan = plan_match.group(1).strip()

            # Append assistant's response to prompt history
            current_prompt += f"\n\nASSISTANT:\n{raw_output}\n\n"
            
            # Check for <view_file> tags
            view_matches = list(re.finditer(r'<view_file>\s*(.*?)\s*</view_file>', raw_output, re.IGNORECASE))
            if view_matches:
                system_reply = "SYSTEM:\n"
                for m in view_matches:
                    fpath = _normalize_path(m.group(1).strip())
                    if fpath.startswith("/"):
                        fpath = fpath.lstrip("/")
                    full_path = self.workspace / fpath
                    if full_path.exists():
                        system_reply += f"--- {fpath} ---\n```python\n{full_path.read_text(encoding='utf-8')}\n```\n\n"
                    else:
                        system_reply += f"--- {fpath} ---\nFILE NOT FOUND\n\n"
                
                current_prompt += system_reply
                log.info("Fixer: agent requested to view files, continuing loop")
                continue  # Loop back to let the LLM think again
                
            # Parse edit blocks (both new <edit_file> and legacy # FILE: format)
            file_edits = {}
            current_file = None
            state = "idle"  # idle, search, replace
            search_block = []
            replace_block = []

            lines = raw_output.splitlines()
            for line in lines:
                # Handle <edit_file path="..."> tag
                edit_match = re.match(r'<edit_file\s+path=["\']([^"\']+)["\'](?:[^>]*)>', line, re.IGNORECASE)
                if edit_match:
                    current_file = edit_match.group(1).strip()
                    if current_file not in file_edits:
                        file_edits[current_file] = []
                    state = "idle"
                    continue
                    
                # Handle legacy # FILE: format just in case
                if line.startswith("# FILE:"):
                    current_file = line.replace("# FILE:", "").strip().strip(' `\'"')
                    if current_file not in file_edits:
                        file_edits[current_file] = []
                    state = "idle"
                    continue
                
                if line.strip().lower() == "</edit_file>":
                    current_file = None
                    state = "idle"
                    continue
                
                if current_file:
                    if line.strip() == "<<<<<<< SEARCH":
                        state = "search"
                        search_block = []
                        continue
                    elif line.strip() == "=======":
                        state = "replace"
                        replace_block = []
                        continue
                    elif line.strip() == ">>>>>>> REPLACE":
                        if search_block or replace_block:
                            file_edits[current_file].append({
                                "search": "\n".join(search_block),
                                "replace": "\n".join(replace_block)
                            })
                        state = "idle"
                        continue
                    
                    if state == "search":
                        search_block.append(line)
                    elif state == "replace":
                        replace_block.append(line)

            # Fallback for full file replacements if LLM outputs full markdown blocks
            if not file_edits:
                pattern = r'#\s*FILE:\s*([^\n]+)\n.*?```(?:python|py)?\s*\n(.*?)(?:```|\Z)'
                matches = list(re.finditer(pattern, raw_output, re.DOTALL | re.IGNORECASE))
                if matches:
                    for match in matches:
                        path = match.group(1).strip(' `\'"')
                        code = match.group(2).strip()
                        file_edits[path] = [{"search": "FULL_FILE_REPLACE", "replace": code}]
                else:
                    # If there's no edit but there is a <done>, we just exit normally
                    if "<done>" in raw_output.lower():
                        break
                    
                    # If we reached here, no valid tool was called. Send error to agent.
                    current_prompt += "SYSTEM:\nYou did not use <view_file>, <edit_file>, or <done>. Please output valid XML tags to proceed.\n\n"
                    log.info("Fixer: agent outputted invalid tags, looping back")
                    continue
                    
            # Apply all fixes
            edit_success = True
            for fpath, edits in file_edits.items():
                fpath = _normalize_path(fpath)
                if fpath.startswith("/"):
                    fpath = fpath.lstrip("/")
                
                full_fpath = self.workspace / fpath
                if not full_fpath.exists():
                    current_prompt += f"SYSTEM:\nTarget file does not exist: {fpath}. Make sure the path is correct.\n\n"
                    edit_success = False
                    break
                
                content = full_fpath.read_text(encoding="utf-8")
                
                # Apply edits sequentially
                for i, edit in enumerate(edits):
                    search_text = edit["search"]
                    replace_text = edit["replace"]
                    
                    if search_text == "FULL_FILE_REPLACE":
                        content = replace_text
                    elif search_text not in content:
                        if search_text.strip() in content:
                            content = content.replace(search_text.strip(), replace_text.strip())
                        else:
                            current_prompt += f"SYSTEM:\nCould not find exact SEARCH block in {fpath}. Since SEARCH/REPLACE failed, on your next attempt, please output the ENTIRE rewritten file inside a ```python block as a fallback.\n\n"
                            edit_success = False
                            break
                    else:
                        content = content.replace(search_text, replace_text, 1)

                if edit_success:
                    # Save fixed file
                    full_fpath.write_text(content, encoding="utf-8")
                    log.info("Fixer: applied edit to %s", fpath)
                    if fpath not in fixed_files_list:
                        fixed_files_list.append(fpath)
                    
                    # Syntax check
                    if fpath.endswith(".py"):
                        syntax_result = await self.runner.syntax_check(fpath)
                        if not syntax_result.success:
                            current_prompt += f"SYSTEM:\nFix introduced Syntax Error in {fpath}:\n{syntax_result.error}\nPlease fix the syntax error.\n\n"
                            edit_success = False
                            break
                            
                    # Update registry
                    entry = FileRegistryBuilder.parse_file(full_fpath, fpath)
                    if entry:
                        self.coder._update_registry(entry)
                        
            if not edit_success:
                log.info("Fixer: edit failed or syntax error, looping back")
                continue # Loop back so LLM can fix its mistake
                
            # If edits succeeded and it output <done>, break
            if "<done>" in raw_output.lower():
                break
                
        # 8. Record in fix history
        self.state.fix_history.append({
            "error_message": error_text,
            "fixed_files": fixed_files_list,
            "summary": brief_plan
        })

        if not fixed_files_list:
            return False, "Agent loop completed without applying any successful edits.", []

        return True, f"Successfully applied fixes to: {', '.join(fixed_files_list)}", fixed_files_list

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
