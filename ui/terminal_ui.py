"""
Terminal UI — handles all user interaction using the 'rich' library.

Strictly adheres to the black & white aesthetic requested by the user.
Ensures maximum transparency by streaming LLM output, showing concrete
file registries, and always asking for permission before execution.
"""

from __future__ import annotations
import sys
from typing import List

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.live import Live
from rich.table import Table

from models.state import ProjectState, PlanStep, StepStatus

# Initialize console (standard + error)
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)


class TerminalUI:
    """Terminal interface using Rich, styled in black and white."""

    def __init__(self, state: ProjectState):
        self.state = state

    # ── Basic Output ──────────────────────────────────────────────────

    def print_header(self, title: str):
        """Print a clear header for a new phase."""
        console.print()
        console.print(Panel(
            Text(title, justify="center", style="bold white"),
            border_style="white"
        ))
        console.print()

    def print_step(self, step_name: str, message: str):
        """Print a discrete step in the current process."""
        console.print(f"[bold white]→ {step_name}:[/] {message}")

    def print_success(self, message: str):
        console.print(f"[bold white]✓ SUCCESS:[/] {message}")

    def print_error(self, message: str):
        err_console.print(f"[bold white]✗ ERROR:[/] {message}")

    def print_warning(self, message: str):
        console.print(f"[bold white]! WARNING:[/] {message}")

    def print_info(self, message: str):
        console.print(f"  {message}")

    # ── Input ─────────────────────────────────────────────────────────

    def get_user_input(self, prompt_text: str, default: str = "") -> str:
        """Get input from the user."""
        return Prompt.ask(f"[bold white]{prompt_text}[/]", default=default)

    def get_multiline_input(self, prompt_text: str) -> str:
        """Get multi-line input (useful for the main prompt)."""
        console.print(f"[bold white]{prompt_text}[/] (Type 'END' on a new line to finish):")
        lines = []
        while True:
            try:
                line = input("> ")
                if line.strip() == "END":
                    break
                lines.append(line)
            except EOFError:
                break
            except KeyboardInterrupt:
                sys.exit(1)
        return "\n".join(lines).strip()

    def ask_permission(self, question: str, default: bool = False) -> bool:
        """
        Ask user for yes/no permission.
        Critical for the security requirement (run/install permission).
        """
        console.print()
        return Confirm.ask(f"[bold white]? {question}[/]", default=default)

    # ── LLM Streaming ─────────────────────────────────────────────────

    class LLMStreamContext:
        """Context manager for streaming LLM output smoothly."""
        def __init__(self, title: str):
            self.title = title
            self.content = ""
            self.live = None
            self.panel = None

        def __enter__(self):
            self.panel = Panel("", title=f"[bold white]{self.title}[/]", border_style="bright_black")
            self.live = Live(self.panel, refresh_per_second=10, console=console)
            self.live.start()
            return self

        def on_token(self, token: str):
            self.content += token
            # Update panel content. Rich can handle basic formatting.
            if self.panel:
                self.panel.renderable = self.content

        def __exit__(self, exc_type, exc_val, exc_tb):
            if self.live:
                self.live.stop()
            if exc_type:
                # If an error occurred, print it
                pass
            else:
                # Print final static panel
                console.print(Panel(self.content, title=f"[bold white]{self.title}[/]", border_style="white"))

    def stream_llm(self, title: str) -> LLMStreamContext:
        """Return a context manager for streaming LLM tokens."""
        return self.LLMStreamContext(title)

    # ── Domain-Specific Displays ──────────────────────────────────────

    def show_plan(self, steps: List[PlanStep]):
        """Display the current plan with status."""
        table = Table(show_header=True, header_style="bold white", border_style="bright_black")
        table.add_column("Step", justify="right", style="white")
        table.add_column("Status", justify="center")
        table.add_column("Title", style="white")
        table.add_column("File", style="dim white")

        for step in steps:
            status_char = {
                StepStatus.PENDING: "○",
                StepStatus.IN_PROGRESS: "→",
                StepStatus.COMPLETED: "✓",
                StepStatus.FAILED: "✗",
                StepStatus.SKIPPED: "⊘",
            }.get(step.status, "?")

            table.add_row(
                str(step.step_number),
                status_char,
                step.title,
                step.file_path
            )

        console.print()
        console.print(Panel(table, title="[bold white]Implementation Plan[/]", border_style="white"))
        console.print()

    def show_file_registry(self):
        """Display the current file registry (transparency requirement)."""
        registry_str = self.state.get_file_registry_string()
        console.print(Panel(
            registry_str,
            title="[bold white]Current File Registry (Agent Context)[/]",
            border_style="bright_black"
        ))

    def show_error(self, file_path: str, error_text: str):
        """Display a runtime or syntax error."""
        console.print(Panel(
            error_text,
            title=f"[bold white]Error in {file_path}[/]",
            border_style="bold white"  # White border to keep B&W theme but stand out
        ))

    def show_progress_bar(self):
        """Create a progress bar for plan execution."""
        return Progress(
            SpinnerColumn(style="white"),
            TextColumn("[bold white]{task.description}[/]"),
            BarColumn(complete_style="white", finished_style="bold white", pulse_style="bright_black"),
            TaskProgressColumn(style="white"),
            console=console
        )

    def print_plan_editing_instructions(self, plan_path: str):
        """Instructions for the user to edit the plan.txt file."""
        console.print(Panel(
            Text.assemble(
                ("The implementation plan has been saved to:\n", "white"),
                (f"{plan_path}\n\n", "bold white"),
                ("You can now open this file in your editor and modify it.\n", "white"),
                ("The agent will read the modified plan when you continue.", "white")
            ),
            title="[bold white]Plan Review[/]",
            border_style="white"
        ))
