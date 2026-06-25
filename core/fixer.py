"""
Fixer — debugging and auto-fix loop.

Analyzes execution and syntax errors, asks the LLM for a fix,
and applies it. Handles ModuleNotFoundErrors automatically.
Cross-platform compatible (Windows + Linux).
"""

from __future__ import annotations
import difflib
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


def _strip_comments(text: str) -> str:
    """Strip inline Python comments from each line for fuzzy comparison."""
    lines = []
    for line in text.splitlines():
        # Remove inline comments but keep strings intact (simple heuristic)
        stripped = re.sub(r'#[^"\']*$', '', line).rstrip()
        lines.append(stripped)
    return "\n".join(lines)


def _fuzzy_find_in_content(search_text: str, content: str, threshold: float = 0.75) -> Optional[tuple]:
    """
    Find the best fuzzy match for search_text within content.
    
    Returns (start_idx, end_idx) of the best match in content, or None if
    no match exceeds the threshold.
    """
    search_lines = search_text.splitlines()
    content_lines = content.splitlines()
    search_len = len(search_lines)
    
    if search_len == 0 or len(content_lines) == 0:
        return None
    
    best_ratio = 0.0
    best_start = -1
    
    # Slide a window of search_len lines over the content
    for i in range(len(content_lines) - search_len + 1):
        window = "\n".join(content_lines[i:i + search_len])
        ratio = difflib.SequenceMatcher(None, search_text, window).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_start = i
    
    if best_ratio >= threshold and best_start >= 0:
        # Reconstruct the matched text from the actual content lines
        matched_text = "\n".join(content_lines[best_start:best_start + search_len])
        # Find the byte positions in the original content
        start_pos = len("\n".join(content_lines[:best_start]))
        if best_start > 0:
            start_pos += 1  # account for the joining newline
        end_pos = start_pos + len(matched_text)
        log.debug("Fuzzy match found (ratio=%.2f) at lines %d-%d", best_ratio, best_start, best_start + search_len)
        return (matched_text, best_ratio)
    
    return None


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
        on_thinking=None,
    ) -> Tuple[bool, str, list[str]]:
        """
        Attempt to fix a broken file (can optionally fix multiple files).

        Args:
            file_path: The file that caused the error (if known)
            error_text: The stderr output or traceback
            on_token: Optional callback for streaming content tokens
            on_thinking: Optional callback for streaming thinking tokens

        Returns:
            (success, message, list_of_modified_files)
        """
        parsed_error = ErrorParser.parse_traceback(error_text)

        # Determine which file to fix
        target_file = _normalize_path(file_path)
        if parsed_error["file"] and parsed_error["file"].endswith(".py"):
            trace_file = _normalize_path(parsed_error["file"])
            workspace_str = _normalize_path(str(self.workspace.resolve()))

            if workspace_str in trace_file:
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

        # 4. Agentic Loop with retry tracking
        max_iterations = 5
        current_prompt = ctx["prompt"]
        system_prompt = ctx["system"]
        fixed_files_list = []
        brief_plan = "Fixed bugs."
        # Track SEARCH/REPLACE failures per file to escalate to full rewrite
        search_fail_counts = {}
        MAX_SEARCH_FAILURES = 3
        
        for iteration in range(max_iterations):
            log.info("Fixer: agent loop iteration %d/%d", iteration + 1, max_iterations)
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
                return False, f"LLM Generation Error: {str(e)}", []
                
            raw_output = "".join(chunks)
            if not raw_output.strip():
                return False, "LLM returned empty output", []
                
            # Extract think block for summary (legacy format — still useful if /api/generate)
            think_match = re.search(r'<think>(.*?)</think>', raw_output, re.DOTALL | re.IGNORECASE)
            think_alt_match = re.search(r'Thinking\.\.\.(.*?)\.\.\.done thinking\.', raw_output, re.DOTALL | re.IGNORECASE)
            if think_match:
                think_text = think_match.group(1).strip()
                brief_plan = think_text[-150:].replace('\n', ' ').strip()
            elif think_alt_match:
                think_text = think_alt_match.group(1).strip()
                brief_plan = think_text[-150:].replace('\n', ' ').strip()

            # Append assistant's response to prompt history
            current_prompt += f"\n\nASSISTANT:\n{raw_output}\n\n"
            
            # Check for <view_file> tags
            has_view_file = False
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
                has_view_file = True
                
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
                    if "<done>" in raw_output.lower():
                        break
                        
                    if has_view_file:
                        log.info("Fixer: agent requested to view files, continuing loop")
                        continue
                    
                    current_prompt += "SYSTEM:\nYou did not use <view_file>, <edit_file>, or <done>. Please output valid XML tags to proceed.\n\n"
                    log.info("Fixer: agent outputted invalid tags, looping back")
                    continue
                    
            # Apply all fixes with fuzzy matching and retry tracking
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
                        log.info("Fixer: full file rewrite applied for %s", fpath)
                        continue
                    
                    # === Multi-level matching strategy ===
                    matched = False
                    
                    # Level 1: Exact match
                    if search_text in content:
                        content = content.replace(search_text, replace_text, 1)
                        matched = True
                        log.info("Fixer: exact SEARCH match in %s", fpath)
                    
                    # Level 2: Stripped whitespace match
                    if not matched and search_text.strip() in content:
                        content = content.replace(search_text.strip(), replace_text.strip(), 1)
                        matched = True
                        log.info("Fixer: stripped whitespace SEARCH match in %s", fpath)
                    
                    # Level 3: Comment-stripped match
                    if not matched:
                        stripped_search = _strip_comments(search_text)
                        stripped_content = _strip_comments(content)
                        if stripped_search.strip() in stripped_content:
                            # Find the matching region in the original content by line
                            search_lines_clean = stripped_search.strip().splitlines()
                            content_lines = content.splitlines()
                            content_lines_clean = stripped_content.splitlines()
                            
                            for idx in range(len(content_lines_clean) - len(search_lines_clean) + 1):
                                window = content_lines_clean[idx:idx + len(search_lines_clean)]
                                if "\n".join(window) == stripped_search.strip():
                                    # Replace original lines
                                    original_match = "\n".join(content_lines[idx:idx + len(search_lines_clean)])
                                    content = content.replace(original_match, replace_text, 1)
                                    matched = True
                                    log.info("Fixer: comment-stripped SEARCH match in %s (line %d)", fpath, idx)
                                    break
                    
                    # Level 4: Fuzzy match using difflib
                    if not matched:
                        fuzzy_result = _fuzzy_find_in_content(search_text, content)
                        if fuzzy_result:
                            actual_text, ratio = fuzzy_result
                            content = content.replace(actual_text, replace_text, 1)
                            matched = True
                            log.info("Fixer: fuzzy SEARCH match in %s (ratio=%.2f)", fpath, ratio)
                    
                    # If no match at any level — track failure
                    if not matched:
                        search_fail_counts[fpath] = search_fail_counts.get(fpath, 0) + 1
                        fail_count = search_fail_counts[fpath]
                        log.warning(
                            "Fixer: SEARCH/REPLACE failed for %s (failure %d/%d)",
                            fpath, fail_count, MAX_SEARCH_FAILURES
                        )
                        
                        if fail_count >= MAX_SEARCH_FAILURES:
                            # Escalate: demand full file rewrite
                            current_prompt += (
                                f"SYSTEM:\nSEARCH/REPLACE has failed {fail_count} times for {fpath}. "
                                f"The SEARCH blocks do not match the actual file content (comments or whitespace differ). "
                                f"You MUST now output the ENTIRE complete rewritten file for {fpath} inside a single ```python block. "
                                f"Do NOT use SEARCH/REPLACE anymore for this file. "
                                f"Use this format:\n"
                                f"# FILE: {fpath}\n"
                                f"```python\n"
                                f"[entire file content here]\n"
                                f"```\n\n"
                            )
                        else:
                            current_prompt += (
                                f"SYSTEM:\nCould not find SEARCH block in {fpath} "
                                f"(failure {fail_count}/{MAX_SEARCH_FAILURES}). "
                                f"The comments or whitespace in your SEARCH block don't match the actual file. "
                                f"Please use <view_file>{fpath}</view_file> to see the exact content, "
                                f"then retry with the exact text from the file.\n\n"
                            )
                        edit_success = False
                        break

                if edit_success:
                    # Save fixed file
                    full_fpath.write_text(content, encoding="utf-8")
                    log.info("Fixer: applied edit to %s", fpath)
                    if fpath not in fixed_files_list:
                        fixed_files_list.append(fpath)
                        
                    current_prompt += f"SYSTEM:\nSuccessfully applied edits to {fpath}.\n\n"
                    
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
                continue
                
            # If edits succeeded and it output <done>, break
            if "<done>" in raw_output.lower():
                break
            else:
                log.info("Fixer: edits succeeded but no <done> found, looping back")
                continue
                
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
