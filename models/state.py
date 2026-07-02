"""
State Models — data structures for the Context Agent.

These models represent the full state of a project at any point in time.
All state is JSON-serializable for checkpoint/resume support.
"""

from __future__ import annotations
import json
import uuid
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict
from datetime import datetime
from dataclasses import dataclass, field, asdict

from models.hierarchy import EpicSpec, ProjectScale


class StepStatus(str, Enum):
    """Status of a single plan step."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class FileEntry:
    """
    Represents a single file in the project's File Registry.

    Built by parsing actual Python files with the `ast` module —
    NOT from LLM summaries. This is the key to solving code stitching.
    """
    path: str                                           # relative path in workspace (e.g. "src/calc.py")
    classes: List[str] = field(default_factory=list)     # top-level class names
    functions: List[str] = field(default_factory=list)   # top-level function names
    imports: List[str] = field(default_factory=list)     # import statements
    class_methods: Dict[str, List[str]] = field(default_factory=dict)  # class -> method names
    function_signatures: Dict[str, str] = field(default_factory=dict)  # func_name -> "func(a, b) -> int"
    constants: List[str] = field(default_factory=list)   # module-level constants (ALL_CAPS names)

    def to_registry_string(self) -> str:
        """
        Format this file entry as a readable string for the LLM context.
        This is what the LLM sees — concrete, not abstract.
        """
        lines = [f"  {self.path}"]

        if self.classes:
            for cls_name in self.classes:
                methods = self.class_methods.get(cls_name, [])
                if methods:
                    lines.append(f"    class {cls_name}: {', '.join(methods)}")
                else:
                    lines.append(f"    class {cls_name}")

        if self.functions:
            for fn in self.functions:
                sig = self.function_signatures.get(fn, fn + "()")
                lines.append(f"    def {sig}")

        if self.constants:
            lines.append(f"    constants: {', '.join(self.constants)}")

        if self.imports:
            # Show only non-stdlib imports to save tokens
            external = [i for i in self.imports if not i.startswith("import os")
                        and not i.startswith("import sys")
                        and not i.startswith("import json")
                        and not i.startswith("import re")
                        and not i.startswith("import math")]
            if external:
                lines.append(f"    imports: {'; '.join(external[:5])}")

        return "\n".join(lines)


@dataclass
class PlanStep:
    """
    A single step in the project plan.

    Each step produces exactly ONE file. Steps are executed in order,
    with dependency checking to ensure prerequisites are met.
    """
    step_number: int
    title: str
    file_path: str                                        # relative path (e.g. "src/calc.py")
    description: str                                      # detailed description of what to implement
    depends_on: List[int] = field(default_factory=list)   # step numbers this depends on
    status: StepStatus = StepStatus.PENDING
    summary: str = ""                                     # concrete summary after completion
    error: str = ""                                       # last error if failed
    attempts: int = 0                                     # number of attempts made

    def is_ready(self, completed_steps: set) -> bool:
        """Check if all dependencies are satisfied."""
        return all(dep in completed_steps for dep in self.depends_on)


@dataclass
class ProjectState:
    """
    Complete state of a Context Agent project.

    This is the single source of truth. It's saved to disk as JSON
    after every significant change, enabling checkpoint/resume.
    """
    # Identity
    project_id: str = field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:8]}")
    project_name: str = ""                     # user-provided name

    # Input
    original_prompt: str = ""
    architecture_text: str = ""                # raw architecture.md content
    project_scale: str = "medium"              # simple, medium, large, massive

    # Epics (Phase 1 JIT Planning)
    epic_queue: List[EpicSpec] = field(default_factory=list)
    current_epic_id: Optional[str] = None

    # Plan
    plan_text: str = ""                        # raw plan.txt content
    plan_steps: List[PlanStep] = field(default_factory=list)
    plan_approved: bool = False

    # File Registry — the key to code stitching
    file_registry: List[FileEntry] = field(default_factory=list)

    # Progress
    current_step: int = 0                      # index into plan_steps
    completed_steps: set = field(default_factory=set)
    status: str = "idle"                       # idle, planning, plan_review, executing, fixing, completed, failed

    # Step summaries — concrete, with function/class names
    step_summaries: List[str] = field(default_factory=list)

    # Fix history — memory of past bugs fixed
    fix_history: List[dict] = field(default_factory=list)

    # Chat history — persistent conversation and reasoning logs
    chat_history: List[dict] = field(default_factory=list)

    # Metrics
    total_llm_calls: int = 0
    total_tokens_used: int = 0

    # Timestamps
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: Optional[str] = None

    # Workspace path (set after project directory is created)
    workspace_path: str = ""
    venv_path: str = ""
    
    # V2 Project Brain Tracking
    brain_path: str = ""                       # path to .agent_brain directory
    hierarchy_spec_path: str = ""              # path to architecture_spec.json

    def increment_llm_calls(self, tokens: int = 0):
        """Track LLM usage."""
        self.total_llm_calls += 1
        self.total_tokens_used += tokens
        self.updated_at = datetime.utcnow().isoformat()

    def get_file_registry_string(self) -> str:
        """
        Build the complete File Registry string that goes into every LLM prompt.
        This is the #1 most important context — it tells the LLM exactly
        what files exist and what they export.
        """
        if not self.file_registry:
            return "FILE REGISTRY: (no files created yet)"

        lines = ["FILE REGISTRY (current project files):"]
        lines.append("=" * 45)
        for entry in self.file_registry:
            lines.append(entry.to_registry_string())
            lines.append("")  # blank line between files
        return "\n".join(lines)

    def get_completed_summaries(self) -> str:
        """Get all completed step summaries as a single string."""
        if not self.step_summaries:
            return ""
        return "\n".join(
            f"Step {i+1}: {s}" for i, s in enumerate(self.step_summaries)
        )

    def progress_percent(self) -> float:
        """Calculate completion percentage."""
        if not self.plan_steps:
            return 0.0
        completed = sum(1 for s in self.plan_steps if s.status == StepStatus.COMPLETED)
        return round((completed / len(self.plan_steps)) * 100, 1)

    def to_api_dict(self) -> dict:
        """Convert to a dict suitable for JSON API responses (lightweight)."""
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "status": self.status,
            "current_step": self.current_step,
            "total_steps": len(self.plan_steps),
            "progress": self.progress_percent(),
            "plan_approved": self.plan_approved,
            "workspace_path": self.workspace_path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "plan_steps": [
                {
                    "step_number": s.step_number,
                    "title": s.title,
                    "file_path": s.file_path,
                    "description": s.description,
                    "status": s.status.value,
                    "summary": s.summary,
                    "error": s.error,
                }
                for s in self.plan_steps
            ],
            "file_registry": [
                {
                    "path": f.path,
                    "classes": f.classes,
                    "functions": f.functions,
                }
                for f in self.file_registry
            ],
            "step_summaries": self.step_summaries,
            "fix_history": self.fix_history,
            "chat_history": self.chat_history,
            "total_llm_calls": self.total_llm_calls,
            "total_tokens_used": self.total_tokens_used,
            "project_scale": self.project_scale,
            "epic_queue": [e.to_dict() for e in self.epic_queue],
            "current_epic_id": self.current_epic_id,
        }

    # ── Serialization ─────────────────────────────────────────────────

    def save(self, path: Path):
        """Save project state to JSON file."""
        data = self._to_dict()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Optional["ProjectState"]:
        """Load project state from JSON file."""
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls._from_dict(data)
        except Exception:
            return None

    @classmethod
    def list_projects(cls, projects_dir: Path) -> List[dict]:
        """List all saved projects with basic info for the dashboard."""
        projects = []
        if not projects_dir.exists():
            return projects
        for project_dir in sorted(projects_dir.iterdir()):
            if not project_dir.is_dir():
                continue
            state_file = project_dir / "project_state.json"
            if state_file.exists():
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    projects.append({
                        "project_id": data.get("project_id", ""),
                        "project_name": data.get("project_name", project_dir.name),
                        "status": data.get("status", "unknown"),
                        "created_at": data.get("created_at", ""),
                        "updated_at": data.get("updated_at", ""),
                        "workspace_path": str(project_dir),
                        "total_steps": len(data.get("plan_steps", [])),
                        "completed_steps": len(data.get("completed_steps", [])),
                        "progress": 0.0,
                    })
                    # Calculate progress
                    total = len(data.get("plan_steps", []))
                    completed = sum(1 for s in data.get("plan_steps", []) if s.get("status") == "completed")
                    if total > 0:
                        projects[-1]["progress"] = round((completed / total) * 100, 1)
                except Exception:
                    continue
        return projects

    def _to_dict(self) -> dict:
        """Convert to a JSON-serializable dictionary."""
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "project_scale": self.project_scale,
            "epic_queue": [e.to_dict() for e in self.epic_queue],
            "current_epic_id": self.current_epic_id,
            "original_prompt": self.original_prompt,
            "plan_text": self.plan_text,
            "plan_steps": [
                {
                    "step_number": s.step_number,
                    "title": s.title,
                    "file_path": s.file_path,
                    "description": s.description,
                    "depends_on": s.depends_on,
                    "status": s.status.value,
                    "summary": s.summary,
                    "error": s.error,
                    "attempts": s.attempts,
                }
                for s in self.plan_steps
            ],
            "plan_approved": self.plan_approved,
            "file_registry": [
                {
                    "path": f.path,
                    "classes": f.classes,
                    "functions": f.functions,
                    "imports": f.imports,
                    "class_methods": f.class_methods,
                    "function_signatures": f.function_signatures,
                    "constants": f.constants,
                }
                for f in self.file_registry
            ],
            "current_step": self.current_step,
            "completed_steps": list(self.completed_steps),
            "status": self.status,
            "step_summaries": self.step_summaries,
            "fix_history": self.fix_history,
            "chat_history": self.chat_history,
            "total_llm_calls": self.total_llm_calls,
            "total_tokens_used": self.total_tokens_used,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workspace_path": self.workspace_path,
            "venv_path": self.venv_path,
        }

    @classmethod
    def _from_dict(cls, data: dict) -> "ProjectState":
        """Reconstruct from a dictionary."""
        state = cls()
        state.project_id = data.get("project_id", state.project_id)
        state.project_name = data.get("project_name", "")
        state.project_scale = data.get("project_scale", "medium")
        state.current_epic_id = data.get("current_epic_id")
        
        # Rebuild Epics
        for ed in data.get("epic_queue", []):
            state.epic_queue.append(EpicSpec.from_dict(ed))

        state.original_prompt = data.get("original_prompt", "")
        state.plan_text = data.get("plan_text", "")
        state.plan_approved = data.get("plan_approved", False)
        state.current_step = data.get("current_step", 0)
        state.completed_steps = set(data.get("completed_steps", []))
        state.status = data.get("status", "idle")
        state.step_summaries = data.get("step_summaries", [])
        state.fix_history = data.get("fix_history", [])
        state.chat_history = data.get("chat_history", [])
        state.total_llm_calls = data.get("total_llm_calls", 0)
        state.total_tokens_used = data.get("total_tokens_used", 0)
        state.created_at = data.get("created_at", "")
        state.updated_at = data.get("updated_at")
        state.workspace_path = data.get("workspace_path", "")
        state.venv_path = data.get("venv_path", "")

        # Rebuild plan steps
        for sd in data.get("plan_steps", []):
            step = PlanStep(
                step_number=sd["step_number"],
                title=sd["title"],
                file_path=sd["file_path"],
                description=sd["description"],
                depends_on=sd.get("depends_on", []),
                status=StepStatus(sd.get("status", "pending")),
                summary=sd.get("summary", ""),
                error=sd.get("error", ""),
                attempts=sd.get("attempts", 0),
            )
            state.plan_steps.append(step)

        # Rebuild file registry
        for fd in data.get("file_registry", []):
            entry = FileEntry(
                path=fd["path"],
                classes=fd.get("classes", []),
                functions=fd.get("functions", []),
                imports=fd.get("imports", []),
                class_methods=fd.get("class_methods", {}),
                function_signatures=fd.get("function_signatures", {}),
                constants=fd.get("constants", []),
            )
            state.file_registry.append(entry)

        return state
