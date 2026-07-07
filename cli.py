"""
Context Agent — CLI Entry Point.

The terminal-based execution loop (legacy interface).
For the web UI, use: python -m backend.server
"""

import asyncio
import sys
import re
from pathlib import Path

import config
from core.llm_client import LLMClient
from core.planner import Planner
from core.coder import Coder
from core.runner import Runner
from core.fixer import Fixer
from core.context import SmartChunker
from models.state import ProjectState, StepStatus
from ui.terminal_ui import TerminalUI


async def main():
    # ── 1. Initialization ─────────────────────────────────────────────
    state = ProjectState()
    ui = TerminalUI(state)

    ui.print_header("CONTEXT AGENT")

    # Get project details
    state.project_name = ui.get_user_input("Enter project name", default=state.project_id)

    # Setup workspace
    safe_name = "".join(c for c in state.project_name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
    workspace_dir = config.PROJECTS_DIR / safe_name
    workspace_dir.mkdir(parents=True, exist_ok=True)
    state.workspace_path = str(workspace_dir)

    ui.print_info(f"Workspace created at: {workspace_dir}")

    # Create venv
    runner = Runner(workspace_dir)
    ui.print_step("Setup", "Creating virtual environment...")
    venv_result = await runner.create_venv()
    if venv_result.success:
        ui.print_success("Virtual environment created.")
        state.venv_path = str(runner.venv_path)
    else:
        ui.print_error(f"Failed to create venv: {venv_result.error}")
        if not ui.ask_permission("Continue without venv?"):
            sys.exit(1)

    # Re-initialize runner with venv — guard against empty venv_path
    venv_path = Path(state.venv_path) if state.venv_path else None
    runner = Runner(workspace_dir, venv_path=venv_path)

    # Initialize LLM & Agents
    llm = LLMClient()

    ui.print_step("Health Check", "Connecting to Ollama...")
    health = await llm.health_check()
    if not health["ollama_running"]:
        ui.print_error(health["error"])
        sys.exit(1)
    if not health["model_available"]:
        ui.print_error(health["error"])
        if not ui.ask_permission(f"Continue anyway? (Agent will try to use {config.OLLAMA_MODEL})"):
            sys.exit(1)

    planner = Planner(llm, state)
    coder = Coder(llm, state, workspace_dir)
    fixer = Fixer(llm, state, workspace_dir, runner, coder)

    # Get prompt
    ui.print_header("PROJECT PROMPT")
    user_prompt = ui.get_multiline_input("Describe the system you want to build")
    if not user_prompt:
        sys.exit(0)

    state.original_prompt = user_prompt
    state.save(workspace_dir / "project_state.json")

    # Chunking check
    if SmartChunker.needs_chunking(user_prompt):
        ui.print_warning("Prompt is very large. It will be chunked intelligently.")
        chunks = SmartChunker.chunk(user_prompt)
        planning_prompt = chunks[0] + "\n\n[Prompt truncated for planning...]"
    else:
        planning_prompt = user_prompt

    # ── 2. Planning ───────────────────────────────────────────────────
    ui.print_header("PHASE 1: PLANNING")

    with ui.stream_llm("Generating Plan...") as stream:
        plan_text = await planner.generate_plan(planning_prompt, on_token=stream.on_token)

    # Save plan
    plan_path = workspace_dir / "plan.txt"
    plan_path.write_text(plan_text, encoding="utf-8")
    state.plan_text = plan_text

    # Parse plan
    state.plan_steps = planner.parse_plan(plan_text)
    state.save(workspace_dir / "project_state.json")

    # Display plan
    ui.show_plan(state.plan_steps)

    # ── 3. Plan Review ────────────────────────────────────────────────
    ui.print_plan_editing_instructions(str(plan_path))
    ui.get_user_input("Press Enter when you have finished reviewing/editing the plan.txt file")

    # Reload plan in case user edited it
    edited_plan_text = plan_path.read_text(encoding="utf-8")
    if edited_plan_text != plan_text:
        ui.print_info("Reloading modified plan...")
        state.plan_text = edited_plan_text
        state.plan_steps = planner.parse_plan(edited_plan_text)
        ui.show_plan(state.plan_steps)
        state.save(workspace_dir / "project_state.json")

    if not ui.ask_permission("Begin execution of this plan?", default=True):
        ui.print_info("Execution cancelled by user.")
        sys.exit(0)

    # ── 4. Execution Loop ─────────────────────────────────────────────
    ui.print_header("PHASE 2: EXECUTION")

    for i, step in enumerate(state.plan_steps):
        state.current_step = i

        ui.print_header(f"Step {step.step_number}: {step.title}")
        ui.print_info(f"Target file: {step.file_path}")

        # Show file registry for transparency
        ui.show_file_registry()

        step.status = StepStatus.IN_PROGRESS
        state.save(workspace_dir / "project_state.json")

        # Code Generation
        with ui.stream_llm(f"Writing {step.file_path}...") as stream:
            success, error = await coder.generate_code(step, on_token=stream.on_token)

        if not success:
            ui.print_error(f"Generation failed: {error}")
            step.status = StepStatus.FAILED
            step.error = error
            # Enter fix loop for syntax errors
            if "Syntax Error" in error:
                fixed = await _fix_loop(ui, fixer, step.file_path, error)
                if not fixed:
                    if not ui.ask_permission("Continue to next step despite failure?"):
                        break
            continue

        ui.print_success(f"Generated {step.file_path}")



        # Execution / Verification
        if step.file_path.endswith(".py"):
            entry_point = state.project_entry_point or "main.py"
            entry_path = workspace_dir / entry_point
            target_to_run = entry_point if (step.file_path.startswith("src/") and entry_path.exists()) else step.file_path

            # CRITICAL: Security requirement - ALWAYS ask before execution
            if ui.ask_permission(f"Execute {target_to_run} to verify?", default=True):
                ui.print_step("Testing", f"Starting {target_to_run}...")

                # Clear boundaries for interactive execution
                print("\n" + "═" * 80)
                print(f"  ▶ RUNNING: {target_to_run}")
                print("  (If the program seems stuck, it may be waiting for your input!)")
                print("═" * 80 + "\n")

                # CLI mode: connect stdin directly to terminal
                run_result = await runner.run_python_file(target_to_run, interactive=True)

                print("\n" + "═" * 80)
                print(f"  ■ END OF RUN: {target_to_run}")
                print("═" * 80 + "\n")

                if run_result.success:
                    ui.print_success("Execution successful!")
                    if run_result.stdout.strip():
                        ui.print_info(f"Captured Output: {run_result.stdout.strip()[:200]}...")
                else:
                    ui.show_error(target_to_run, run_result.error or run_result.stderr)

                    if ui.ask_permission("Attempt auto-fix with LLM?", default=True):
                        fixed = await _fix_loop(ui, fixer, target_to_run, run_result.error or run_result.stderr)
                        if not fixed and not ui.ask_permission("Continue to next step despite errors?"):
                            break

        # Mark step complete
        step.status = StepStatus.COMPLETED
        state.completed_steps.add(step.step_number)
        state.save(workspace_dir / "project_state.json")

    # ── 5. Final ──────────────────────────────────────────────────────
    ui.print_header("PROJECT COMPLETED")
    ui.show_plan(state.plan_steps)

    usage = llm.get_usage()
    ui.print_info(f"Total LLM calls: {usage['total_calls']}")
    ui.print_info(f"Total tokens used: {usage['total_tokens']} ({usage['total_prompt_tokens']} prompt, {usage['total_completion_tokens']} completion)")
    ui.print_info(f"Workspace path: {state.workspace_path}")

    entry_point = state.project_entry_point or "main.py"
    if (workspace_dir / entry_point).exists():
        if ui.ask_permission(f"Run final project ({entry_point})?", default=True):
            result = await runner.run_python_file(entry_point, interactive=True)
            if result.success:
                ui.print_success("Project runs successfully!")
                print("\n=== OUTPUT ===")
                print(result.stdout)
                print("==============")
            else:
                ui.show_error(entry_point, result.error or result.stderr)


async def _fix_loop(ui: TerminalUI, fixer: Fixer, file_path: str, error_text: str) -> bool:
    """Run the auto-fix loop up to MAX_FIX_ATTEMPTS."""
    attempts = 0
    current_error = error_text
    target_file = file_path

    while attempts < config.MAX_FIX_ATTEMPTS:
        attempts += 1

        # Smart error targeting: find the deepest workspace file in the traceback
        matches = re.findall(r'File "([^"]+)"', current_error)
        if matches:
            workspace_path = fixer.workspace.resolve()
            for match in reversed(matches):
                try:
                    match_path = Path(match).resolve()
                    if match_path.is_relative_to(workspace_path):
                        target_file = match_path.relative_to(workspace_path).as_posix()
                        break
                    elif not match_path.is_absolute() and not match.startswith("<"):
                        target_file = match_path.as_posix()
                        break
                except Exception:
                    pass

        ui.print_step(f"Fix Attempt {attempts}/{config.MAX_FIX_ATTEMPTS}", f"Analyzing {target_file}...")

        with ui.stream_llm("Generating fix...") as stream:
            success, msg = await fixer.fix_error(target_file, current_error, on_token=stream.on_token)

        if not success:
            ui.print_error(msg)
            return False

        ui.print_success("Fix applied. Verifying...")

        # Verify the fix
        run_result = await fixer.runner.run_python_file(file_path, interactive=True)
        if run_result.success:
            ui.print_success("Fix resolved the error!")
            return True

        # Still broken, prepare for next attempt
        current_error = run_result.error or run_result.stderr
        ui.show_error(file_path, current_error)

        user_choice = ui.get_user_input("Error remains. Press Enter to retry, type a hint for the AI, or type 'n' to skip", default="")
        if user_choice.lower() == 'n':
            return False

        if user_choice.strip() and user_choice.lower() != 'y':
            current_error += f"\n\nUSER HINT TO FIX THIS ERROR:\n{user_choice.strip()}"

    ui.print_error("Max fix attempts reached.")
    return False


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nOperation cancelled by user. Exiting.")
        sys.exit(0)
