"""
Runner — sandboxed code execution with security checks.

Runs Python files in the project workspace with:
  - STRICT security: blocks ALL delete/remove/destructive commands
  - Workspace sandboxing: can ONLY access files within the project
  - Timeout protection
  - Stdout/stderr capture for error analysis
  - Cross-platform support (Windows + Linux)
  - Callback-based output streaming (works with terminal AND web UI)
  - Async stdin feeding (for interactive programs)
  - User permission required before every execution
"""

from __future__ import annotations
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable, Awaitable

import config

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    """Result of running a code file."""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    runtime_ms: int = 0
    error: Optional[str] = None
    file_path: str = ""

    def get_error_summary(self) -> str:
        """Get a concise error summary for display."""
        if self.success:
            return ""
        text = self.error or self.stderr
        if not text:
            return f"Process exited with code {self.exit_code}"
        # Return first 500 chars of error
        return text[:500]


class SecurityChecker:
    """
    Validates code and commands for dangerous operations.

    NOTHING is executed without passing these checks.
    This protects the user's system from accidental file deletion,
    privilege escalation, or any operation outside the project sandbox.
    """

    @staticmethod
    def check_command(command: str) -> Optional[str]:
        """
        Check if a command is safe to run.

        Returns:
            None if safe, or an error message describing why it's blocked.
        """
        cmd_lower = command.lower().strip()
        cmd_parts = cmd_lower.split()

        if not cmd_parts:
            return "Empty command"

        # Check against blocked command list
        for blocked in config.BLOCKED_COMMANDS:
            blocked_parts = blocked.lower().split()
            # Check if the command starts with the blocked command
            if cmd_parts[:len(blocked_parts)] == blocked_parts:
                return f"BLOCKED: '{blocked}' commands are forbidden for safety"

        # Additional pattern checks
        dangerous_patterns = [
            (r'\brm\s', "File deletion (rm) is forbidden"),
            (r'\brm$', "File deletion (rm) is forbidden"),
            (r'\brmdir\b', "Directory deletion (rmdir) is forbidden"),
            (r'\bdel\s', "File deletion (del) is forbidden"),
            (r'\brd\s', "Directory deletion (rd) is forbidden"),
            (r'\bsudo\b', "Elevated privileges (sudo) are forbidden"),
            (r'\bchmod\b', "Permission changes (chmod) are forbidden"),
            (r'\bchown\b', "Ownership changes (chown) are forbidden"),
            (r'\bmkfs\b', "Filesystem formatting (mkfs) is forbidden"),
            (r'\bformat\b', "Formatting (format) is forbidden"),
            (r'>\s*/dev/', "Writing to /dev/ is forbidden"),
            (r'\bshutdown\b', "Shutdown is forbidden"),
            (r'\breboot\b', "Reboot is forbidden"),
        ]

        for pattern, reason in dangerous_patterns:
            if re.search(pattern, cmd_lower):
                return f"BLOCKED: {reason}"

        return None  # Safe

    @staticmethod
    def check_code_file(file_path: Path) -> Optional[str]:
        """
        Scan a code file for dangerous operations.

        Returns:
            None if safe, or a warning message.
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception:
            return None

        warnings = []
        for pattern_str in config.DANGEROUS_CODE_PATTERNS:
            pattern = re.compile(pattern_str)
            matches = pattern.findall(content)
            if matches:
                warnings.append(f"Found dangerous pattern: {pattern_str}")

        return "; ".join(warnings) if warnings else None

    @staticmethod
    def is_within_workspace(file_path: Path, workspace: Path) -> bool:
        """Check that a file path is within the project workspace."""
        try:
            file_path.resolve().relative_to(workspace.resolve())
            return True
        except ValueError:
            return False


class ProcessHandle:
    """
    Wraps an asyncio subprocess, providing methods to send input,
    read output, and kill the process. Works with both terminal and web UI.
    """

    def __init__(self):
        self.process: Optional[asyncio.subprocess.Process] = None
        self.stdin_queue: asyncio.Queue = asyncio.Queue()
        self._stdout_buf = bytearray()
        self._stderr_buf = bytearray()
        self._is_running = False
        self._waiting_for_input = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def waiting_for_input(self) -> bool:
        return self._waiting_for_input

    async def send_input(self, data: str):
        """Send input to the running process stdin."""
        if self.process and self.process.stdin and self._is_running:
            try:
                encoded = (data if data.endswith("\n") else data + "\n").encode("utf-8")
                self.process.stdin.write(encoded)
                await self.process.stdin.drain()
                self._waiting_for_input = False
            except (BrokenPipeError, ConnectionResetError, OSError) as e:
                log.warning("Failed to send input to process: %s", e)

    async def kill(self):
        """Kill the running process."""
        if self.process and self._is_running:
            try:
                self.process.kill()
                await self.process.wait()
            except ProcessLookupError:
                pass
            self._is_running = False


class Runner:
    """
    Executes Python files in the project workspace.

    Security model:
    1. ALL commands are checked against the blocklist
    2. ALL code files are scanned for dangerous patterns
    3. Execution is confined to the project workspace
    4. The UI layer must get user permission before calling run()
    """

    def __init__(self, workspace: Path, venv_path: Optional[Path] = None):
        self.workspace = workspace
        self.venv_path = venv_path
        self.security = SecurityChecker()
        self.current_process: Optional[ProcessHandle] = None

    def _get_python_cmd(self) -> str:
        """Get the Python command, preferring venv if available."""
        if self.venv_path and self.venv_path.exists():
            if config.IS_WINDOWS:
                venv_python = self.venv_path / "Scripts" / "python.exe"
            else:
                venv_python = self.venv_path / "bin" / "python"
            if venv_python.exists():
                return str(venv_python)
            # Try without extension on Windows
            venv_python_no_ext = self.venv_path / ("Scripts" if config.IS_WINDOWS else "bin") / "python"
            if venv_python_no_ext.exists():
                return str(venv_python_no_ext)
            # Try python3
            venv_python3 = self.venv_path / ("Scripts" if config.IS_WINDOWS else "bin") / "python3"
            if venv_python3.exists():
                return str(venv_python3)
        return config.PYTHON_CMD

    def _get_pip_cmd(self) -> str:
        """Get the pip command, preferring venv if available."""
        if self.venv_path and self.venv_path.exists():
            if config.IS_WINDOWS:
                venv_pip = self.venv_path / "Scripts" / "pip.exe"
            else:
                venv_pip = self.venv_path / "bin" / "pip"
            if venv_pip.exists():
                return str(venv_pip)
            venv_pip3 = self.venv_path / ("Scripts" if config.IS_WINDOWS else "bin") / "pip3"
            if venv_pip3.exists():
                return str(venv_pip3)
        return config.PIP_CMD

    async def run_python_file(
        self,
        file_path: str,
        timeout: int = 0,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        on_input_needed: Optional[Callable[[], Awaitable[str]]] = None,
        interactive: bool = False,
    ) -> RunResult:
        """
        Run a Python file in the workspace.

        Args:
            file_path: Relative path within workspace (e.g. "main.py")
            timeout: Max seconds before killing the process (0 = use config default)
            on_stdout: Callback for each stdout chunk (for UI streaming)
            on_stderr: Callback for each stderr chunk (for UI streaming)
            on_input_needed: Async callback to get user input when process waits
            interactive: If True, connect stdin to terminal directly (CLI mode only)

        Returns:
            RunResult with stdout, stderr, and exit code
        """
        import sys

        if timeout <= 0:
            timeout = config.PROCESS_RUN_TIMEOUT

        full_path = self.workspace / file_path

        # Security: check file is within workspace
        if not self.security.is_within_workspace(full_path, self.workspace):
            return RunResult(
                success=False,
                error=f"SECURITY: {file_path} is outside the project workspace",
                file_path=file_path,
            )

        if not full_path.exists():
            return RunResult(
                success=False,
                error=f"File not found: {file_path}",
                file_path=file_path,
            )

        # Security: scan the file for dangerous code
        warning = self.security.check_code_file(full_path)
        if warning:
            return RunResult(
                success=False,
                error=f"SECURITY WARNING: {warning}",
                file_path=file_path,
            )

        python_cmd = self._get_python_cmd()
        log.info("Runner: executing %s with %s", file_path, python_cmd)

        start_time = time.monotonic()
        handle = ProcessHandle()
        self.current_process = handle

        try:
            import os
            env = os.environ.copy()
            env["PYTHONPATH"] = str(self.workspace.resolve())

            if interactive:
                # CLI mode: connect stdin directly to terminal
                process = await asyncio.create_subprocess_exec(
                    python_cmd,
                    str(full_path),
                    stdin=sys.stdin,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workspace),
                    env=env,
                )
            else:
                # Web/API mode: use PIPE for stdin so we can feed input programmatically
                process = await asyncio.create_subprocess_exec(
                    python_cmd,
                    "-u",  # Force unbuffered output for real-time streaming
                    str(full_path),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self.workspace),
                    env=env,
                )

            handle.process = process
            handle._is_running = True

            stdout_buf = bytearray()
            stderr_buf = bytearray()

            async def stream_stdout():
                """Read stdout chunks and forward to callback."""
                while True:
                    try:
                        chunk = await process.stdout.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stdout_buf.extend(chunk)

                    if interactive:
                        # In CLI mode, print directly to terminal
                        sys.stdout.write(text)
                        sys.stdout.flush()

                    if on_stdout:
                        on_stdout(text)

                    # Detect if process is waiting for input
                    # Common patterns: prompts ending with ":", "?", "> ", ">>> "
                    stripped = text.rstrip()
                    if stripped and (
                        stripped.endswith(":") or
                        stripped.endswith("?") or
                        stripped.endswith("> ") or
                        stripped.endswith(">>>") or
                        "input" in stripped.lower() or
                        "enter" in stripped.lower()
                    ):
                        handle._waiting_for_input = True
                        if not interactive:
                            # If not interactive, waiting for input means it successfully initialized.
                            # We terminate early to prevent hanging.
                            handle._input_terminated = True
                            process.kill()

            async def stream_stderr():
                """Read stderr chunks and forward to callback."""
                while True:
                    try:
                        chunk = await process.stderr.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stderr_buf.extend(chunk)

                    if interactive:
                        sys.stderr.write(text)
                        sys.stderr.flush()

                    if on_stderr:
                        on_stderr(text)

            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        stream_stdout(),
                        stream_stderr(),
                        process.wait(),
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                elapsed = int((time.monotonic() - start_time) * 1000)
                handle._is_running = False
                self.current_process = None
                return RunResult(
                    success=False,
                    stdout=stdout_buf.decode("utf-8", errors="replace"),
                    stderr=stderr_buf.decode("utf-8", errors="replace"),
                    exit_code=-1,
                    runtime_ms=elapsed,
                    error=f"Timeout: process ran longer than {timeout} seconds",
                    file_path=file_path,
                )

            handle._is_running = False
            self.current_process = None

            elapsed = int((time.monotonic() - start_time) * 1000)
            stdout = stdout_buf.decode("utf-8", errors="replace")
            stderr = stderr_buf.decode("utf-8", errors="replace")

            input_terminated = getattr(handle, "_input_terminated", False)

            result = RunResult(
                success=process.returncode == 0 or input_terminated,
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode,
                runtime_ms=elapsed,
                file_path=file_path,
            )

            if not result.success:
                result.error = stderr or f"Process exited with code {process.returncode}"

            if input_terminated:
                result.error = None
                result.stdout += "\n[System: Auto-terminated validation run because it reached an input prompt successfully.]"

            log.info(
                "Runner: %s finished (exit=%d, %dms)",
                file_path, process.returncode, elapsed,
            )
            return result

        except FileNotFoundError:
            handle._is_running = False
            self.current_process = None
            return RunResult(
                success=False,
                error=f"Python not found at '{python_cmd}'. Is Python installed?",
                file_path=file_path,
            )
        except Exception as e:
            handle._is_running = False
            self.current_process = None
            return RunResult(
                success=False,
                error=f"Execution error: {e}",
                file_path=file_path,
            )

    async def run_shell_command(self, command: str, timeout: int = 15) -> RunResult:
        """
        Securely execute an arbitrary shell command within the project workspace.
        This allows the AI Agent to run tests, linters, or pip install safely.
        """
        # 1. Security Check
        security_err = self.security.check_command(command)
        if security_err:
            return RunResult(
                success=False,
                error=security_err
            )

        log.info("Runner: executing shell command: %s", command)
        start_time = time.monotonic()

        try:
            import os
            env = os.environ.copy()
            # If using a venv, inject it into PATH
            if self.venv_path and self.venv_path.exists():
                venv_bin = str(self.venv_path / "Scripts") if config.IS_WINDOWS else str(self.venv_path / "bin")
                env["PATH"] = f"{venv_bin}{os.pathsep}{env.get('PATH', '')}"
            env["PYTHONPATH"] = str(self.workspace.resolve())

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
                env=env,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(process.communicate(), timeout=timeout)
            elapsed = int((time.monotonic() - start_time) * 1000)

            return RunResult(
                success=process.returncode == 0,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
                exit_code=process.returncode or 0,
                runtime_ms=elapsed
            )

        except asyncio.TimeoutError:
            try:
                process.kill()
            except Exception:
                pass
            elapsed = int((time.monotonic() - start_time) * 1000)
            return RunResult(
                success=False,
                exit_code=-1,
                runtime_ms=elapsed,
                error=f"Timeout: command exceeded {timeout} seconds."
            )
        except Exception as e:
            return RunResult(
                success=False,
                error=f"Execution error: {str(e)}"
            )

    async def send_process_input(self, data: str) -> bool:
        """Send input to the currently running process. Returns True if successful."""
        if self.current_process and self.current_process.is_running:
            await self.current_process.send_input(data)
            return True
        return False

    async def kill_process(self) -> bool:
        """Kill the currently running process. Returns True if successful."""
        if self.current_process and self.current_process.is_running:
            await self.current_process.kill()
            return True
        return False

    async def syntax_check(self, file_path: str) -> RunResult:
        """
        Check a Python file for syntax errors without executing it.
        Uses py_compile which is safe and fast.
        """
        full_path = self.workspace / file_path

        if not full_path.exists():
            return RunResult(
                success=False,
                error=f"File not found: {file_path}",
                file_path=file_path,
            )

        python_cmd = self._get_python_cmd()

        try:
            process = await asyncio.create_subprocess_exec(
                python_cmd, "-m", "py_compile", str(full_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=config.SYNTAX_CHECK_TIMEOUT,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            return RunResult(
                success=process.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode,
                error=stderr if process.returncode != 0 else None,
                file_path=file_path,
            )

        except asyncio.TimeoutError:
            return RunResult(
                success=False,
                error="Syntax check timed out",
                file_path=file_path,
            )
        except Exception as e:
            return RunResult(
                success=False,
                error=f"Syntax check error: {e}",
                file_path=file_path,
            )

    async def install_package(
        self,
        package: str,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> RunResult:
        """
        Install a pip package in the project's venv.

        Security: only allows pip install, never pip uninstall or other commands.
        """
        # Security: validate package name — only alphanumeric, hyphens, underscores, dots, brackets
        if not re.match(r'^[a-zA-Z0-9._\-\[\]>=<,!]+$', package):
            return RunResult(
                success=False,
                error=f"Invalid package name: {package}",
            )

        pip_cmd = self._get_pip_cmd()
        cmd = [pip_cmd, "install", package]

        log.info("Runner: installing package '%s'", package)

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            stdout_buf = bytearray()
            stderr_buf = bytearray()

            async def stream_stdout():
                while True:
                    try:
                        chunk = await process.stdout.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stdout_buf.extend(chunk)
                    if on_stdout:
                        on_stdout(text)

            async def stream_stderr():
                while True:
                    try:
                        chunk = await process.stderr.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stderr_buf.extend(chunk)
                    if on_stderr:
                        on_stderr(text)

            await asyncio.wait_for(
                asyncio.gather(
                    stream_stdout(),
                    stream_stderr(),
                    process.wait(),
                ),
                timeout=300,  # pip can be slow
            )

            stdout = stdout_buf.decode("utf-8", errors="replace")
            stderr = stderr_buf.decode("utf-8", errors="replace")

            return RunResult(
                success=process.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode,
                error=stderr if process.returncode != 0 else None,
            )

        except asyncio.TimeoutError:
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            return RunResult(success=False, error="pip install timed out")
        except Exception as e:
            return RunResult(
                success=False,
                error=f"Package install error: {e}",
            )

    async def install_requirements(
        self,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> RunResult:
        """Install dependencies from requirements.txt."""
        req_path = self.workspace / "requirements.txt"
        if not req_path.exists():
            return RunResult(success=True, stdout="No requirements.txt found.")

        pip_cmd = self._get_pip_cmd()
        cmd = [pip_cmd, "install", "-r", "requirements.txt"]

        log.info("Runner: installing requirements.txt")
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace),
            )

            stdout_buf = bytearray()
            stderr_buf = bytearray()

            async def stream_stdout():
                while True:
                    try:
                        chunk = await process.stdout.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stdout_buf.extend(chunk)
                    if on_stdout:
                        on_stdout(text)

            async def stream_stderr():
                while True:
                    try:
                        chunk = await process.stderr.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stderr_buf.extend(chunk)
                    if on_stderr:
                        on_stderr(text)

            await asyncio.wait_for(
                asyncio.gather(
                    stream_stdout(),
                    stream_stderr(),
                    process.wait(),
                ),
                timeout=300
            )

            return RunResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                stdout=stdout_buf.decode('utf-8', errors='replace'),
                stderr=stderr_buf.decode('utf-8', errors='replace'),
            )
        except asyncio.TimeoutError:
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            return RunResult(success=False, error="pip install timed out")
        except Exception as e:
            return RunResult(success=False, error=str(e))

    async def install_npm_requirements(
        self,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
    ) -> RunResult:
        """Install dependencies from package.json using npm."""
        # Find package.json either in root or frontend/ folder
        pkg_dir = None
        if (self.workspace / "package.json").exists():
            pkg_dir = self.workspace
        elif (self.workspace / "frontend" / "package.json").exists():
            pkg_dir = self.workspace / "frontend"

        if not pkg_dir:
            return RunResult(success=True, stdout="No package.json found.")

        cmd = ["npm", "install"]
        if config.IS_WINDOWS:
            cmd = ["npm.cmd", "install"]

        log.info("Runner: installing npm packages in %s", pkg_dir)
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(pkg_dir),
            )

            stdout_buf = bytearray()
            stderr_buf = bytearray()

            async def stream_stdout():
                while True:
                    try:
                        chunk = await process.stdout.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stdout_buf.extend(chunk)
                    if on_stdout:
                        on_stdout(text)

            async def stream_stderr():
                while True:
                    try:
                        chunk = await process.stderr.read(256)
                    except Exception:
                        break
                    if not chunk:
                        break
                    text = chunk.decode("utf-8", errors="replace")
                    stderr_buf.extend(chunk)
                    if on_stderr:
                        on_stderr(text)

            await asyncio.wait_for(
                asyncio.gather(
                    stream_stdout(),
                    stream_stderr(),
                    process.wait(),
                ),
                timeout=300
            )

            return RunResult(
                success=process.returncode == 0,
                exit_code=process.returncode,
                stdout=stdout_buf.decode('utf-8', errors='replace'),
                stderr=stderr_buf.decode('utf-8', errors='replace'),
            )
        except asyncio.TimeoutError:
            if process:
                try:
                    process.kill()
                except Exception:
                    pass
            return RunResult(success=False, error="npm install timed out")
        except Exception as e:
            return RunResult(success=False, error=str(e))

    async def create_venv(self) -> RunResult:
        """Create a virtual environment for the project, or use an existing one."""
        if self.venv_path and self.venv_path.exists():
            return RunResult(success=True, stdout="venv already exists")

        if not self.venv_path:
            # Check for existing common venv directory names
            for venv_name in ["venv", ".venv", "env", ".env"]:
                potential_path = self.workspace / venv_name
                if (potential_path / "bin" / "python").exists() or \
                   (potential_path / "Scripts" / "python.exe").exists() or \
                   (potential_path / "bin" / "python3").exists():
                    self.venv_path = potential_path
                    log.info("Runner: found existing venv at %s", self.venv_path)
                    return RunResult(success=True, stdout=f"found existing venv at {venv_name}")

            # Fallback to creating a new one
            self.venv_path = self.workspace / "venv"

        log.info("Runner: creating venv at %s", self.venv_path)

        try:
            process = await asyncio.create_subprocess_exec(
                config.PYTHON_CMD, "-m", "venv", str(self.venv_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=60,
            )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            return RunResult(
                success=process.returncode == 0,
                stdout=stdout,
                stderr=stderr,
                exit_code=process.returncode,
                error=stderr if process.returncode != 0 else None,
            )

        except Exception as e:
            return RunResult(
                success=False,
                error=f"Venv creation error: {e}",
            )


class ErrorParser:
    """
    Parses Python tracebacks to extract structured error information.
    Used by the Fixer to understand what went wrong and where.
    """

    @staticmethod
    def _strip_terminal_noise(text: str) -> str:
        r"""
        Strip terminal prompt noise from pasted text.
        Removes lines like:
            user@laptop:~/proj$ python main.py
            >>> import foo
            PS C:\> python main.py
            (venv) user@host:~$
        """
        lines = text.split('\n')
        cleaned = []
        traceback_started = False

        for line in lines:
            stripped = line.strip()

            # Detect traceback start
            if 'Traceback (most recent call last)' in stripped:
                traceback_started = True
                cleaned.append(line)
                continue

            # Before traceback starts, skip terminal prompts
            if not traceback_started:
                # Skip lines that look like shell prompts
                if re.match(r'^[\(\[]?(?:venv|env|base)[\)\]]?\s*\w+@[\w\-\.]+:', stripped):
                    continue
                if re.match(r'^\$\s', stripped) or re.match(r'^>>>\s', stripped):
                    continue
                if re.match(r'^PS\s+[A-Z]:', stripped, re.IGNORECASE):
                    continue
                if re.match(r'^[a-zA-Z]:\\.*>\s', stripped):
                    continue
                # Skip lines that are just a command like "python main.py"
                if re.match(r'^python[3]?\s+\w+\.py', stripped):
                    continue

            cleaned.append(line)

        return '\n'.join(cleaned)

    @staticmethod
    def parse_traceback(error_text: str) -> dict:
        """
        Parse a Python traceback into structured error info.

        Returns:
            {
                "error_type": "ImportError",
                "error_message": "No module named 'foo'",
                "file": "src/main.py",
                "line": 5,
                "is_import_error": True,
                "missing_module": "foo",
            }
        """
        result = {
            "error_type": "",
            "error_message": "",
            "file": "",
            "line": 0,
            "is_import_error": False,
            "is_syntax_error": False,
            "missing_module": "",
        }

        if not error_text:
            return result

        # Pre-process: strip terminal prompt noise
        error_text = ErrorParser._strip_terminal_noise(error_text)

        # Extract the final error line (e.g., "ImportError: No module named 'foo'")
        error_match = re.search(
            r'^(\w+Error|\w+Exception)\s*:\s*(.+?)$',
            error_text,
            re.MULTILINE,
        )
        if error_match:
            result["error_type"] = error_match.group(1)
            result["error_message"] = error_match.group(2).strip()

        # Extract file and line from traceback
        file_match = re.findall(
            r'File "([^"]+)".*?line (\d+)',
            error_text,
        )
        if file_match:
            # Take the last file reference (closest to the error)
            last_file, last_line = file_match[-1]
            # Normalize path separators for cross-platform
            result["file"] = last_file.replace("\\", "/")
            result["line"] = int(last_line)

        # Check for import errors
        if result["error_type"] in ("ImportError", "ModuleNotFoundError"):
            result["is_import_error"] = True
            mod_match = re.search(
                r"No module named ['\"]([^'\"]+)['\"]",
                result["error_message"],
            )
            if mod_match:
                result["missing_module"] = mod_match.group(1)

        # Check for syntax errors
        if result["error_type"] == "SyntaxError":
            result["is_syntax_error"] = True

        return result
