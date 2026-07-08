import logging
import asyncio
from pathlib import Path
from typing import Callable, Optional

from core.brain.project_brain import ProjectBrain
from core.agents.summarizer import SummarizerAgent
from core.agents.understanding_agent import UnderstandingAgent
from core.context import FileRegistryBuilder
from models.state import ProjectState, FileEntry

log = logging.getLogger(__name__)

class RepositoryIngester:
    """
    Ingests an existing codebase into the Project Brain (Phase 7).
    
    1. Extracts AST and graph relationships using Graphifyy.
    2. Runs deep semantic analysis on every file to populate ChromaDB.
    """
    
    def __init__(self, workspace: Path, brain: ProjectBrain, summarizer: SummarizerAgent, understanding_agent: Optional[UnderstandingAgent] = None, state: Optional[ProjectState] = None):
        self.workspace = workspace
        self.brain = brain
        self.summarizer = summarizer
        self.understanding_agent = understanding_agent
        self.state = state

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

        # 2. Find all relevant files to summarize
        paths = []
        for ext in ["*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.md"]:
            paths.extend(self.workspace.rglob(ext))
        # Filter out venv, .git, hidden directories, and common library/cache folders
        ignored_dirs = {
            "venv", "env", ".env", ".git", "node_modules", "lib",
            "__pycache__", "site-packages", "dist", "build",
            ".pytest_cache", ".mypy_cache"
        }
        paths = [
            p for p in paths 
            if not any(part in ignored_dirs or (part.startswith('.') and part != '.agent_brain') for part in p.parts)
        ]
        
        total_files = len(paths)
        if total_files == 0:
            if on_status:
                on_status("No Python files found to ingest.")
            return True

        # 3. Summarize each file and store in ChromaDB (Concurrent)
        sem = asyncio.Semaphore(10)
        
        completed_count = 0
        
        async def process_file(i: int, path: Path):
            nonlocal completed_count
            rel_path = str(path.relative_to(self.workspace)).replace("\\", "/")
                
            async with sem:
                try:
                    content = path.read_text(encoding="utf-8")
                    summary = await self.summarizer.summarize_file(rel_path, content)
                    
                    if summary:
                        # We don't have subsystem/service info for raw codebases, so we leave them empty
                        self.brain.store_file_summary(summary, subsystem="", service="")
                        
                    if self.state:
                        # Parse AST and add to File Registry so the Planner can see it
                        if path.suffix == '.py':
                            entry = FileRegistryBuilder.parse_file(path, rel_path)
                            if entry:
                                self.state.file_registry.append(entry)
                        else:
                            self.state.file_registry.append(FileEntry(path=rel_path))
                            
                except Exception as e:
                    log.warning(f"Failed to summarize {rel_path}: {e}")
                
                completed_count += 1
                if on_progress:
                    on_progress(completed_count, total_files, rel_path)

        tasks = [process_file(i, path) for i, path in enumerate(paths)]
        if tasks:
            await asyncio.gather(*tasks)

        if on_progress:
            on_progress(total_files, total_files, "Complete")
            
        # 4. Synthesize overall architecture
        if self.understanding_agent:
            if on_status:
                on_status("Understanding Codebase Architecture...")
            try:
                def on_understanding_token(token: str):
                    # We could broadcast these tokens if we want, but for now just silence it
                    pass
                arch_text, entry_point = await self.understanding_agent.analyze_codebase(on_token=on_understanding_token)
                # We need to return this so the orchestrator can save it in project_state
                self.brain.latest_architecture_notes = arch_text
                if self.state and entry_point:
                    self.state.project_entry_point = entry_point
            except Exception as e:
                log.warning(f"Understanding phase failed: {e}")
            
        if on_status:
            on_status(f"Successfully ingested {total_files} files into Project Brain.")
            
        return True
