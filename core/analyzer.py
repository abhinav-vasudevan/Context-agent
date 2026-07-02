import json
import logging
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Tuple
from core.runner import Runner, RunResult

log = logging.getLogger(__name__)

class StaticAnalyzer:
    """
    Runs deep semantic static analysis tools (Ruff, Pyright, Semgrep) 
    and parses their JSON output for the Fixer agent.
    """
    
    def __init__(self, runner: Runner):
        self.runner = runner
        self.workspace = runner.workspace

    async def install_tools(self) -> bool:
        """Install the required analysis tools into the project venv."""
        log.info("Analyzer: Installing ruff, pyright, and semgrep...")
        result = await self.runner.run_shell_command("pip install ruff pyright semgrep", timeout=300)
        return result.success

    async def run_ruff(self) -> List[Dict[str, Any]]:
        """Run Ruff to catch syntax and linting errors."""
        log.info("Analyzer: Running Ruff...")
        # Ruff outputs JSON format. We ignore exit code since 1 means errors found.
        result = await self.runner.run_shell_command("ruff check . --output-format json", timeout=60)
        try:
            errors = json.loads(result.stdout)
            return errors if isinstance(errors, list) else []
        except json.JSONDecodeError:
            log.warning("Ruff output was not valid JSON. Stderr: %s", result.stderr)
            return []

    async def run_pyright(self) -> List[Dict[str, Any]]:
        """Run Pyright to catch deep semantic type and logic errors."""
        log.info("Analyzer: Running Pyright...")
        result = await self.runner.run_shell_command("pyright . --outputjson", timeout=120)
        try:
            data = json.loads(result.stdout)
            return data.get("generalDiagnostics", [])
        except json.JSONDecodeError:
            log.warning("Pyright output was not valid JSON. Stderr: %s", result.stderr)
            return []
            
    async def run_semgrep(self) -> List[Dict[str, Any]]:
        """Run Semgrep to catch security and complex AST patterns."""
        log.info("Analyzer: Running Semgrep...")
        # We can run without explicit rules, or use default rules. Semgrep --json.
        # But semgrep needs rules. `semgrep scan --config auto --json`
        result = await self.runner.run_shell_command("semgrep scan --config auto --no-git-ignore --exclude venv --exclude .venv --exclude '*.md' --exclude '*.txt' --exclude '*.json' --json", timeout=120)
        try:
            data = json.loads(result.stdout)
            return data.get("results", [])
        except json.JSONDecodeError:
            log.warning("Semgrep output was not valid JSON. Stderr: %s", result.stderr)
            return []

    def build_fix_prompt(self, ruff_errors: List[Dict], pyright_errors: List[Dict], semgrep_errors: List[Dict]) -> str:
        """Format the aggregated JSON errors into a clean prompt string for the Fixer."""
        lines = []
        
        if ruff_errors:
            lines.append("### Ruff Linting & Syntax Errors:")
            for err in ruff_errors:
                file_path = err.get("location", {}).get("row", "unknown")
                filename = err.get("filename", "unknown")
                msg = err.get("message", "Unknown error")
                lines.append(f"- File `{filename}`, Line {file_path}: {msg}")
                
        if pyright_errors:
            lines.append("\n### Pyright Semantic Type Errors:")
            for err in pyright_errors:
                filename = err.get("file", "unknown")
                # Pyright gives a range, we grab the start line (0-indexed usually, so +1)
                line = err.get("range", {}).get("start", {}).get("line", 0) + 1
                msg = err.get("message", "Unknown error")
                lines.append(f"- File `{filename}`, Line {line}: {msg}")
                
        if semgrep_errors:
            lines.append("\n### Semgrep Security & Logic Errors:")
            for err in semgrep_errors:
                filename = err.get("path", "unknown")
                line = err.get("start", {}).get("line", "unknown")
                msg = err.get("extra", {}).get("message", "Unknown error")
                lines.append(f"- File `{filename}`, Line {line}: {msg}")
                
        return "\n".join(lines)
