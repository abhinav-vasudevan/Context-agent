"""
Project Brain — Central façade coordinating all registries.

The ProjectBrain is the unified interface that the Orchestrator and
Context Retrieval Engine use to interact with the persistent memory.

It coordinates:
  - Knowledge Graph (Neo4j) — relationships between architectural entities
  - Semantic Store (ChromaDB) — meaning and similarity search
  - AST Registry (from existing v1) — concrete code structure
  - ADR Manager — architectural decision records

The LLM is NOT the source of truth. The Project Brain is.
"""

from __future__ import annotations
import logging
import json
from pathlib import Path
from typing import List, Dict, Any

import config
from core.brain.knowledge_graph import KnowledgeGraph
from core.brain.semantic_store import SemanticStore
from models.hierarchy import (
    ArchitectureSpec, ArchitectureDecisionRecord, SemanticSummary,
)

log = logging.getLogger(__name__)


class ProjectBrain:
    """
    Central coordinator for the Project Brain.

    Provides a clean API for:
      - Ingesting architecture specs into the graph and vector store
      - Storing and querying file summaries
      - Recording and retrieving ADRs
      - Impact analysis before code modifications
      - Architecture overview generation for LLM prompts

    Usage:
        brain = ProjectBrain(workspace_dir)
        brain.ingest_architecture(arch_spec)
        brain.store_file_summary("src/auth.py", summary)
        related = brain.get_context_for_file("src/auth.py")
    """

    BRAIN_DIR_NAME = ".agent_brain"

    def __init__(self, workspace_dir: Path):
        """
        Initialize the Project Brain for a workspace.

        Args:
            workspace_dir: Root directory of the project workspace.
                           The brain data is stored in <workspace>/.agent_brain/
        """
        self.workspace_dir = workspace_dir
        self.brain_dir = workspace_dir / self.BRAIN_DIR_NAME
        self.brain_dir.mkdir(parents=True, exist_ok=True)

        # ADR storage (JSON files)
        self.adr_dir = self.brain_dir / "adrs"
        self.adr_dir.mkdir(parents=True, exist_ok=True)

        # Architecture spec storage
        self.arch_spec_path = self.brain_dir / "architecture_spec.json"

        # Initialize subsystems
        neo4j_uri = getattr(config, "NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = getattr(config, "NEO4J_USER", "neo4j")
        neo4j_password = getattr(config, "NEO4J_PASSWORD", "password")
        neo4j_database = getattr(config, "NEO4J_DATABASE", "neo4j")

        self.graph = KnowledgeGraph(
            uri=neo4j_uri,
            user=neo4j_user,
            password=neo4j_password,
            database=neo4j_database,
        )

        chroma_dir = str(self.brain_dir / "chroma")
        self.semantic = SemanticStore(persist_dir=chroma_dir)

        log.info(
            "ProjectBrain initialized: graph=%s, semantic=%s",
            "connected" if self.graph.is_available else "offline",
            "connected" if self.semantic.is_available else "offline",
        )

    # ── Architecture Ingestion ────────────────────────────────────────

    def ingest_architecture(self, arch_spec: ArchitectureSpec, project_name: str, clear: bool = False):
        """
        Ingest a full architecture spec into both the Knowledge Graph
        and the Semantic Store.

        This is called after the Architecture Planner generates the spec.
        It populates:
          - Neo4j with Project -> Subsystem -> Service -> Module hierarchy
          - ChromaDB with searchable descriptions of each entity
        """
        log.info("Ingesting architecture spec: %s (%d subsystems)",
                 arch_spec.name, len(arch_spec.subsystems))

        # Save architecture spec to disk, merging with existing if possible
        try:
            if self.arch_spec_path.exists():
                existing = ArchitectureSpec.load(self.arch_spec_path)
                if existing:
                    existing_names = {s.name for s in existing.subsystems}
                    for s in arch_spec.subsystems:
                        if s.name not in existing_names:
                            existing.subsystems.append(s)
                    existing.save(self.arch_spec_path)
                else:
                    arch_spec.save(self.arch_spec_path)
            else:
                arch_spec.save(self.arch_spec_path)
        except Exception:
            arch_spec.save(self.arch_spec_path)

        # Clear previous graph data for this project if requested
        if clear:
            self.graph.clear_project(project_name)

        # Add the project node
        self.graph.add_node("Project", {"name": project_name, "vision": arch_spec.vision})

        for subsystem in arch_spec.subsystems:
            # Add subsystem to graph
            self.graph.add_node("Subsystem", {
                "name": subsystem.name,
                "purpose": subsystem.purpose,
                "description": subsystem.description,
            })
            self.graph.add_edge("Project", project_name, "Subsystem", subsystem.name, "OWNS")

            # Add subsystem to semantic store
            self.semantic.store_architecture_spec(
                entity_id=subsystem.id,
                entity_type="Subsystem",
                name=subsystem.name,
                description=subsystem.description,
                purpose=subsystem.purpose,
                responsibilities=subsystem.responsibilities,
            )

            # Add subsystem dependencies
            for dep_id in subsystem.dependencies:
                # Find the dependency subsystem by ID
                dep_sub = next((s for s in arch_spec.subsystems if s.id == dep_id), None)
                if dep_sub:
                    self.graph.add_edge("Subsystem", subsystem.name, "Subsystem", dep_sub.name, "DEPENDS_ON")

            for service in subsystem.services:
                # Add service to graph
                self.graph.add_node("Service", {
                    "name": service.name,
                    "description": service.description,
                })
                self.graph.add_edge("Subsystem", subsystem.name, "Service", service.name, "OWNS")

                # Add service to semantic store
                self.semantic.store_architecture_spec(
                    entity_id=service.id,
                    entity_type="Service",
                    name=service.name,
                    description=service.description,
                    responsibilities=service.responsibilities,
                )

                for module in service.modules:
                    # Add module/file to graph
                    self.graph.add_node("File", {
                        "path": module.file_path,
                        "name": module.name,
                        "description": module.description,
                    })
                    self.graph.add_edge("Service", service.name, "File", module.file_path, "OWNS")

        # Ingest ADRs
        for adr in arch_spec.adrs:
            self.store_adr(adr)

        log.info("Architecture ingestion complete.")

    def update_graphify_knowledge(self):
        """
        Runs Graphifyy AST extraction across the workspace and ingests the raw
        semantic symbols and edges into Neo4j.
        """
        try:
            import graphify.extract
            import graphify.build
            from pathlib import Path
            
            log.info("Starting Graphifyy extraction...")
            # Collect all python and frontend files
            paths = []
            for ext in ["*.py", "*.js", "*.jsx", "*.ts", "*.tsx", "*.md"]:
                paths.extend(self.workspace_dir.rglob(ext))
            # Filter out virtual environments and unwanted directories
            ignored_dirs = {
                "venv", "env", ".env", ".git", "node_modules", "lib",
                "__pycache__", "site-packages", "dist", "build",
                ".pytest_cache", ".mypy_cache"
            }
            paths = [
                p for p in paths 
                if not any(part in ignored_dirs or (part.startswith('.') and part != '.agent_brain') for part in p.parts)
            ]
            
            # Extract AST (skipping semantic LLM clustering to save time/tokens)
            extractions = graphify.extract.extract(paths)
            
            # Ingest into Neo4j
            count = 0
            
            nodes = extractions.get('nodes', [])
            edges = extractions.get('edges', [])
            
            for node in nodes:
                node_id = node.get('id')
                label = node.get('label', 'Unknown')
                file_type = node.get('file_type', 'code')
                source_file = node.get('source_file', '')
                
                # We skip rationale since we have ChromaDB for semantics
                if file_type == 'rationale':
                    continue
                
                # Add Symbol Node
                self.graph.add_node("Symbol", {
                    "id": node_id,
                    "name": label,
                    "kind": file_type,
                    "file": source_file
                })
                # Add file mapping if known
                if source_file:
                    self.graph.add_node("File", {"path": source_file, "name": Path(source_file).name})
                    self.graph.add_edge("File", source_file, "Symbol", node_id, "CONTAINS")
                
                count += 1
                
            for edge in edges:
                source = edge.get('source')
                target = edge.get('target')
                relation = edge.get('relation', 'CALLS').upper()
                
                if source and target:
                    # We ensure target exists, as graphify might point to external dependencies
                    self.graph.add_node("Symbol", {"id": target, "name": target})
                    self.graph.add_edge("Symbol", source, "Symbol", target, relation)

            log.info("Graphifyy ingestion complete. Ingested %d symbols into Neo4j.", count)
        except ImportError:
            log.warning("Graphifyy is not installed. Skipping automatic architecture graph build.")
        except Exception as e:
            log.error("Failed to update graphify knowledge: %s", e)

    # ── File Summary Management ───────────────────────────────────────

    def store_file_summary(self, summary: SemanticSummary, subsystem: str = "", service: str = ""):
        """
        Store a semantic summary for a file after it has been generated.

        Called by the Summarization Agent after every file creation/modification.
        """
        self.semantic.store_file_summary(
            file_path=summary.entity_path,
            purpose=summary.purpose,
            responsibilities=summary.responsibilities,
            exports=summary.exports,
            dependencies=summary.dependencies,
            constraints=summary.constraints,
            risks=summary.risks,
            subsystem=subsystem,
            service=service,
        )

        # Update the graph node with the summary purpose
        self.graph.add_node("File", {
            "path": summary.entity_path,
            "purpose": summary.purpose,
        })

        # Add dependency edges
        for dep in summary.dependencies:
            self.graph.add_edge("File", summary.entity_path, "File", dep, "DEPENDS_ON")

    # ── ADR Management ────────────────────────────────────────────────

    def store_adr(self, adr: ArchitectureDecisionRecord):
        """Store an ADR both to disk (JSON) and to the Semantic Store."""
        # Save to disk
        adr_path = self.adr_dir / f"{adr.id}.json"
        adr_path.write_text(json.dumps(adr.to_dict(), indent=2), encoding="utf-8")

        # Index in ChromaDB for semantic search
        self.semantic.store_adr(
            adr_id=adr.id,
            title=adr.title,
            context=adr.context,
            decision=adr.decision,
            consequences=adr.consequences,
        )

    def get_all_adrs(self) -> List[ArchitectureDecisionRecord]:
        """Load all ADRs from disk."""
        adrs = []
        for adr_file in sorted(self.adr_dir.glob("adr_*.json")):
            try:
                data = json.loads(adr_file.read_text(encoding="utf-8"))
                adrs.append(ArchitectureDecisionRecord.from_dict(data))
            except Exception as e:
                log.warning("Failed to load ADR %s: %s", adr_file.name, e)
        return adrs

    # ── Context Retrieval ─────────────────────────────────────────────

    def get_context_for_file(self, file_path: str, task_description: str = "") -> Dict[str, Any]:
        """
        Retrieve all relevant context for generating or modifying a file.

        This is the core method that the Context Retrieval Engine calls.
        It fuses data from all three brain subsystems:
          - Knowledge Graph: related files, owning subsystem, dependency chain
          - Semantic Store: similar files, relevant ADRs
          - AST Registry: (handled externally by the existing v1 system)

        Returns:
            Dict with keys:
              - subsystem: The subsystem this file belongs to
              - related_files: Files connected via the graph
              - dependency_chain: Files that must exist first
              - similar_files: Semantically similar files
              - relevant_adrs: ADRs related to this task
              - architecture_overview: High-level system map
        """
        context = {
            "subsystem": None,
            "related_files": [],
            "dependency_chain": [],
            "similar_files": [],
            "relevant_adrs": [],
            "architecture_overview": [],
        }

        # 1. Graph: subsystem ownership
        context["subsystem"] = self.graph.get_subsystem_for_file(file_path)

        # 2. Graph: related files within 2 hops
        context["related_files"] = self.graph.get_related_files(file_path, depth=2)

        # 3. Graph: dependency chain
        context["dependency_chain"] = self.graph.get_dependency_chain(file_path)

        # 4. Semantic: similar files
        query = task_description or file_path
        context["similar_files"] = self.semantic.query_similar_files(query, n_results=5)

        # 5. Semantic: relevant ADRs
        context["relevant_adrs"] = self.semantic.query_adrs(query, n_results=3)

        # 6. Graph: architecture overview
        context["architecture_overview"] = self.graph.get_architecture_overview()

        return context

    def get_impact_analysis(self, file_path: str) -> Dict[str, List[str]]:
        """
        Perform Change Impact Analysis before modifying a file.

        Returns what services, files, and subsystems would be affected.
        """
        return self.graph.get_impact_analysis(file_path)

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Get a status summary of the Project Brain."""
        return {
            "graph_available": self.graph.is_available,
            "semantic_available": self.semantic.is_available,
            "file_summaries_count": self.semantic.get_collection_count(SemanticStore.FILES_COLLECTION),
            "architecture_specs_count": self.semantic.get_collection_count(SemanticStore.ARCH_COLLECTION),
            "adr_count": len(list(self.adr_dir.glob("adr_*.json"))),
        }

    def close(self):
        """Release all connections."""
        self.graph.close()
