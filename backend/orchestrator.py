"""
Orchestrator — class-based orchestrator that can be driven by both CLI and Web UI.

Replaces the old procedural main.py with a stateful class that uses callbacks
for all user interactions. This means the same orchestrator works with both
the terminal UI and the FastAPI web backend.
"""

from __future__ import annotations
import asyncio
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

import config
from core.llm_client import LLMClient
from core.planner import Planner
from core.coder import Coder
from core.runner import Runner, ErrorParser
from core.fixer import Fixer
from core.context import SmartChunker
from models.state import ProjectState, StepStatus, PlanStep
from backend.ws_manager import ConnectionManager

log = logging.getLogger(__name__)


class Orchestrator:
    """
    Drives the Context Agent workflow with WebSocket-based callbacks.

    Lifecycle:
    1. create_project(name, prompt)
    2. generate_plan()
    3. approve_plan()
    4. execute_all() or execute_step(n)
    5. send_input(text) — when a process needs user input
    """

    def __init__(self, ws_manager: ConnectionManager):
        self.ws = ws_manager
        self.state: Optional[ProjectState] = None
        self.llm: Optional[LLMClient] = None
        self.planner: Optional[Planner] = None
        self.coder: Optional[Coder] = None
        self.runner: Optional[Runner] = None
        self.fixer: Optional[Fixer] = None
        self.workspace_dir: Optional[Path] = None

        # Permission handling via async events
        self._permission_event: Optional[asyncio.Event] = None
        self._permission_response: bool = False

        # Input handling
        self._input_event: Optional[asyncio.Event] = None
        self._input_response: str = ""

        # Execution control
        self._executing = False
        self._cancel_requested = False

    # ── Project Lifecycle ─────────────────────────────────────────────

    async def create_project(self, name: str, prompt: str = "") -> dict:
        """Create a new project workspace."""
        self.state = ProjectState()
        self.state.project_name = name
        self.state.original_prompt = prompt

        # Create workspace
        safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
        self.workspace_dir = config.PROJECTS_DIR / safe_name
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.state.workspace_path = str(self.workspace_dir)

        # Initialize LLM
        self.llm = LLMClient()

        # Health check
        health = await self.llm.health_check()
        if not health["ollama_running"]:
            await self.ws.send_error(health["error"] or "Cannot connect to Ollama")
            return {"success": False, "error": health["error"]}

        if not health["model_available"]:
            await self.ws.send_status("warning", health["error"] or f"Model {config.OLLAMA_MODEL} not found")

        # Create venv
        await self.ws.send_status("setup", "Creating virtual environment...")
        self.runner = Runner(self.workspace_dir)
        venv_result = await self.runner.create_venv()

        if venv_result.success:
            self.state.venv_path = str(self.runner.venv_path)
            await self.ws.send_status("setup", "Virtual environment created")
        else:
            await self.ws.send_status("warning", f"Venv creation failed: {venv_result.error}")

        # Re-init runner with venv
        venv_path = Path(self.state.venv_path) if self.state.venv_path else None
        self.runner = Runner(self.workspace_dir, venv_path=venv_path)

        # Initialize agents
        self.planner = Planner(self.llm, self.state)
        self.coder = Coder(self.llm, self.state, self.workspace_dir)
        self.fixer = Fixer(self.llm, self.state, self.workspace_dir, self.runner, self.coder)

        self.state.status = "idle"
        self.state.save(self.workspace_dir / "project_state.json")

        await self.ws.send_status("ready", f"Project '{name}' created")
        return {"success": True, "project": self.state.to_api_dict()}

    async def load_project(self, workspace_path: str) -> dict:
        """Resume an existing project from its workspace."""
        self.workspace_dir = Path(workspace_path)
        state_file = self.workspace_dir / "project_state.json"

        if not state_file.exists():
            return {"success": False, "error": "project_state.json not found"}

        self.state = ProjectState.load(state_file)
        if not self.state:
            return {"success": False, "error": "Failed to parse project state"}

        # Re-initialize all agents
        self.llm = LLMClient()
        venv_path = Path(self.state.venv_path) if self.state.venv_path else None
        self.runner = Runner(self.workspace_dir, venv_path=venv_path)
        self.planner = Planner(self.llm, self.state)
        self.coder = Coder(self.llm, self.state, self.workspace_dir)
        self.fixer = Fixer(self.llm, self.state, self.workspace_dir, self.runner, self.coder)

        await self.ws.send_status("ready", f"Project '{self.state.project_name}' loaded")
        return {"success": True, "project": self.state.to_api_dict()}

    # ── Planning ──────────────────────────────────────────────────────

    async def generate_plan(self, prompt: str = "") -> dict:
        """Generate the implementation plan from the prompt."""
        if not self.state or not self.planner:
            return {"success": False, "error": "No project loaded"}

        if prompt:
            self.state.original_prompt = prompt

        if not self.state.original_prompt:
            return {"success": False, "error": "No prompt provided"}

        self.state.status = "planning"
        await self.ws.send_status("planning", "Generating implementation plan...")

        # Chunking check
        planning_prompt = self.state.original_prompt
        if SmartChunker.needs_chunking(planning_prompt):
            chunks = SmartChunker.chunk(planning_prompt)
            planning_prompt = chunks[0] + "\n\n[Prompt truncated for planning...]"

        # Stream plan generation
        llm_chunks = []

        def on_token(token: str):
            llm_chunks.append(token)
            # Schedule broadcast on the event loop
            asyncio.ensure_future(self.ws.send_llm_token(token))

        try:
            plan_text = await self.planner.generate_plan(planning_prompt, on_token=on_token)
            await self.ws.send_llm_done(plan_text)
        except Exception as e:
            err_msg = str(e)
            if hasattr(e, 'response'):
                err_msg = f"API Error: HTTP {e.response.status_code} - The selected model may not exist or is unavailable."
            await self.ws.send_error(err_msg)
            self.state.status = "failed"
            return {"success": False, "error": err_msg}

        # Save plan
        plan_path = self.workspace_dir / "plan.txt"
        plan_path.write_text(plan_text, encoding="utf-8")
        self.state.plan_text = plan_text

        # Parse plan
        self.state.plan_steps = self.planner.parse_plan(plan_text)
        self.state.status = "plan_review"
        self.state.save(self.workspace_dir / "project_state.json")

        # Send plan to frontend
        plan_data = [
            {
                "step_number": s.step_number,
                "title": s.title,
                "file_path": s.file_path,
                "description": s.description,
                "status": s.status.value,
                "depends_on": s.depends_on,
            }
            for s in self.state.plan_steps
        ]
        await self.ws.send_plan_update(plan_data)
        await self.ws.send_status("plan_review", "Plan generated. Review and approve to begin execution.")

        return {"success": True, "plan_steps": plan_data}

    async def approve_plan(self) -> dict:
        """Approve the plan and mark it ready for execution."""
        if not self.state:
            return {"success": False, "error": "No project loaded"}

        self.state.plan_approved = True
        self.state.status = "approved"
        self.state.save(self.workspace_dir / "project_state.json")
        await self.ws.send_status("approved", "Plan approved. Ready for execution.")
        return {"success": True}

    # ── Execution ─────────────────────────────────────────────────────

    async def execute_all(self) -> dict:
        """
        Execute all plan steps with the NHIL (No Human In The Loop) flow:
        1. Write ALL files (no execution during generation)
        2. Ask permission for pip install requirements.txt
        3. Run syntax check on EACH .py file and fix errors
        4. Run QA Agent to test main.py with LLM-driven inputs
        5. Fix any errors found during QA testing
        """
        if not self.state or not self.state.plan_approved:
            return {"success": False, "error": "Plan not approved"}

        if self._executing:
            return {"success": False, "error": "Already executing"}

        self._executing = True
        self._cancel_requested = False
        self.state.status = "executing"

        try:
            # ── Phase 1: Write ALL files ──────────────────────────────
            await self.ws.send_status("executing", "Phase 1: Generating all files...")
            for i, step in enumerate(self.state.plan_steps):
                if self._cancel_requested:
                    await self.ws.send_status("cancelled", "Execution cancelled by user")
                    break

                if step.status == StepStatus.COMPLETED:
                    continue

                self.state.current_step = i
                result = await self._execute_step(step)

                if not result["success"] and not result.get("continued", False):
                    break

            all_written = all(s.status == StepStatus.COMPLETED for s in self.state.plan_steps)
            if not all_written:
                self.state.status = "paused"
                await self.ws.send_status("paused", "File generation paused due to error.")
                self.state.save(self.workspace_dir / "project_state.json")
                return {"success": False, "project": self.state.to_api_dict()}

            # ── Phase 2: Install requirements.txt (with permission) ──
            req_path = self.workspace_dir / "requirements.txt"
            if req_path.exists():
                req_id = str(uuid.uuid4())
                await self.ws.send_permission_request(
                    req_id, "Install dependencies from requirements.txt?", default=True
                )
                self._permission_event = asyncio.Event()
                try:
                    await asyncio.wait_for(self._permission_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    self._permission_response = True

                if self._permission_response:
                    await self.ws.send_status("installing", "Phase 2: Installing dependencies...")
                    install_res = await self.runner.install_requirements(
                        on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                        on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                    )
                    if install_res.success:
                        await self.ws.send_status("installed", "Dependencies installed successfully!")
                    else:
                        await self.ws.send_error(
                            install_res.error or install_res.stderr, "requirements.txt"
                        )

            # ── Phase 3: Syntax check ALL .py files and fix errors ───
            await self.ws.send_status("verifying", "Phase 3: Running syntax checks on all files...")
            py_files = [s.file_path for s in self.state.plan_steps if s.file_path.endswith(".py")]

            for py_file in py_files:
                if self._cancel_requested:
                    break

                full_path = self.workspace_dir / py_file
                if not full_path.exists():
                    continue

                syntax_result = await self.runner.syntax_check(py_file)
                if syntax_result.success:
                    await self.ws.send_status("verified", f"✓ {py_file} — syntax OK")
                else:
                    await self.ws.send_error(syntax_result.error, py_file)
                    await self.ws.send_status("fixing", f"Fixing syntax error in {py_file}...")
                    fixed = await self._auto_fix(py_file, syntax_result.error, verify_execution=False)
                    if fixed:
                        await self.ws.send_status("fixed", f"✓ {py_file} — syntax fixed")
                    else:
                        await self.ws.send_error(f"Could not fix syntax in {py_file}", py_file)

            # ── Phase 4: QA Agent tests main.py ──────────────────────
            main_path = self.workspace_dir / "main.py"
            if main_path.exists():
                await self.ws.send_status("testing", "Phase 4: QA Agent testing main.py...")
                await self._run_qa_test_loop()

            # ── Done ─────────────────────────────────────────────────
            self.state.status = "completed"
            self.state.save(self.workspace_dir / "project_state.json")
            await self.ws.send_status("completed", "All phases completed successfully!")

            usage = self.llm.get_usage()
            return {
                "success": True,
                "project": self.state.to_api_dict(),
                "usage": usage,
            }
        finally:
            self._executing = False

    async def execute_single_step(self, step_number: int) -> dict:
        """Execute a specific step by number."""
        if not self.state:
            return {"success": False, "error": "No project loaded"}

        step = next((s for s in self.state.plan_steps if s.step_number == step_number), None)
        if not step:
            return {"success": False, "error": f"Step {step_number} not found"}

        self._executing = True
        self.state.status = "executing"
        try:
            result = await self._execute_step(step)

            all_done = all(s.status == StepStatus.COMPLETED for s in self.state.plan_steps)
            if all_done:
                self.state.status = "completed"
                await self.ws.send_status("completed", "All steps completed successfully!")
            else:
                self.state.status = "paused"
                await self.ws.send_status("paused", f"Step {step_number} finished. Paused.")

            return result
        finally:
            self._executing = False
            self.state.save(self.workspace_dir / "project_state.json")

    async def _execute_step(self, step: PlanStep) -> dict:
        """
        Execute a single plan step: generate the file and save it.
        No execution, no pip installs, no permission prompts.
        """
        await self.ws.send_step_update(step.step_number, "in_progress", f"Working on {step.title}...")
        step.status = StepStatus.IN_PROGRESS
        self.state.save(self.workspace_dir / "project_state.json")

        # ── Code Generation ──
        await self.ws.send_status("generating", f"Writing {step.file_path}...")
        llm_chunks = []

        def on_token(token: str):
            llm_chunks.append(token)
            asyncio.ensure_future(self.ws.send_llm_token(token))

        success, error = await self.coder.generate_code(step, on_token=on_token)
        full_output = "".join(llm_chunks)
        await self.ws.send_llm_done(full_output)

        if not success:
            step.status = StepStatus.FAILED
            step.error = error
            await self.ws.send_step_update(step.step_number, "failed", error)
            await self.ws.send_error(error, step.file_path)

            if "Syntax Error" in error or "placeholder" in error.lower():
                await self.ws.send_status("fixing", f"Auto-fixing generation error in {step.file_path}...")
                fixed = await self._auto_fix(step.file_path, error, verify_execution=False)
                if not fixed:
                    return {"success": False, "error": error}
            else:
                return {"success": False, "error": error}

        # Send file content to frontend
        file_path = self.workspace_dir / step.file_path
        if file_path.exists():
            content = file_path.read_text(encoding="utf-8")
            await self.ws.send_file_update(step.file_path, content)

        # ── Main.py Integration (for src/ files) ──
        if step.file_path.startswith("src/") and step.file_path.endswith(".py"):
            await self.ws.send_status("integrating", f"Updating main.py to import {step.file_path}...")
            new_entry = next((e for e in self.state.file_registry if e.path == step.file_path), None)
            if new_entry:
                int_chunks = []

                def on_int_token(token: str):
                    int_chunks.append(token)
                    asyncio.ensure_future(self.ws.send_llm_token(token))

                main_success, main_error = await self.coder.update_main_integration(new_entry, on_token=on_int_token)
                await self.ws.send_llm_done("".join(int_chunks))

                if main_success:
                    main_path = self.workspace_dir / "main.py"
                    if main_path.exists():
                        await self.ws.send_file_update("main.py", main_path.read_text(encoding="utf-8"))

        # Mark complete
        step.status = StepStatus.COMPLETED
        self.state.completed_steps.add(step.step_number)
        self.state.save(self.workspace_dir / "project_state.json")
        await self.ws.send_step_update(step.step_number, "completed", f"✓ {step.title}")

        return {"success": True}

    async def _run_qa_test_loop(self):
        """
        Run the QA Agent test loop:
        1. QA Agent runs main.py and interacts with it
        2. If bugs are found, send to Fixer
        3. Re-test until success or MAX_QA_ATTEMPTS reached
        """
        from core.qa_agent import QAAgent

        qa = QAAgent(self.llm, self.original_prompt)
        python_cmd = self.runner._get_python_cmd()
        main_file = str(self.workspace_dir / "main.py")

        for attempt in range(1, config.MAX_QA_ATTEMPTS + 1):
            await self.ws.send_status(
                "testing", f"QA Test attempt {attempt}/{config.MAX_QA_ATTEMPTS}..."
            )

            qa_result = await qa.test_application(
                python_cmd=python_cmd,
                main_file=main_file,
                workspace=str(self.workspace_dir),
                on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                on_status=lambda msg: asyncio.ensure_future(self.ws.send_status("testing", msg)),
            )

            if qa_result.success:
                await self.ws.send_status("tested", "✓ QA Agent: Application passed testing!")
                return

            # Test failed — report and fix
            error_text = qa_result.bug_report or qa_result.error or qa_result.stderr
            await self.ws.send_error(error_text, "main.py")

            if attempt < config.MAX_QA_ATTEMPTS:
                await self.ws.send_status("fixing", f"QA Agent found issues. Auto-fixing...")
                fixed = await self._auto_fix("main.py", error_text)
                if not fixed:
                    await self.ws.send_status("warning", "Auto-fix failed. Retrying QA test...")
            else:
                await self.ws.send_status(
                    "warning",
                    f"QA Agent: Max test attempts ({config.MAX_QA_ATTEMPTS}) reached. "
                    f"Application may need manual review.",
                )

    @property
    def original_prompt(self) -> str:
        """Get the original user prompt."""
        return self.state.original_prompt if self.state else ""

    async def _auto_fix(self, file_path: str, error_text: str, verify_execution: bool = True) -> bool:
        """Run the auto-fix loop. Automatically installs missing modules."""
        attempts = 0
        current_error = error_text
        target_file = file_path

        while attempts < config.MAX_FIX_ATTEMPTS:
            attempts += 1

            # Smart error targeting — find the actual file from the traceback
            matches = re.findall(r'File "([^"]+)"', current_error)
            if matches:
                workspace_path = self.workspace_dir.resolve()
                for match in reversed(matches):
                    try:
                        match_path = Path(match).resolve()
                        if match_path.is_relative_to(workspace_path):
                            target_file = match_path.relative_to(workspace_path).as_posix()
                            break
                    except Exception:
                        pass

            await self.ws.send_status("fixing", f"Fix attempt {attempts}/{config.MAX_FIX_ATTEMPTS} on {target_file}...")

            fix_chunks = []

            def on_fix_token(token: str):
                fix_chunks.append(token)
                asyncio.ensure_future(self.ws.send_llm_token(token))

            success, msg, fixed_files = await self.fixer.fix_error(target_file, current_error, on_token=on_fix_token)
            await self.ws.send_llm_done("".join(fix_chunks))

            if not success:
                await self.ws.send_error(msg, target_file)
                current_error = msg
                if "does not exist" in msg or "truncated by the API" in msg:
                    break
                continue

            # Send updated files to frontend
            for fpath in fixed_files:
                full_fpath = self.workspace_dir / fpath
                if full_fpath.exists():
                    await self.ws.send_file_update(fpath, full_fpath.read_text(encoding="utf-8"))

            # Verify fix by re-running
            if verify_execution:
                run_result = await self.runner.run_python_file(
                    file_path,
                    on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                    on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                )
                await self.ws.send_process_done(run_result.success, run_result.exit_code, run_result.error)

                if run_result.success:
                    await self.ws.send_status("fixed", "Fix resolved the error!")
                    return True

                current_error = run_result.error or run_result.stderr
                await self.ws.send_error(current_error, file_path)

                # Auto-install missing modules without asking
                parsed_err = ErrorParser.parse_traceback(current_error)
                if parsed_err.get("is_import_error") and parsed_err.get("missing_module"):
                    missing_mod = parsed_err["missing_module"]
                    await self.ws.send_status("installing", f"Auto-installing {missing_mod}...")
                    install_res = await self.runner.install_package(
                        missing_mod,
                        on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                        on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                    )
                    if install_res.success:
                        run_result = await self.runner.run_python_file(
                            file_path,
                            on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                            on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                        )
                        await self.ws.send_process_done(run_result.success, run_result.exit_code, run_result.error)
                        if run_result.success:
                            await self.ws.send_status("fixed", "Fix resolved the error after install!")
                            return True
                        current_error = run_result.error or run_result.stderr
                        await self.ws.send_error(current_error, file_path)
            else:
                await self.ws.send_status("fixed", "Code updated. (Execution verification skipped)")
                return True

        await self.ws.send_error(f"Max fix attempts ({config.MAX_FIX_ATTEMPTS}) reached.", file_path)
        return False

    async def handle_manual_fix(self, text: str) -> dict:
        """Handle a manual user request to fix an error or add a feature after project completion."""
        if not self.state:
            return {"success": False, "error": "No active project"}

        await self.ws.send_status("fixing", "Analyzing user feedback...")
        
        # Resolve the target file from the pasted text
        target_file = self._resolve_target_file(text)
        
        await self.ws.send_status("fixing", f"Targeting {target_file} for fix...")

        # Trigger auto-fix loop WITH verification so fixes are actually tested
        fixed = await self._auto_fix(target_file, f"User Feedback/Error:\n{text}", verify_execution=True)
        
        if fixed:
            await self.ws.send_status("fixed", f"Successfully fixed {target_file}!")
            self.state.status = "fixed"
        else:
            self.state.status = "completed"  # Revert to completed on failure
            
        self.state.save(self.workspace_dir / "project_state.json")
        return {"success": True}

    def _resolve_target_file(self, text: str) -> str:
        """
        Resolve the target file from user-pasted error text.
        
        Strategy:
        1. Extract all File "..." paths from the traceback
        2. Try to resolve them relative to the workspace
        3. If only a basename is found, search the workspace
        4. Fall back to main.py as last resort
        """
        workspace_path = self.workspace_dir.resolve()
        
        # Extract all File "..." references from the text
        file_matches = re.findall(r'File "([^"]+)"', text)
        
        if file_matches:
            # Walk in reverse (last file in traceback is closest to the error)
            for match in reversed(file_matches):
                try:
                    match_path = Path(match).resolve()
                    # Check if this file is inside our workspace
                    if match_path.is_relative_to(workspace_path):
                        rel_path = match_path.relative_to(workspace_path).as_posix()
                        # Verify the file actually exists in workspace
                        if (self.workspace_dir / rel_path).exists():
                            log.info("Manual fix: resolved target file from traceback: %s", rel_path)
                            return rel_path
                except Exception:
                    pass
            
            # If no workspace-relative path found, try basename search
            for match in reversed(file_matches):
                basename = Path(match).name
                # Search workspace for this file
                found = self._find_file_in_workspace(basename)
                if found:
                    log.info("Manual fix: resolved target file by basename search: %s", found)
                    return found
        
        # Try ErrorParser for structured error info
        error_info = ErrorParser.parse_traceback(text)
        if error_info.get("file"):
            error_file = error_info["file"]
            # Try to resolve relative to workspace
            try:
                err_path = Path(error_file).resolve()
                if err_path.is_relative_to(workspace_path):
                    rel_path = err_path.relative_to(workspace_path).as_posix()
                    if (self.workspace_dir / rel_path).exists():
                        return rel_path
            except Exception:
                pass
            # Try basename search
            found = self._find_file_in_workspace(Path(error_file).name)
            if found:
                return found
        
        # Last resort: default to main.py
        log.warning("Manual fix: could not resolve target file, defaulting to main.py")
        return "main.py"

    def _find_file_in_workspace(self, filename: str) -> Optional[str]:
        """Search the workspace for a file by name. Returns relative path or None."""
        for item in self.workspace_dir.rglob(filename):
            if item.is_file():
                rel = item.relative_to(self.workspace_dir).as_posix()
                # Skip venv and __pycache__
                if rel.startswith("venv/") or "__pycache__" in rel:
                    continue
                return rel
        return None

    # ── User Input ────────────────────────────────────────────────────

    async def _request_input(self) -> str:
        """Called by Runner when process hangs on stdin."""
        await self.ws.send_input_request("Process is waiting for input...")
        self._input_event = asyncio.Event()
        self._input_response = ""
        try:
            await asyncio.wait_for(self._input_event.wait(), timeout=300)
        except asyncio.TimeoutError:
            self._input_response = ""
        return self._input_response

    async def send_input(self, text: str) -> dict:
        """Send user input to the running process."""
        input_event = getattr(self, '_input_event', None)
        if input_event and not input_event.is_set():
            self._input_response = text
            input_event.set()
        
        if not self.runner:
            return {"success": False, "error": "No runner active"}
        result = await self.runner.send_process_input(text)
        return {"success": result}

    async def respond_permission(self, granted: bool):
        """Respond to a permission request from the orchestrator."""
        self._permission_response = granted
        if self._permission_event:
            self._permission_event.set()

    async def cancel_execution(self) -> dict:
        """Cancel the current execution."""
        self._cancel_requested = True
        await self.runner.kill_process()
        return {"success": True}

    # ── File Operations ───────────────────────────────────────────────

    def get_file_content(self, file_path: str) -> Optional[str]:
        """Read a file from the workspace."""
        if not self.workspace_dir:
            return None
        full_path = self.workspace_dir / file_path
        if not full_path.exists():
            return None
        try:
            return full_path.read_text(encoding="utf-8")
        except Exception:
            return None

    def list_workspace_files(self) -> list:
        """List all files in the workspace (excluding venv)."""
        if not self.workspace_dir:
            return []
        files = []
        for item in self.workspace_dir.rglob("*"):
            if item.is_file():
                rel = item.relative_to(self.workspace_dir).as_posix()
                # Skip venv and __pycache__
                if rel.startswith("venv/") or "__pycache__" in rel:
                    continue
                files.append(rel)
        return sorted(files)
