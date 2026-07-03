import json
import os
import asyncio
from pathlib import Path
from core.brain.project_brain import ProjectBrain
from models.state import ProjectState
from models.hierarchy import ArchitectureSpec

workspace_dir = Path("projects/jj")
state = ProjectState.load(workspace_dir / "project_state.json")
brain = ProjectBrain(workspace_dir)

print(f"Loaded project {state.project_name} with {len(state.epic_queue)} epics.")

for i, epic in enumerate(state.epic_queue):
    clear_graph = (i == 0)
    spec = ArchitectureSpec(name=epic.name, subsystems=[epic.subsystem])
    brain.ingest_architecture(spec, state.project_name, clear=clear_graph)
    print(f"Ingested epic {i+1}: {epic.name}")

print("Done re-ingesting!")
