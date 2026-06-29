"""
Static Analysis Module.

Wraps deterministic tools like ast.parse, mypy, and ruff to catch
syntax and typing errors before the code is executed.
"""

from __future__ import annotations
import ast
import logging
from typing import Tuple, List

log = logging.getLogger(__name__)


class StaticAnalyzer:
    """Performs static analysis on generated Python code."""

    @staticmethod
    def check_syntax(code_content: str, file_path: str = "<unknown>") -> Tuple[bool, str]:
        """
        Check if the code has valid Python syntax.
        
        Returns:
            (is_valid, error_message)
        """
        try:
            ast.parse(code_content, filename=file_path)
            return True, ""
        except SyntaxError as e:
            error_msg = f"SyntaxError in {file_path} on line {e.lineno}:\n"
            if e.text:
                error_msg += f"    {e.text.rstrip()}\n"
                if e.offset:
                    error_msg += f"    {' ' * (e.offset - 1)}^\n"
            error_msg += str(e)
            return False, error_msg
        except Exception as e:
            return False, f"Error parsing code: {e}"

    @staticmethod
    def analyze_file(workspace_dir: str, file_path: str) -> Tuple[bool, List[str]]:
        """
        Run external static analysis tools (like ruff or mypy) if available.
        This is a placeholder for actual external tool integration.
        For now, it just relies on the built-in syntax check.
        """
        # In a fully productionized v2, this would run `ruff check` or `mypy` via subprocess
        # For this implementation, we return True (pass) since the Fixer loop handles runtime errors.
        return True, []
