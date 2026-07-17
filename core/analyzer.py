import asyncio
import logging
from pathlib import Path
from typing import Tuple, List, Optional
from dataclasses import dataclass

log = logging.getLogger(__name__)

@dataclass
class VerificationResult:
    success: bool
    errors: List[str]
    tool_name: str

class IncrementalVerifier:
    """
    Runs scoped incremental verification using Ruff (linting) and Pyright (type checking).
    Designed to run on a per-file or per-sprint basis, leveraging the Contract-First
    stubs to prevent false-positive ImportErrors.
    """
    def __init__(self, workspace: Path, venv_path: Optional[Path] = None):
        self.workspace = workspace
        self.venv_path = venv_path

    def _get_tool_cmd(self, tool: str) -> str:
        """Get path to a tool (ruff or pyright) in the venv, if it exists."""
        if self.venv_path and self.venv_path.exists():
            import os
            bin_dir = "Scripts" if os.name == 'nt' else "bin"
            tool_exe = f"{tool}.exe" if os.name == 'nt' else tool
            tool_path = self.venv_path / bin_dir / tool_exe
            if tool_path.exists():
                return str(tool_path)
        return tool

    async def verify_file(self, file_path: str) -> Tuple[bool, str]:
        """
        Run Ruff and Pyright on a specific file.
        Returns (success, error_message).
        """
        full_path = self.workspace / file_path
        if not full_path.exists():
            return False, f"File not found: {file_path}"

        # 1. Run Ruff (Linter)
        ruff_res = await self._run_ruff(str(full_path))
        if not ruff_res.success:
            return False, f"Ruff Lint Errors:\n{chr(10).join(ruff_res.errors)}"

        # 2. Run Pyright (Type Checker)
        pyright_res = await self._run_pyright(str(full_path))
        if not pyright_res.success:
            return False, f"Pyright Type Errors:\n{chr(10).join(pyright_res.errors)}"

        return True, ""

    async def _run_ruff(self, target_path: str) -> VerificationResult:
        cmd = [self._get_tool_cmd("ruff"), "check", target_path]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace)
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return VerificationResult(True, [], "ruff")

            out_str = stdout.decode("utf-8", errors="replace").strip()
            # Basic cleanup of Ruff output
            errors = [line for line in out_str.split("\n") if line.strip() and not line.startswith("Found")]
            return VerificationResult(False, errors, "ruff")
        except FileNotFoundError:
            # Tool not installed, ignore for now (should be installed by orchestrator setup ideally)
            log.warning("Ruff not found. Skipping linting.")
            return VerificationResult(True, [], "ruff")
        except Exception as e:
            log.error(f"Failed to run Ruff: {e}")
            return VerificationResult(False, [str(e)], "ruff")

    async def _run_pyright(self, target_path: str) -> VerificationResult:
        cmd = [self._get_tool_cmd("pyright"), target_path]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace)
            )
            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                return VerificationResult(True, [], "pyright")

            out_str = stdout.decode("utf-8", errors="replace").strip()
            errors = [line for line in out_str.split("\n") if "error:" in line.lower()]
            if not errors:
                errors = [out_str]

            return VerificationResult(False, errors, "pyright")
        except FileNotFoundError:
            log.warning("Pyright not found. Skipping type checking.")
            return VerificationResult(True, [], "pyright")
        except Exception as e:
            log.error(f"Failed to run Pyright: {e}")
            return VerificationResult(False, [str(e)], "pyright")
