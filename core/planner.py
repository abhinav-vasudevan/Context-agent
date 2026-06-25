"""
Planner — generates and parses implementation plans.

Takes the user's prompt → calls LLM → produces a structured plan
with numbered steps, file paths, dependencies, and descriptions.

Key rules enforced:
  - Step 1 is ALWAYS main.py (skeleton entry point)
  - Source files go in src/
  - Last step is README.md
  - Each step produces exactly one file
"""

from __future__ import annotations
import re
import logging
from typing import List, Optional

from core.llm_client import LLMClient
from core.context import ContextAssembler
from models.state import PlanStep, ProjectState

log = logging.getLogger(__name__)


class Planner:
    """Generates structured plans and parses them into PlanStep objects."""

    def __init__(self, llm: LLMClient, state: ProjectState):
        self.llm = llm
        self.state = state
        self.assembler = ContextAssembler(state)

    async def generate_architecture(
        self,
        user_prompt: str,
        on_token=None,
        on_thinking=None,
    ) -> str:
        """
        Phase 1: Generate a deep architectural blueprint from the user prompt.
        """
        log.info("Planner: generating architecture for prompt (len=%d)", len(user_prompt))

        ctx = self.assembler.build_architect_prompt(user_prompt)

        chunks = []
        try:
            async for chunk in self.llm.generate_stream(
                prompt=ctx["prompt"],
                system=ctx["system"],
                on_token=on_token,
                on_thinking=on_thinking,
            ):
                chunks.append(chunk)
        except Exception as e:
            log.error("Planner architecture generation failed: %s", e)
            raise ValueError(f"Architect failed to generate from the API: {str(e)}")

        arch_text = "".join(chunks)
        log.info("Planner: architecture generated (len=%d)", len(arch_text))
        return arch_text

    async def generate_plan(
        self,
        user_prompt: str,
        architecture_text: str,
        on_token=None,
        on_thinking=None,
    ) -> str:
        """
        Phase 2: Generate a plan from the user's prompt and architectural blueprint.
        
        Args:
            user_prompt: The user's project description
            architecture_text: The deeply reasoned architecture.md text
            on_token: Optional callback for streaming tokens to UI
            on_thinking: Optional callback for streaming thinking tokens to UI
            
        Returns:
            The raw plan text
        """
        log.info("Planner: generating plan for prompt (len=%d)", len(user_prompt))

        ctx = self.assembler.build_planner_prompt(user_prompt, architecture_text)

        # Stream the plan generation so user sees it being built
        chunks = []
        
        try:
            async for chunk in self.llm.generate_stream(
                prompt=ctx["prompt"],
                system=ctx["system"],
                on_token=on_token,
                on_thinking=on_thinking,
            ):
                chunks.append(chunk)
                
        except Exception as e:
            log.error("Planner generation failed: %s", e)
            raise ValueError(f"Planner failed to generate from the API: {str(e)}")

        plan_text = "".join(chunks)
        
        # Remove any <think> blocks from the final plan string so the parser doesn't see them
        plan_text = re.sub(r'<think>.*?</think>', '', plan_text, flags=re.DOTALL)
        # Also strip unclosed blocks (model hit token limit mid-think)
        plan_text = re.sub(r'<think>.*$', '', plan_text, flags=re.DOTALL)
        
        # Support Ollama alternative output formats
        plan_text = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', plan_text, flags=re.DOTALL)
        plan_text = re.sub(r'Thinking\.\.\..*$', '', plan_text, flags=re.DOTALL)
        
        log.info("Planner: plan generated (len=%d)", len(plan_text))

        return plan_text

    def parse_plan(self, plan_text: str) -> List[PlanStep]:
        """
        Parse a plan text into structured PlanStep objects.
        
        Expected format:
            STEP 1: [title]
            FILE: [file_path]
            DEPENDS: [step numbers or "none"]
            DESCRIPTION: [description]
            ---
            
        Uses a two-pass approach:
        1. Primary: Split on STEP N: headers
        2. Fallback: Look for numbered lists with file paths
            
        Returns:
            List of PlanStep objects
        """
        steps = []
        
        # Pre-process: strip markdown code fences wrapping the whole plan
        cleaned = plan_text.strip()
        if cleaned.startswith("```"):
            # Remove opening and closing fences
            cleaned = re.sub(r'^```\w*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```\s*$', '', cleaned)

        # Primary parser: Split on STEP N: headers (allowing optional markdown like ** or ###)
        blocks = re.split(r'\n(?=[ \t*\-#]*STEP\s+\d+\s*:)', '\n' + cleaned, flags=re.IGNORECASE)

        for block in blocks:
            block = block.strip()
            if not block:
                continue
            
            # Remove any trailing --- from the block if they exist
            block = re.sub(r'\n---+\s*$', '', block).strip()

            step = self._parse_step_block(block)
            if step:
                steps.append(step)

        # Fallback parser: if zero steps found, try numbered list format
        # Some models output "1. **main.py** - Create entry point" instead of "STEP 1:"
        if not steps:
            log.warning("Primary parser found 0 steps. Trying fallback numbered-list parser.")
            steps = self._fallback_parse(cleaned)

        # Validate and fix the plan
        steps = self._validate_plan(steps)

        log.info("Planner: parsed %d steps from plan", len(steps))
        return steps

    def _fallback_parse(self, text: str) -> List[PlanStep]:
        """
        Fallback parser for when the model ignores the STEP N: format
        and outputs numbered lists like:
            1. **Create main.py** - FILE: main.py ...
            2. **Calculator module** - FILE: src/calc.py ...
        """
        steps = []
        # Match patterns like "1." or "1)" at the start of a line
        blocks = re.split(r'\n(?=\d+[.)]\s)', '\n' + text)
        
        for block in blocks:
            block = block.strip()
            if not block:
                continue
                
            # Try to extract number, title, and file path
            num_match = re.match(r'(\d+)[.)]\s*\**([^*\n:]+)\**', block)
            if not num_match:
                continue
                
            step_number = int(num_match.group(1))
            title = num_match.group(2).strip(' -:')
            
            # Try to find a file path
            file_match = re.search(r'(?:FILE\s*:|file\s*:|\b)((?:src/)?[\w/]+\.(?:py|md|txt))\b', block, re.IGNORECASE)
            file_path = file_match.group(1).strip() if file_match else ""
            
            if not file_path:
                # Try to infer from title
                if 'main.py' in block.lower():
                    file_path = 'main.py'
                elif 'readme' in block.lower():
                    file_path = 'README.md'
                else:
                    continue  # Skip blocks without a detectable file path
            
            # Description is the rest of the block
            description = block[num_match.end():].strip(' -:\n')
            
            steps.append(PlanStep(
                step_number=step_number,
                title=title,
                file_path=file_path,
                description=description or title,
            ))
        
        if steps:
            log.info("Fallback parser found %d steps", len(steps))
        
        return steps

    def _parse_step_block(self, block: str) -> Optional[PlanStep]:
        """Parse a single step block into a PlanStep."""
        # Extract step number and title (robust to markdown)
        step_match = re.search(
            r'STEP\s+(\d+)\s*:\s*([^\n]+)',
            block,
            re.IGNORECASE,
        )
        if not step_match:
            return None

        step_number = int(step_match.group(1))
        # Strip markdown bold/italics from the title
        title = step_match.group(2).strip(' *#`')

        # Extract file path
        file_match = re.search(
            r'FILE\s*:\s*([^\n]+)',
            block,
            re.IGNORECASE,
        )
        file_path = file_match.group(1).strip() if file_match else ""

        # Clean up file path — remove backticks, quotes
        file_path = file_path.strip('`"\' ')

        # Extract dependencies
        deps_match = re.search(
            r'DEPENDS?\s*:\s*([^\n]+)',
            block,
            re.IGNORECASE,
        )
        depends_on = []
        if deps_match:
            deps_text = deps_match.group(1).strip().lower()
            if deps_text not in ("none", "n/a", "-", ""):
                # Extract numbers from the dependency text
                dep_numbers = re.findall(r'\d+', deps_text)
                depends_on = [int(d) for d in dep_numbers]

        # Extract description — everything after DESCRIPTION:
        desc_match = re.search(
            r'DESCRIPTION\s*:\s*(.+)',
            block,
            re.IGNORECASE | re.DOTALL,
        )
        description = desc_match.group(1).strip() if desc_match else title

        return PlanStep(
            step_number=step_number,
            title=title,
            file_path=file_path,
            description=description,
            depends_on=depends_on,
        )

    def _validate_plan(self, steps: List[PlanStep]) -> List[PlanStep]:
        """
        Validate and fix the plan to ensure our mandatory rules are met:
        1. Step 1 must be main.py
        2. Source files go in src/
        3. Last step should be README.md
        4. Each step has a valid file path
        """
        if not steps:
            return steps

        # Ensure step numbers are sequential starting from 1
        for i, step in enumerate(steps):
            step.step_number = i + 1

        # Check if ANY step is main.py
        main_step = next((s for s in steps if s.file_path.endswith("main.py")), None)
        
        if main_step:
            main_step.file_path = "main.py"
            main_step.description = (
                "Create a completely empty file. Do NOT write any imports. "
                "Only write an empty `if __name__ == '__main__':` block. "
                "The system will automatically populate this file later."
            )
            # If it's not the first step, move it to the front
            if steps[0] != main_step:
                steps.remove(main_step)
                steps.insert(0, main_step)
        else:
            log.warning("No main.py step found in plan. Inserting one.")
            # Insert a main.py step at the beginning
            main_step = PlanStep(
                step_number=1,
                title="Create main.py entry point",
                file_path="main.py",
                description=(
                    "Create the main entry point for the project. "
                    "Include 'import sys, os; sys.path.insert(0, os.path.join(os.path.dirname(__file__), \"src\"))' "
                    "at the top, then a basic if __name__ == '__main__' block that will be "
                    "updated as new modules are added."
                ),
            )
            steps.insert(0, main_step)
            
        # Renumber all steps
        for i, step in enumerate(steps):
            step.step_number = i + 1

        # Ensure source files have src/ prefix (except main.py and README.md)
        for step in steps:
            fp = step.file_path
            if fp in ("main.py", "README.md", "requirements.txt"):
                continue
            if not fp.startswith("src/") and fp.endswith(".py"):
                step.file_path = f"src/{fp}"
                log.info("Fixed file path: %s -> %s", fp, step.file_path)

        # Remove duplicate file paths (do this before injecting requirements/readme)
        seen_files = set()
        deduped = []
        for step in steps:
            if step.file_path not in seen_files:
                seen_files.add(step.file_path)
                deduped.append(step)
            else:
                log.warning("Removing duplicate step for file: %s", step.file_path)
        steps = deduped

        # Ensure requirements.txt exists
        req_step = next((s for s in steps if s.file_path == "requirements.txt"), None)
        if not req_step:
            req_step = PlanStep(
                step_number=len(steps) + 1,
                title="Create requirements.txt",
                file_path="requirements.txt",
                description="List all third-party pip dependencies used in the project.",
                depends_on=[s.step_number for s in steps if s.file_path.endswith('.py')],
            )
            # Insert before README if README is already there, otherwise append
            readme_idx = next((i for i, s in enumerate(steps) if s.file_path == "README.md"), -1)
            if readme_idx >= 0:
                steps.insert(readme_idx, req_step)
            else:
                steps.append(req_step)

        # Ensure last step is README.md
        readme_step = next((s for s in steps if s.file_path == "README.md"), None)
        if readme_step:
            steps.remove(readme_step)
        
        readme_step = PlanStep(
            step_number=len(steps) + 1,
            title="Create README.md",
            file_path="README.md",
            description=(
                "Create a comprehensive README.md documenting the project. "
                "CRITICAL: You MUST include explicit instructions on how to activate the "
                "virtual environment (`source venv/bin/activate` on Linux/Mac, or `venv\\\\Scripts\\\\activate` on Windows) "
                "BEFORE running `python main.py`. "
                "If the system encountered any errors running main.py that require user "
                "intervention (like missing system dependencies or API keys), "
                "you MUST document them clearly under a 'Manual Setup Required' section."
            ),
            depends_on=[s.step_number for s in steps],
        )
        steps.append(readme_step)

        # Final renumber
        for i, step in enumerate(steps):
            step.step_number = i + 1

        return steps

    def format_plan_for_display(self, steps: List[PlanStep]) -> str:
        """Format plan steps for display in the terminal UI."""
        lines = []
        for step in steps:
            status_icon = {
                "pending": "○",
                "in_progress": "→",
                "completed": "✓",
                "failed": "✗",
                "skipped": "⊘",
            }.get(step.status.value, "?")

            deps_str = ""
            if step.depends_on:
                deps_str = f" [depends: {', '.join(str(d) for d in step.depends_on)}]"

            lines.append(
                f"  {status_icon} Step {step.step_number}: {step.title}"
            )
            lines.append(f"    File: {step.file_path}{deps_str}")
            lines.append(f"    {step.description[:120]}")
            lines.append("")

        return "\n".join(lines)
