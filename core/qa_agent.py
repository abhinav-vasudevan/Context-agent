"""
QA Agent — Autonomous Testing with LLM-driven Interactive Input.

Runs the generated application (main.py) and uses the LLM to reason about
and provide interactive inputs, exactly as a human tester would.

The QA Agent does NOT modify source code. It interacts with the running
process via stdin/stdout piping.
"""

from __future__ import annotations
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional, Callable, List

import config
from core.llm_client import LLMClient

log = logging.getLogger(__name__)


@dataclass
class QAResult:
    """Result of a QA test run."""
    success: bool
    interactions: List[dict]  # [{prompt: str, response: str}, ...]
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    bug_report: Optional[str] = None


class QAAgent:
    """
    Autonomous QA tester that runs the generated application and
    uses the LLM to provide interactive inputs like a human would.
    """

    def __init__(self, llm: LLMClient, original_prompt: str):
        self.llm = llm
        self.original_prompt = original_prompt

    async def test_application(
        self,
        python_cmd: str,
        main_file: str,
        workspace: str,
        on_stdout: Optional[Callable[[str], None]] = None,
        on_stderr: Optional[Callable[[str], None]] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> QAResult:
        """
        Run main.py and interact with it like a human tester.

        1. Launch the process with piped stdin/stdout/stderr.
        2. Monitor stdout for input prompts.
        3. Use the LLM to reason about valid inputs.
        4. Inject responses into stdin.
        5. Observe final output and report success or bugs.
        """
        import os

        interactions = []
        stdout_buf = bytearray()
        stderr_buf = bytearray()
        stdout_text_so_far = ""
        interaction_count = 0

        env = os.environ.copy()
        env["PYTHONPATH"] = workspace

        if on_status:
            on_status("QA Agent: Starting application test...")

        try:
            process = await asyncio.create_subprocess_exec(
                python_cmd,
                "-u",  # Unbuffered output
                main_file,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
                env=env,
            )
        except FileNotFoundError:
            return QAResult(
                success=False,
                interactions=[],
                error=f"Python not found at '{python_cmd}'",
            )
        except Exception as e:
            return QAResult(
                success=False,
                interactions=[],
                error=f"Failed to start process: {e}",
            )

        start_time = time.monotonic()
        process_finished = False

        try:
            while not process_finished:
                # Check timeout
                elapsed = time.monotonic() - start_time
                if elapsed > config.QA_PROCESS_TIMEOUT:
                    process.kill()
                    return QAResult(
                        success=False,
                        interactions=interactions,
                        stdout=stdout_buf.decode("utf-8", errors="replace"),
                        stderr=stderr_buf.decode("utf-8", errors="replace"),
                        error=f"QA test timed out after {config.QA_PROCESS_TIMEOUT}s",
                    )

                # Check interaction limit
                if interaction_count >= config.MAX_QA_INTERACTIONS:
                    process.kill()
                    return QAResult(
                        success=False,
                        interactions=interactions,
                        stdout=stdout_buf.decode("utf-8", errors="replace"),
                        stderr=stderr_buf.decode("utf-8", errors="replace"),
                        error=f"QA Agent hit max interactions ({config.MAX_QA_INTERACTIONS}). Possible infinite input loop.",
                    )

                # Read stdout with a short timeout to detect input prompts
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(1024),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    # No output for 5 seconds — check if process is still running
                    if process.returncode is not None:
                        process_finished = True
                        break

                    # Process is alive but silent — likely waiting for input
                    # with no visible prompt. Provide a generic input.
                    if stdout_text_so_far.strip():
                        input_response = await self._reason_about_input(
                            stdout_text_so_far,
                            "(The program appears to be waiting for input silently)",
                            interactions,
                        )
                        interactions.append({
                            "prompt": "(silent wait)",
                            "response": input_response,
                        })
                        interaction_count += 1
                        try:
                            process.stdin.write((input_response + "\n").encode("utf-8"))
                            await process.stdin.drain()
                        except (BrokenPipeError, ConnectionResetError):
                            process_finished = True
                    continue

                if not chunk:
                    # EOF — process finished
                    process_finished = True
                    break

                text = chunk.decode("utf-8", errors="replace")
                stdout_buf.extend(chunk)
                stdout_text_so_far += text

                if on_stdout:
                    on_stdout(text)

                # Detect if the output ends with an input prompt
                if self._looks_like_input_prompt(text):
                    if on_status:
                        on_status(f"QA Agent: Detected input prompt, reasoning about response...")

                    input_response = await self._reason_about_input(
                        stdout_text_so_far,
                        text.strip(),
                        interactions,
                    )

                    interactions.append({
                        "prompt": text.strip(),
                        "response": input_response,
                    })
                    interaction_count += 1

                    if on_stdout:
                        on_stdout(f"\n[QA Agent Input] → {input_response}\n")

                    try:
                        process.stdin.write((input_response + "\n").encode("utf-8"))
                        await process.stdin.drain()
                    except (BrokenPipeError, ConnectionResetError):
                        process_finished = True

            # Wait for process to finish
            try:
                await asyncio.wait_for(process.wait(), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

            # Drain remaining stderr
            try:
                remaining_stderr = await asyncio.wait_for(
                    process.stderr.read(), timeout=5
                )
                if remaining_stderr:
                    stderr_buf.extend(remaining_stderr)
                    if on_stderr:
                        on_stderr(remaining_stderr.decode("utf-8", errors="replace"))
            except asyncio.TimeoutError:
                pass

        except Exception as e:
            try:
                process.kill()
                await process.wait()
            except Exception:
                pass
            return QAResult(
                success=False,
                interactions=interactions,
                stdout=stdout_buf.decode("utf-8", errors="replace"),
                stderr=stderr_buf.decode("utf-8", errors="replace"),
                error=f"QA Agent error: {e}",
            )

        final_stdout = stdout_buf.decode("utf-8", errors="replace")
        final_stderr = stderr_buf.decode("utf-8", errors="replace")

        # Determine success
        has_error = process.returncode != 0 or bool(final_stderr.strip())

        if has_error:
            bug_report = await self._generate_bug_report(
                final_stdout, final_stderr, interactions, process.returncode
            )
            return QAResult(
                success=False,
                interactions=interactions,
                stdout=final_stdout,
                stderr=final_stderr,
                error=final_stderr or f"Process exited with code {process.returncode}",
                bug_report=bug_report,
            )

        return QAResult(
            success=True,
            interactions=interactions,
            stdout=final_stdout,
            stderr=final_stderr,
        )

    def _looks_like_input_prompt(self, text: str) -> bool:
        """Detect if the text looks like it's asking for user input."""
        stripped = text.rstrip()
        if not stripped:
            return False

        # Common prompt patterns
        prompt_endings = (":", "?", "> ", ">>> ", "$ ")
        prompt_keywords = (
            "enter", "input", "type", "choose", "select",
            "name", "password", "username", "option", "choice",
            "press", "provide", "specify",
        )

        ends_with_prompt = any(stripped.endswith(e) for e in prompt_endings)
        has_keyword = any(kw in stripped.lower() for kw in prompt_keywords)

        return ends_with_prompt and has_keyword

    async def _reason_about_input(
        self,
        full_stdout: str,
        current_prompt: str,
        previous_interactions: List[dict],
    ) -> str:
        """Use the LLM to decide what input to provide."""
        # Build context of previous interactions
        interaction_history = ""
        if previous_interactions:
            interaction_history = "\n".join(
                f"  Program asked: {i['prompt']}\n  I entered: {i['response']}"
                for i in previous_interactions
            )

        system = (
            "You are a QA tester interacting with a CLI application. "
            "The program is asking for input. Based on the context, "
            "provide a single, realistic, valid test input value. "
            "Respond with ONLY the input value — no explanation, no quotes, "
            "no formatting. Just the raw value to type."
        )

        prompt = (
            f"The application was built for this purpose:\n"
            f"{self.original_prompt}\n\n"
            f"Program output so far:\n{full_stdout[-2000:]}\n\n"
        )

        if interaction_history:
            prompt += f"Previous inputs I provided:\n{interaction_history}\n\n"

        prompt += (
            f"The program is now showing this prompt:\n"
            f"'{current_prompt}'\n\n"
            f"What should I type? Respond with ONLY the input value."
        )

        try:
            response = await self.llm.generate(prompt=prompt, system=system)
            # Clean up the response — take only the first line
            clean = response.strip().split("\n")[0].strip()
            # Remove quotes if the LLM wrapped it
            if (clean.startswith('"') and clean.endswith('"')) or \
               (clean.startswith("'") and clean.endswith("'")):
                clean = clean[1:-1]
            return clean if clean else "test"
        except Exception as e:
            log.warning("QA Agent: LLM reasoning failed: %s. Using fallback.", e)
            return "test"

    async def _generate_bug_report(
        self,
        stdout: str,
        stderr: str,
        interactions: List[dict],
        exit_code: int,
    ) -> str:
        """Generate a structured bug report from the test results."""
        interaction_log = ""
        if interactions:
            interaction_log = "\n".join(
                f"  Input prompt: {i['prompt']}\n  QA response: {i['response']}"
                for i in interactions
            )

        report = (
            f"=== QA Agent Bug Report ===\n"
            f"Exit Code: {exit_code}\n\n"
        )

        if interaction_log:
            report += f"Interactions:\n{interaction_log}\n\n"

        if stdout.strip():
            report += f"Stdout:\n{stdout[-2000:]}\n\n"

        if stderr.strip():
            report += f"Stderr:\n{stderr[-2000:]}\n\n"

        return report
