"""
Orchestrator — class-based orchestrator that can be driven by both CLI and Web UI.

Replaces the old procedural main.py with a stateful class that uses callbacks
for all user interactions. This means the same orchestrator works with both
the terminal UI and the FastAPI web backend.

Updated for Context Agent v2 (8-Layer Cognitive Architecture) with Project Brain,
Hierarchical Planning, and Engineering Agents.
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
from core.planners.master_planner import MasterPlanner
from core.coder import Coder
from core.runner import Runner, ErrorParser
from core.fixer import Fixer
from core.context import SmartChunker
from core.brain.project_brain import ProjectBrain
from core.retrieval.context_engine import ContextEngine
from core.agents.integration_agent import IntegrationAgent
from core.agents.summarizer import SummarizerAgent
from core.agents.architect_agent import ArchitectAgent
from core.agents.understanding_agent import UnderstandingAgent
from core.agents.test_generator import TestGeneratorAgent
from core.checkpoint import CheckpointManager
from core.analyzer import IncrementalVerifier
from core.ingestion.ingester import RepositoryIngester
from core.ingestion.doc_ingester import UserDocumentIngester
from core.templates.template_engine import TemplateEngine
from models.state import ProjectState, StepStatus, PlanStep
from models.hierarchy import ArchitectureSpec, ModuleSpec
from backend.ws_manager import ConnectionManager
from backend.chat_agent import ChatAgent

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
        self.master_planner: Optional[MasterPlanner] = None
        self.coder: Optional[Coder] = None
        self.runner: Optional[Runner] = None
        self.fixer: Optional[Fixer] = None
        
        # V2 specific
        self.brain: Optional[ProjectBrain] = None
        self.context_engine: Optional[ContextEngine] = None
        self.integration_agent: Optional[IntegrationAgent] = None
        self.summarizer: Optional[SummarizerAgent] = None
        self.architect: Optional[ArchitectAgent] = None
        self.test_generator: Optional[TestGeneratorAgent] = None
        self.verifier: Optional[IncrementalVerifier] = None
        self.ingester: Optional[RepositoryIngester] = None
        self.doc_ingester: Optional[UserDocumentIngester] = None
        self.chat_agent: Optional[ChatAgent] = None
        self.understanding_agent: Optional[UnderstandingAgent] = None
        self.template_engine: Optional[TemplateEngine] = None
        
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

        # Paused state (V3: Resilient Fixer)
        self._paused = False
        self._paused_step: Optional[PlanStep] = None
        self._paused_file: Optional[str] = None
        self._retry_event: Optional[asyncio.Event] = None
        self._skip_requested = False

        # Manual Pause/Resume control
        self._manual_pause_event = asyncio.Event()
        self._manual_pause_event.set()  # Default to running (not paused)
        
        # Concurrency locks
        self._ingestion_lock = asyncio.Lock()
        self._planning_lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()

    # ── Project Lifecycle ─────────────────────────────────────────────

    async def create_project(self, name: str, prompt: str = "", target_dir: str = None, mode: str = "build") -> dict:
        """Create a new project workspace."""
        self.state = ProjectState()
        self.state.project_name = name
        self.state.original_prompt = prompt
        self.state.project_mode = mode

        # Create workspace
        if target_dir:
            self.workspace_dir = Path(target_dir).resolve()
        else:
            safe_name = "".join(c for c in name if c.isalnum() or c in (' ', '-', '_')).strip().replace(' ', '_')
            if not safe_name:
                safe_name = f"project_{uuid.uuid4().hex[:8]}"
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

        # Initialize V2 subsystems
        self.brain = ProjectBrain(self.workspace_dir)
        self.state.brain_path = str(self.brain.brain_dir)
        self.context_engine = ContextEngine(self.brain, self.state)
        
        # Initialize agents
        self.master_planner = MasterPlanner(self.llm)
        self.coder = Coder(self.llm, self.state, self.workspace_dir)
        self.fixer = Fixer(self.llm, self.state, self.workspace_dir, self.runner, self.coder)
        self.integration_agent = IntegrationAgent(self.llm, self.brain)
        self.summarizer = SummarizerAgent(self.llm)
        self.architect = ArchitectAgent(self.llm)
        self.test_generator = TestGeneratorAgent(self.llm)
        self.understanding_agent = UnderstandingAgent(self.llm, self.brain)
        venv_path = Path(self.state.venv_path) if self.state.venv_path else None
        self.verifier = IncrementalVerifier(self.workspace_dir, venv_path)
        self.ingester = RepositoryIngester(self.workspace_dir, self.brain, self.summarizer, self.understanding_agent, state=self.state)
        self.doc_ingester = UserDocumentIngester(self.llm, self.brain.semantic, self.state)
        self.chat_agent = ChatAgent(self.llm, self.ws, self.state)
        self.context_engine = ContextEngine(self.brain, self.ws)
        self.template_engine = TemplateEngine()

        self.state.status = "idle"
        self.state.save(self.workspace_dir / "project_state.json")

        # Auto-ingest if there are files in target_dir (prevent isolated environment hallucination)
        has_files = any(
            f.name not in [".venv", "venv", "__pycache__", ".git", ".agent_brain"]
            for f in self.workspace_dir.iterdir()
        )
        if has_files:
            asyncio.create_task(self.ingest_codebase())

        await self.ws.send_status("ready", f"Project '{name}' created")
        return {"success": True, "project": self.state.to_api_dict()}
        
    async def auto_build_from_file(self, file_path: str, prompt: str):
        """Automatically generate plan from uploaded file and start execution."""
        try:
            await self.ws.send_status("planning", "Auto-generating plan from uploaded document...")
            res = await self.generate_plan(prompt, [file_path])
            if res.get("success"):
                await self.ws.send_status("planning", "Plan generated successfully. Auto-approving...")
                app_res = await self.approve_plan()
                if app_res.get("success"):
                    await self.ws.send_status("executing", "Starting execution automatically...")
                    await self.execute_all()
                else:
                    await self.ws.send_status("failed", "Failed to auto-approve plan.")
            else:
                await self.ws.send_status("failed", f"Failed to generate plan: {res.get('error')}")
        except Exception as e:
            log.error("auto_build_from_file error: %s", repr(e))
            await self.ws.send_error(f"Auto build failed: {str(e)}")

    async def load_project(self, workspace_path: str) -> dict:
        """Resume an existing project from its workspace."""
        self.workspace_dir = Path(workspace_path)
        state_file = self.workspace_dir / "project_state.json"

        if not state_file.exists():
            return {"success": False, "error": "project_state.json not found"}

        self.state = ProjectState.load(state_file)
        if not self.state:
            return {"success": False, "error": "Failed to parse project state"}
            
        if self.state.status == "executing":
            self.state.status = "paused"
            self.state.save(state_file)

        # Re-initialize all agents
        self.llm = LLMClient()
        venv_path = Path(self.state.venv_path) if self.state.venv_path else None
        self.runner = Runner(self.workspace_dir, venv_path=venv_path)
        
        # Re-initialize V2 subsystems
        self.brain = ProjectBrain(self.workspace_dir)
        self.context_engine = ContextEngine(self.brain, self.ws)
        
        self.master_planner = MasterPlanner(self.llm)
        self.coder = Coder(self.llm, self.state, self.workspace_dir)
        self.fixer = Fixer(self.llm, self.state, self.workspace_dir, self.runner, self.coder)
        self.integration_agent = IntegrationAgent(self.llm, self.brain)
        self.summarizer = SummarizerAgent(self.llm)
        self.architect = ArchitectAgent(self.llm)
        self.test_generator = TestGeneratorAgent(self.llm)
        self.understanding_agent = UnderstandingAgent(self.llm, self.brain)
        self.verifier = IncrementalVerifier(self.workspace_dir, venv_path)
        self.ingester = RepositoryIngester(self.workspace_dir, self.brain, self.summarizer, self.understanding_agent, state=self.state)
        self.doc_ingester = UserDocumentIngester(self.llm, self.brain.semantic, self.state)
        self.chat_agent = ChatAgent(self.llm, self.ws, self.state)
        self.template_engine = TemplateEngine()

        await self.ws.send_status("ready", f"Project '{self.state.project_name}' loaded")
        return {"success": True, "project": self.state.to_api_dict()}

    async def ingest_codebase(self) -> dict:
        """Trigger codebase ingestion for the currently loaded project."""
        if not self.state or not self.ingester:
            return {"success": False, "error": "No project loaded"}

        if self._ingestion_lock.locked():
            await self.ws.send_status("warning", "Ingestion is already running.")
            return {"success": False, "error": "Already ingesting"}

        async with self._ingestion_lock:
            await self.ws.send_status("ingesting", "Starting Codebase Ingestion Pipeline...")
            
            def on_status(msg: str):
                asyncio.create_task(self.ws.send_status("ingesting", msg))
                
            def on_progress(current: int, total: int, current_file: str):
                if total > 0:
                    percent = (current / total) * 100
                    asyncio.create_task(self.ws.send_progress(percent, f"Ingesting: {current_file}"))
                
            try:
                success = await self.ingester.ingest_repository(on_status=on_status, on_progress=on_progress)
                
                if success:
                    if hasattr(self.brain, 'latest_architecture_notes'):
                        # Save to state memory for planners to reference
                        if not hasattr(self.state, 'ingested_architecture_notes'):
                            self.state.ingested_architecture_notes = ""
                        self.state.ingested_architecture_notes = self.brain.latest_architecture_notes
                    self.state.save(self.workspace_dir / "project_state.json")
                    
                    await self.ws.send_status("ready", "Codebase ingestion completed successfully.")
                    return {"success": True}
                else:
                    await self.ws.send_status("error", "Codebase ingestion failed.")
                    return {"success": False, "error": "Ingestion failed"}
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                log.error(f"Ingestion aborted due to unexpected error:\n{error_details}")
                await self.ws.send_status("error", f"Codebase ingestion failed unexpectedly: {str(e)}")
                return {"success": False, "error": str(e)}

    # ── Planning ──────────────────────────────────────────────────────

    async def generate_plan(self, prompt: str = "", file_paths: list[str] = None) -> dict:
        """Generate the implementation plan using V2 Hierarchical Planning."""
        await self._planning_lock.acquire()
        try:
            if self._ingestion_lock.locked():
                await self.ws.send_status("planning", "Waiting for codebase ingestion to finish before planning...")
                
            async with self._ingestion_lock:
                if not self.state or not self.master_planner:
                    return {"success": False, "error": "No project loaded"}

            if prompt:
                self.state.original_prompt = prompt
                self.state.chat_history.append({"role": "user", "content": prompt})
                self.state.save(self.workspace_dir / "project_state.json")
            if not self.state.original_prompt:
                return {"success": False, "error": "No prompt provided"}

            if file_paths:
                for fp in file_paths:
                    from pathlib import Path
                    await self.doc_ingester.ingest_document(fp, Path(fp).name, on_status=self.ws.send_status)
                
                extracted_reqs = await self.chat_agent.process_task(
                    "Extract a detailed master specification and architecture plan from these documents to build the software.",
                    self.state.user_documents, 
                    return_result=True
                )
                self.state.global_master_summary = extracted_reqs
                self.state.save(self.workspace_dir / "project_state.json")


            planning_prompt = self.state.original_prompt
            if getattr(self.state, "ingested_architecture_notes", ""):
                planning_prompt = f"Existing Codebase Architecture Context:\n{self.state.ingested_architecture_notes}\n\nUSER REQUEST:\n{planning_prompt}"
                
            if getattr(self.state, "global_master_summary", ""):
                planning_prompt = f"GLOBAL MASTER SPECIFICATION (from uploaded documents):\n{self.state.global_master_summary}\n\n{planning_prompt}"
            elif hasattr(self.state, "user_documents") and self.state.user_documents:
                summaries = [doc.master_summary for doc in self.state.user_documents]
                planning_prompt = f"PROJECT MASTER SPECIFICATIONS (from uploaded documents):\n" + "\n---\n".join(summaries) + f"\n\n{planning_prompt}"
                
            if getattr(self.state, "project_mode", "") == "ingest":
                planning_prompt += "\n\nCRITICAL RULE FOR INGESTION MODE: You MUST prioritize editing existing files (like the root main.py). Do NOT create new files or new entry points unless absolutely necessary to avoid breaking the existing architecture. Your goal is to integrate directly into the old code."
                
            if SmartChunker.needs_chunking(planning_prompt):
                chunks = SmartChunker.chunk(planning_prompt)
                planning_prompt = chunks[0] + "\n\n[Prompt truncated for planning...]"

            # Determine Complexity / Epics
            self.state.status = "architecting"
            await self.ws.send_status("planning", "Stage 1: Determining complexity and bounded domains (Epics)...")
            
            epic_chunks = []
            def on_epic_token(token: str):
                epic_chunks.append(token)
                asyncio.ensure_future(self.ws.send_llm_token(token))
                
            try:
                entry_point, epics = await self.master_planner.generate_epic_queue(planning_prompt, on_token=on_epic_token)
                self.state.project_entry_point = entry_point
                self.state.epic_queue = epics
                if epics:
                    self.state.project_scale = epics[0].scale_estimate.value
                await self.ws.send_llm_done("".join(epic_chunks))
            except Exception as e:
                err_msg = str(e)
                await self.ws.send_error(f"Complexity Generation Error: {err_msg}")
                self.state.status = "failed"
                return {"success": False, "error": err_msg}

            is_massive = self.state.project_scale in ["large", "massive"]

            if not is_massive:
                # ── Monolithic Planning for SIMPLE/MEDIUM projects ──
                await self.ws.send_status("planning", "Project is simple/medium. Generating full architecture...")
                
                arch_chunks = []
                def on_arch_token(token: str):
                    arch_chunks.append(token)
                    asyncio.ensure_future(self.ws.send_llm_token(token))
                    
                try:
                    arch_spec = await self.master_planner.generate_vision(planning_prompt, on_token=on_arch_token)
                    arch_spec = await self.master_planner.generate_services(arch_spec, planning_prompt, on_token=on_arch_token)
                    self.brain.ingest_architecture(arch_spec, self.state.project_name)
                    self.state.architecture_text = self.master_planner.format_vision_for_display(arch_spec)
                    self.state.plan_steps = self.master_planner.flatten_to_plan_steps(arch_spec)
                except Exception as e:
                    return {"success": False, "error": str(e)}
            else:
                # ── JIT Epic Planning for LARGE/MASSIVE projects ──
                await self.ws.send_status("planning", f"Project is {self.state.project_scale.upper()}. Using JIT Epic Planning...")
                
                # Format Epics for display instead of a full architecture
                lines = [f"# {self.state.project_name} - {self.state.project_scale.upper()} Scale"]
                lines.append("\nThis is a massive project. It will be built iteratively via the following Epics:\n")
                for i, epic in enumerate(self.state.epic_queue):
                    lines.append(f"## Epic {i+1}: {epic.name}")
                    lines.append(f"Purpose: {epic.purpose}")
                    lines.append(f"API Contract: {', '.join(epic.public_api_contract)}")
                    if epic.depends_on_epics:
                        lines.append(f"Depends on: {', '.join(epic.depends_on_epics)}")
                    lines.append("")
                    
                self.state.architecture_text = "\n".join(lines)
                self.state.plan_steps = []  # Will be populated JIT during execution
                
            arch_path = self.workspace_dir / "architecture.md"
            arch_path.write_text(self.state.architecture_text, encoding="utf-8")
            
            # Generate simple plan_text string for backward compatibility with frontend
            plan_lines = []
            for s in self.state.plan_steps:
                plan_lines.append(f"Step {s.step_number}: {s.title}\nFILE: {s.file_path}\nDESCRIPTION: {s.description}\n")
            self.state.plan_text = "\n".join(plan_lines)
            plan_path = self.workspace_dir / "plan.txt"
            plan_path.write_text(self.state.plan_text, encoding="utf-8")

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
            await self.ws.send_status("plan_review", "Hierarchical Plan generated. Review and approve to begin execution.")

            return {"success": True, "plan_steps": plan_data}
        except Exception as e:
            log.error(f"Planning failed: {str(e)}")
            await self.ws.send_status("error", f"Planning failed: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            self._planning_lock.release()

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
        await self._execution_lock.acquire()
        try:
            if not self.state or not self.state.plan_approved:
                return {"success": False, "error": "Plan not approved"}

            if self._executing:
                return {"success": False, "error": "Already executing"}

            self._executing = True
            self._cancel_requested = False
            self.state.status = "executing"

            ckpt = CheckpointManager.load(self.workspace_dir)
            resume_epic_id = None
            if ckpt:
                resume_epic_id = ckpt.get("current_epic_id")
                await self.ws.send_status("resuming", "Resuming from checkpoint...")

            epics_to_run = self.state.epic_queue if self.state.project_scale in ["large", "massive"] else [None]
            
            for epic_idx, epic in enumerate(epics_to_run):
                await self._manual_pause_event.wait()
                if self._cancel_requested:
                    break
                    
                if epic:
                    if resume_epic_id and epic.id != resume_epic_id:
                        continue
                    resume_epic_id = None
                    
                    has_valid_plan = bool(self.state.plan_steps and self.state.current_epic_id == epic.id)
                    self.state.current_epic_id = epic.id
                    await self.ws.send_status("executing", f"--- Epic {epic_idx+1}/{len(epics_to_run)}: {epic.name} ---")
                    
                    # JIT Sprint Planning for this Epic
                    if has_valid_plan:
                        await self.ws.send_status("planning", f"Skipping Sprint Plan (already exists) for {epic.name}...")
                        
                        # Ingest the architecture into the graph in case it hasn't been (or the server restarted)
                        arch_spec = ArchitectureSpec(name=epic.name, subsystems=[epic.subsystem])
                        if self.brain:
                            self.brain.ingest_architecture(arch_spec, self.state.project_name)
                    else:
                        await self.ws.send_status("planning", f"JIT Planning for {epic.name}...")
                        
                        def on_sprint_token(token: str):
                            asyncio.ensure_future(self.ws.send_llm_token(token))
                            
                        epic = await self.master_planner.generate_sprint_plan(
                            epic, 
                            self.state.get_file_registry_string(), 
                            self.state.get_completed_summaries(),
                            self.state.project_entry_point,
                            on_token=on_sprint_token
                        )
                        
                        # Flatten just this epic to plan steps
                        arch_spec = ArchitectureSpec(name=epic.name, subsystems=[epic.subsystem])
                        new_steps = self.master_planner.flatten_to_plan_steps(arch_spec)
                        
                        start_offset = len(self.state.plan_steps)
                        for s in new_steps:
                            s.step_number += start_offset
                            s.epic_id = epic.id
                            
                        self.state.plan_steps.extend(new_steps)
                        
                        if self.brain:
                            self.brain.ingest_architecture(arch_spec, self.state.project_name)
                        
                        # Send updated plan to UI
                        plan_data = [
                            {"step_number": s.step_number, "title": s.title, "file_path": s.file_path, "status": s.status.value, "epic_id": getattr(s, "epic_id", None)}
                            for s in self.state.plan_steps
                        ]
                        await self.ws.send_plan_update(plan_data)
                        self.state.save(self.workspace_dir / "project_state.json")

                # ── Phase 0: Skeleton Scaffolding (Contract-First) ──────────────
                uncompleted_steps = [s for s in self.state.plan_steps if s.status != StepStatus.COMPLETED]
                if uncompleted_steps:
                    first_step = uncompleted_steps[0]
                    first_step.status = StepStatus.IN_PROGRESS
                    await self.ws.send_step_update(first_step.step_number, "in_progress", f"Scaffolding {first_step.title}...")
                    
                    await self.ws.send_status("scaffolding", "Phase 0: Generating Contract-First skeleton stubs...")
                    
                    # Convert PlanSteps to ModuleSpecs for ArchitectAgent, or use templates
                    CODE_EXTENSIONS = ('.py', '.js', '.jsx', '.ts', '.tsx')
                    modules = []
                    for step in uncompleted_steps:
                        if any(step.file_path.endswith(ext) for ext in CODE_EXTENSIONS):
                            template_name = self.template_engine.get_template_for_file(step.file_path)
                            if template_name:
                                # Provide context for template rendering
                                entity_name = Path(step.file_path).stem.replace("_model", "").replace("_service", "").replace("_controller", "").replace("_api", "").title().replace("_", "")
                                context = {
                                    "module_name": Path(step.file_path).stem,
                                    "entity_name": entity_name
                                }
                                rendered = self.template_engine.render(template_name, context)
                                if rendered:
                                    full_path = self.workspace_dir / step.file_path
                                    full_path.parent.mkdir(parents=True, exist_ok=True)
                                    full_path.write_text(rendered, encoding="utf-8")
                                    await self.ws.send_file_update(step.file_path, rendered)
                                    continue # Skip Architect for this file since template succeeded
                            
                            # Fallback to ArchitectAgent for unique files
                            modules.append(ModuleSpec(name=step.title, file_path=step.file_path, description=step.description))
                            
                    if modules:
                        def on_stub_token(token: str):
                            asyncio.ensure_future(self.ws.send_llm_token(token))
                        
                        stubs = await self.architect.generate_stubs(modules, on_token=on_stub_token)
                        
                        if self._cancel_requested:
                            await self.ws.send_status("cancelled", "Execution cancelled by user")
                            break
                            
                        for file_path, content in stubs.items():
                            full_path = self.workspace_dir / file_path
                            full_path.parent.mkdir(parents=True, exist_ok=True)
                            full_path.write_text(content, encoding="utf-8")
                            await self.ws.send_file_update(file_path, content)
                            
                        await self.ws.send_status("scaffolding", "Skeleton scaffolding complete (TDD Disabled).")

                # ── Phase 1: Write ALL files ──────────────────────────────
                await self.ws.send_status("executing", "Phase 1: Generating implementation logic...")
                for i, step in enumerate(self.state.plan_steps):
                    await self._manual_pause_event.wait()
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
            pkg_path_root = self.workspace_dir / "package.json"
            pkg_path_frontend = self.workspace_dir / "frontend" / "package.json"
            
            if req_path.exists() or pkg_path_root.exists() or pkg_path_frontend.exists():
                req_id = str(uuid.uuid4())
                await self.ws.send_permission_request(
                    req_id, "Install project dependencies (pip/npm)?", default=True
                )
                self._permission_event = asyncio.Event()
                try:
                    await asyncio.wait_for(self._permission_event.wait(), timeout=300)
                except asyncio.TimeoutError:
                    self._permission_response = True

                if self._permission_response:
                    await self.ws.send_status("installing", "Phase 2: Installing dependencies...")
                    
                    if req_path.exists():
                        install_res = await self.runner.install_requirements(
                            on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                            on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                        )
                        if install_res.success:
                            await self.ws.send_status("installed", "Python dependencies installed successfully!")
                        else:
                            await self.ws.send_error(
                                install_res.error or install_res.stderr, "requirements.txt"
                            )

                    if pkg_path_root.exists() or pkg_path_frontend.exists():
                        await self.ws.send_status("installing", "Phase 2: Installing npm dependencies...")
                        npm_res = await self.runner.install_npm_requirements(
                            on_stdout=lambda text: asyncio.ensure_future(self.ws.send_process_stdout(text)),
                            on_stderr=lambda text: asyncio.ensure_future(self.ws.send_process_stderr(text)),
                        )
                        if npm_res.success:
                            await self.ws.send_status("installed", "NPM dependencies installed successfully!")
                        else:
                            await self.ws.send_error(
                                npm_res.error or npm_res.stderr, "package.json"
                            )

            # ── Phase 4: QA Agent tests the Project ──────────────────────
            entry_file = self.state.project_entry_point or "main.py"
            main_path = self.workspace_dir / entry_file
            if main_path.exists():
                await self.ws.send_status("testing", f"Phase 4: QA Agent testing {entry_file}...")
                await self._run_qa_test_loop()

            # ── Done with all Epics ──────────────────────────────────────
            self.state.status = "completed"
            self.state.save(self.workspace_dir / "project_state.json")
            CheckpointManager.clear(self.workspace_dir)
            await self.ws.send_status("completed", "All phases completed successfully!")

            usage = self.llm.get_usage()
            return {
                "success": True,
                "project": self.state.to_api_dict(),
                "usage": usage,
            }
        except Exception as e:
            log.error(f"Execution pipeline failed: {str(e)}")
            await self.ws.send_status("error", f"Execution failed: {str(e)}")
            return {"success": False, "error": str(e)}
        finally:
            self._executing = False
            self._execution_lock.release()

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
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            log.error(f"Step execution aborted due to unexpected error:\n{error_details}")
            await self.ws.send_status("error", f"Step execution failed unexpectedly: {str(e)}")
            self.state.status = "failed"
            self.state.save(self.workspace_dir / "project_state.json")
            return {"success": False, "error": str(e)}
        finally:
            self._executing = False
            self.state.save(self.workspace_dir / "project_state.json")

    async def _execute_step(self, step: PlanStep) -> dict:
        """
        Execute a single plan step using V2 Context Engine.
        """
        await self._manual_pause_event.wait()
        await self.ws.send_step_update(step.step_number, "in_progress", f"Working on {step.title}...")
        step.status = StepStatus.IN_PROGRESS
        self.state.save(self.workspace_dir / "project_state.json")

        # ── V2: Context Assembly ──
        await self.ws.send_status("generating", f"Retrieving Brain context for {step.file_path}...")
        context_text = self.context_engine.build_context_for_file(step.file_path, step.description)

        # ── Code Generation ──
        await self.ws.send_status("generating", f"Writing {step.file_path}...")
        llm_chunks = []

        def on_token(token: str):
            llm_chunks.append(token)
            asyncio.ensure_future(self.ws.send_llm_token(token))
        def on_thinking(token: str):
            asyncio.ensure_future(self.ws.send_llm_thinking(token))

        # Read stub if it exists (from Phase 0)
        stub_content = None
        file_path = self.workspace_dir / step.file_path
        if file_path.exists():
            stub_content = file_path.read_text(encoding="utf-8")

        # We pass context_text and stub_content directly using the new v2 code generator
        success, error = await self.coder.generate_code_v2(
            step, context_text, stub_content=stub_content, 
            on_token=on_token, on_thinking=on_thinking
        )
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

        file_path = self.workspace_dir / step.file_path
        if file_path.exists():
            code_content = file_path.read_text(encoding="utf-8")
            
            # ── V2: Integration Verification ──
            if step.file_path.endswith(".py") and step.file_path != "main.py":
                await self.ws.send_status("integrating", f"Verifying {step.file_path} integration...")
                is_integrated, instructions = await self.integration_agent.verify_integration(step.file_path, code_content)
                if not is_integrated:
                    await self.ws.send_status("fixing", f"Integration issues found in {step.file_path}. Auto-fixing...")
                    fixed = await self._auto_fix(step.file_path, instructions, verify_execution=False)
                    if fixed:
                        code_content = file_path.read_text(encoding="utf-8")
                    else:
                        await self.ws.send_error("Failed to fix integration issues.", step.file_path)

            # ── Phase 4: Scoped Incremental Verification (Ruff/Pyright) ──
            if step.file_path.endswith(".py"):
                await self.ws.send_status("verifying", f"Running incremental lint/type checks on {step.file_path}...")
                v_success, v_error = await self.verifier.verify_file(step.file_path)
                if not v_success:
                    await self.ws.send_status("fixing", f"Incremental check failed for {step.file_path}. Auto-fixing...")
                    fixed = await self._auto_fix(step.file_path, v_error, verify_execution=False)
                    if fixed:
                        code_content = file_path.read_text(encoding="utf-8")
                    else:
                        await self.ws.send_error("Failed to fix lint/type errors.", step.file_path)

            # ── Phase 8: Test-First Verification (TDD) ──
            if step.file_path.endswith(".py"):
                path_obj = Path(step.file_path)
                test_file_name = f"test_{path_obj.name}"
                test_path = path_obj.parent / test_file_name
                
                # If a test file was generated in Phase 0, run pytest against it
                if (self.workspace_dir / test_path).exists():
                    await self.ws.send_status("verifying", f"Running TDD tests for {step.file_path}...")
                    test_cmd = f"{self.runner._get_python_cmd()} -m pytest {test_path}"
                    test_res = await self.runner.run_shell_command(test_cmd)
                    
                    if not test_res.success:
                        await self.ws.send_status("fixing", f"Tests failed for {step.file_path}. Auto-fixing...")
                        error_msg = f"Pytest Output:\n{test_res.stdout}\n{test_res.stderr}"
                        fixed = await self._auto_fix(step.file_path, error_msg, verify_execution=False)
                        if fixed:
                            code_content = file_path.read_text(encoding="utf-8")
                        else:
                            await self.ws.send_error("Failed to fix test failures.", step.file_path)

            # ── V2: Summarization & Storage ──
            SUMMARIZABLE_EXTENSIONS = ('.py', '.js', '.jsx', '.ts', '.tsx')
            if any(step.file_path.endswith(ext) for ext in SUMMARIZABLE_EXTENSIONS):
                await self.ws.send_status("verifying", f"Summarizing {step.file_path} for Project Brain...")
                summary = await self.summarizer.summarize_file(step.file_path, code_content)
                if summary:
                    self.brain.store_file_summary(summary)
            
            await self.ws.send_file_update(step.file_path, code_content)
            
            # ── V1: AST Registry fallback (for bridging) ──
            # We still add to the old file registry so the fixer and fallback contexts work
            from core.context import FileRegistryBuilder
            entry = FileRegistryBuilder.parse_file(file_path, step.file_path)
            if entry:
                self.state.file_registry = [e for e in self.state.file_registry if e.path != step.file_path]
                self.state.file_registry.append(entry)



        # Mark complete
        if self._cancel_requested:
            return {"success": False, "continued": False, "error": "Cancelled"}

        step.status = StepStatus.COMPLETED
        self.state.completed_steps.add(step.step_number)
        self.state.save(self.workspace_dir / "project_state.json")
        CheckpointManager.save(self.workspace_dir, self.state.current_epic_id, step.step_number, "completed")
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

        qa = QAAgent(self.llm, self.state.original_prompt)
        python_cmd = self.runner._get_python_cmd()
        main_file = str(self.workspace_dir / (self.state.project_entry_point or "main.py"))

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
            entry_file = self.state.project_entry_point or "main.py"
            await self.ws.send_error(error_text, entry_file)

            if attempt < config.MAX_QA_ATTEMPTS:
                await self.ws.send_status("fixing", "QA Agent found issues. Auto-fixing...")
                fixed = await self._auto_fix(entry_file, error_text)
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
            await self._manual_pause_event.wait()
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
            fix_thinking_chunks = []
            def on_fix_token(token: str):
                fix_chunks.append(token)
                asyncio.ensure_future(self.ws.send_llm_token(token))
            def on_fix_thinking(token: str):
                fix_thinking_chunks.append(token)
                asyncio.ensure_future(self.ws.send_llm_thinking(token))

            success, msg, fixed_files = await self.fixer.fix_error(target_file, current_error, on_token=on_fix_token, on_thinking=on_fix_thinking)
            await self.ws.send_llm_done("".join(fix_chunks))
            
            self.state.chat_history.append({
                "role": "assistant",
                "content": "".join(fix_chunks),
                "thinking": "".join(fix_thinking_chunks)
            })
            self.state.save(self.workspace_dir / "project_state.json")



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

    async def retry_execution(self, target_step_number: Optional[int] = None) -> dict:
        """Retry execution after a paused state. Redos the current step, or the last completed step."""
        if not self.state:
            return {"success": False, "error": "No active project"}
            
        step_to_retry_idx = -1
        
        if target_step_number is not None:
            for i, step in enumerate(self.state.plan_steps):
                if step.step_number == target_step_number:
                    step_to_retry_idx = i
                    break
        else:
            for i, step in enumerate(self.state.plan_steps):
                if step.status in [StepStatus.IN_PROGRESS, StepStatus.FAILED]:
                    step_to_retry_idx = i
                    break
                    
            if step_to_retry_idx == -1:
                for i, step in enumerate(self.state.plan_steps):
                    if step.status == StepStatus.PENDING:
                        if i > 0:
                            step_to_retry_idx = i - 1
                        break
                        
            if step_to_retry_idx == -1 and self.state.plan_steps:
                step_to_retry_idx = len(self.state.plan_steps) - 1
            
        if target_step_number is None:
            # Walk backwards to find the last step that is a code file (not .md or .txt)
            while step_to_retry_idx >= 0:
                file_path = self.state.plan_steps[step_to_retry_idx].file_path
                if file_path and not (file_path.endswith('.md') or file_path.endswith('.txt')):
                    break
                step_to_retry_idx -= 1
            
        if step_to_retry_idx < 0 and self.state.plan_steps:
            step_to_retry_idx = 0
            
        if step_to_retry_idx >= 0:
            self.state.plan_steps[step_to_retry_idx].status = StepStatus.PENDING
            for i in range(step_to_retry_idx + 1, len(self.state.plan_steps)):
                self.state.plan_steps[i].status = StepStatus.PENDING
            self.state.save(self.workspace_dir / "project_state.json")
            
            plan_data = [
                {"step_number": s.step_number, "title": s.title, "file_path": s.file_path, "status": s.status.value, "epic_id": getattr(s, "epic_id", None)}
                for s in self.state.plan_steps
            ]
            await self.ws.send_plan_update(plan_data)

        if self._executing:
            self._cancel_requested = True
            self._manual_pause_event.set()
            if self.runner:
                await self.runner.kill_process()

        self.state.status = "executing"
        self.state.save(self.workspace_dir / "project_state.json")
        await self.ws.send_status("executing", f"Retrying from step {step_to_retry_idx + 1}...")
        
        import asyncio
        async def _restart_when_ready():
            while getattr(self, "_executing", False):
                await asyncio.sleep(0.5)
                
            self._paused = False
            self._cancel_requested = False
            self._skip_requested = False
            self._manual_pause_event.set()
            
            await self.execute_all()
            
        asyncio.create_task(_restart_when_ready())
            
        return {"success": True, "message": "Retrying..."}

    async def skip_execution(self) -> dict:
        """Skip the paused step and continue execution (user clicked 'Skip')."""
        if not self._paused:
            return {"success": False, "error": "System is not paused"}
        
        self._skip_requested = True
        if self._retry_event:
            self._retry_event.set()
        
        return {"success": True, "message": "Skipping to next phase..."}

    async def handle_manual_fix(self, prompt: str, file_paths: list[str] = None) -> dict:
        """Handle a followup request from the user (e.g. 'run the tests' or 'add a login page')."""
        if not self.state:
            return {"success": False, "error": "No project loaded"}

        self.state.chat_history.append({"role": "user", "content": prompt})
        self.state.save(self.workspace_dir / "project_state.json")

        await self.ws.send_status("planning", "Analyzing user request intent...")
        
        # Determine intent
        intent_prompt = f"""You must classify the following user request into one of three categories:
1. "bug_fix": The user is pasting an error, traceback, or asking to fix a broken feature/bug.
2. "feature_update": The user is asking to add a new feature, change the architecture, or implement something new.
3. "document_task": The user is asking a conversational question, asking to summarize attached documents, compare them, or perform a general QA task.

Respond with exactly one word: either "bug_fix", "feature_update", or "document_task".

USER REQUEST:
{prompt}
"""
        try:
            intent_raw = await self.llm.generate(prompt=intent_prompt, system="You are an intent classifier. Respond with ONE word.")
            intent = intent_raw.strip().lower()
            if "doc" in intent or "chat" in intent or "sum" in intent or intent == "document_task":
                intent_type = "document_task"
            elif "bug" in intent or "fix" in intent or "error" in intent:
                intent_type = "bug_fix"
            else:
                intent_type = "feature_update"
        except Exception:
            intent_type = "feature_update"  # default to feature if LLM fails here

        if intent_type == "document_task":
            await self.ws.send_status("processing", "Request classified as Document Task. Reading documents...")
            if file_paths:
                for fp in file_paths:
                    from pathlib import Path
                    await self.doc_ingester.ingest_document(fp, Path(fp).name, on_status=self.ws.send_status)
            
            await self.chat_agent.process_task(prompt, self.state.user_documents)
            return {"success": True, "message": "Document task processed."}

        if intent_type == "feature_update":
            await self.ws.send_status("planning", "Request classified as Feature Update. Generating new plan...")
            
            if file_paths:
                for fp in file_paths:
                    from pathlib import Path
                    await self.doc_ingester.ingest_document(fp, Path(fp).name, on_status=self.ws.send_status)
                
                extracted_reqs = await self.chat_agent.process_task(
                    "Extract a detailed master specification and architecture plan from these documents to build the requested feature.",
                    self.state.user_documents, 
                    return_result=True
                )
                self.state.global_master_summary = extracted_reqs
                self.state.save(self.workspace_dir / "project_state.json")
                
            return await self._update_project(prompt)

        # Fall back to the original bug fix logic
        await self.ws.send_status("fixing", "Request classified as Bug Fix. Targeting file...")
        target_file = self._resolve_target_file(prompt)
        
        fixed = await self._auto_fix(target_file, f"User Feedback/Request:\n{prompt}", verify_execution=True)
        
        if fixed:
            await self.ws.send_status("fixed", f"Successfully fixed {target_file}!")
            self.state.status = "fixed"
        else:
            self.state.status = "completed"
            
        self.state.save(self.workspace_dir / "project_state.json")
        return {"success": True}

    async def _update_project(self, prompt: str) -> dict:
        """Handle a feature update request by generating a new update plan."""
        if not self.master_planner:
            from core.planners.master_planner import MasterPlanner
            self.master_planner = MasterPlanner(self.llm)
            
        try:
            async def send_token(t):
                await self.ws.send_llm_token(t)
            async def send_thinking(t):
                await self.ws.send_llm_thinking(t)
                
            update_prompt = prompt
            if getattr(self.state, "global_master_summary", ""):
                update_prompt = f"GLOBAL MASTER SPECIFICATION (from uploaded documents):\n{self.state.global_master_summary}\n\n{update_prompt}"
            elif hasattr(self.state, "user_documents") and self.state.user_documents:
                summaries = [doc.master_summary for doc in self.state.user_documents]
                update_prompt = f"PROJECT MASTER SPECIFICATIONS (from uploaded documents):\n" + "\n---\n".join(summaries) + f"\n\n{update_prompt}"

            update_steps = await self.master_planner.generate_update_plan(
                prompt=update_prompt,
                state=self.state,
                on_token=send_token,
                on_thinking=send_thinking
            )
        except Exception as e:
            log.error(f"Update plan failed: {e}", exc_info=True)
            return {"success": False, "error": f"Failed to generate update plan: {e}"}
            
        if not update_steps:
            return {"success": False, "error": "No update steps generated"}
            
        # Append steps to state
        start_step = len(self.state.plan_steps) + 1
        for i, step in enumerate(update_steps):
            step.step_number = start_step + i
            self.state.plan_steps.append(step)
            
        # Reset plan_approved to False so the user can review the new steps
        self.state.plan_approved = False
        self.state.status = "plan_review"
        self.state.save(self.workspace_dir / "project_state.json")
        
        # Send updated plan to frontend
        plan_data = [
            {"step_number": s.step_number, "title": s.title, "file_path": s.file_path, "description": s.description, "status": s.status.value, "epic_id": getattr(s, "epic_id", None)}
            for s in self.state.plan_steps
        ]
        await self.ws.send_plan_update(plan_data)
        await self.ws.send_status("plan_review", "Update plan generated. Review and approve to begin execution.")
        
        return {"success": True}


    def _resolve_target_file(self, text: str) -> str:
        """Resolve the target file from user-pasted error text."""
        workspace_path = self.workspace_dir.resolve()
        
        file_matches = re.findall(r'File "([^"]+)"', text)
        if file_matches:
            for match in reversed(file_matches):
                try:
                    match_path = Path(match).resolve()
                    if match_path.is_relative_to(workspace_path):
                        rel_path = match_path.relative_to(workspace_path).as_posix()
                        if (self.workspace_dir / rel_path).exists():
                            return rel_path
                except Exception:
                    pass
            for match in reversed(file_matches):
                basename = Path(match).name
                found = self._find_file_in_workspace(basename)
                if found:
                    return found
        
        error_info = ErrorParser.parse_traceback(text)
        if error_info.get("file"):
            error_file = error_info["file"]
            try:
                err_path = Path(error_file).resolve()
                if err_path.is_relative_to(workspace_path):
                    rel_path = err_path.relative_to(workspace_path).as_posix()
                    if (self.workspace_dir / rel_path).exists():
                        return rel_path
            except Exception:
                pass
            found = self._find_file_in_workspace(Path(error_file).name)
            if found:
                return found
        
        entry = self.state.project_entry_point or "main.py"
        log.warning(f"Manual fix: could not resolve target file, defaulting to {entry}")
        return entry

    def _find_file_in_workspace(self, filename: str) -> Optional[str]:
        """Search the workspace for a file by name. Returns relative path or None."""
        for item in self.workspace_dir.rglob(filename):
            if item.is_file():
                rel = item.relative_to(self.workspace_dir).as_posix()
                if "/venv/" in f"/{rel}" or "__pycache__" in rel or "/.agent_brain/" in f"/{rel}":
                    continue
                return rel
        return None

    # ── User Input ────────────────────────────────────────────────────

    async def _request_input(self) -> str:
        """Called by Runner when process hangs on stdin."""
        log.info("Process asked for input during testing. Supplying automated 'exit' command to prevent blocking.")
        return "exit"

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
        if self.runner:
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
        """List all files in the workspace (excluding venv and internal brain)."""
        if not self.workspace_dir:
            return []
        files = []
        for path in self.workspace_dir.rglob("*"):
            if path.is_file():
                # Ignore hidden directories, virtual environments, and caches
                if any(ignored in path.parts for ignored in [".git", "__pycache__", ".pytest_cache", ".agent_brain", "venv", "graphify-out", "node_modules", "dist", "build"]):
                    continue
                files.append(path.relative_to(self.workspace_dir).as_posix())
        return sorted(files)

    async def pause_execution(self) -> dict:
        """Manually pause the execution loop."""
        self._manual_pause_event.clear()
        if self.state:
            self.state.status = "paused"
            self.state.save(self.workspace_dir / "project_state.json")
        await self.ws.send_status("paused", "Execution paused manually.")
        return {"success": True}

    async def resume_execution(self) -> dict:
        """Manually resume the execution loop."""
        self._manual_pause_event.set()
        if self.state:
            self.state.status = "executing"
            self.state.save(self.workspace_dir / "project_state.json")
        await self.ws.send_status("executing", "Execution resumed.")
        
        # If the server was restarted, the execution loop won't be running. Start it!
        if getattr(self, "_executing", False) is False:
            import asyncio
            asyncio.create_task(self.execute_all())
            
        return {"success": True}

    # ── Document Processing ───────────────────────────────────────────

    async def ingest_user_document(self, file_path: str, doc_id: str) -> dict:
        """Ingests a large user document into the system state and semantic store."""
        if not self.state or not self.doc_ingester:
            return {"success": False, "error": "No active project"}
            
        try:
            async def send_status(msg: str):
                await self.ws.send_status("document_ingestion", msg)
                
            doc = await self.doc_ingester.ingest_document(file_path, doc_id, on_status=send_status)
            return {"success": True, "document": doc.to_dict()}
        except Exception as e:
            import traceback
            log.error(f"Failed to ingest document {file_path}: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    async def consolidate_documents(self) -> dict:
        """Consolidates all ingested documents into a single master specification."""
        if not self.state or not self.doc_ingester:
            return {"success": False, "error": "No active project"}
            
        try:
            await self.ws.send_status("document_consolidation", "Consolidating all documents into master specification...")
            summary = await self.doc_ingester.consolidate_all_documents()
            await self.ws.send_status("document_consolidation", "Master specification ready.")
            return {"success": True, "master_specification": summary}
        except Exception as e:
            import traceback
            log.error(f"Failed to consolidate documents: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}
