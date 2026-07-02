import logging
from pathlib import Path
from typing import Callable, Optional
import asyncio

from core.brain.project_brain import ProjectBrain
from core.agents.summarizer import SummarizerAgent

log = logging.getLogger(__name__)

class RepositoryIngester:
    """
    Ingests an existing codebase into the Project Brain (Phase 7).
    
    1. Extracts AST and graph relationships using Graphifyy.
    2. Runs deep semantic analysis on every file to populate ChromaDB.
    """
    
    def __init__(self, workspace: Path, brain: ProjectBrain, summarizer: SummarizerAgent):
        self.workspace = workspace
        self.brain = brain
        self.summarizer = summarizer

    async def ingest_repository(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None
    ) -> bool:
        """
        Ingest the entire repository into the Project Brain.
        """
        if on_status:
            on_status("Starting AST Knowledge Graph extraction...")
            
        # 1. Extract AST and relationships into Neo4j
        try:
            self.brain.update_graphify_knowledge()
        except Exception as e:
            log.error(f"Graphify extraction failed: {e}")
            if on_status:
                on_status(f"Error during AST extraction: {e}")
            return False

        if on_status:
            on_status("Starting Semantic Analysis of codebase...")

        # 2. Find all python files to summarize
        paths = list(self.workspace.rglob("*.py"))
        # Filter out venv, .git, and hidden directories
        paths = [
            p for p in paths 
            if "venv" not in p.parts and ".git" not in p.parts and not any(part.startswith('.') for part in p.parts if part != '.agent_brain')
        ]
        
        total_files = len(paths)
        if total_files == 0:
            if on_status:
                on_status("No Python files found to ingest.")
            return True

        # 3. Summarize each file and store in ChromaDB
        for i, path in enumerate(paths):
            rel_path = str(path.relative_to(self.workspace)).replace("\\", "/")
            if on_progress:
                on_progress(i, total_files, rel_path)
                
            try:
                content = path.read_text(encoding="utf-8")
                summary = await self.summarizer.summarize_file(rel_path, content)
                
                if summary:
                    # We don't have subsystem/service info for raw codebases, so we leave them empty
                    self.brain.store_file_summary(summary, subsystem="", service="")
            except Exception as e:
                log.warning(f"Failed to summarize {rel_path}: {e}")

        if on_progress:
            on_progress(total_files, total_files, "Complete")
            
        if on_status:
            on_status(f"Successfully ingested {total_files} files into Project Brain.")
            
        return True
