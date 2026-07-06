"""
Context Engine — Hierarchical Context Builder.

This replaces the flat AST-only context assembly from v1.
Instead of blindly injecting the entire AST registry into the LLM prompt,
the Context Engine queries the Project Brain to build a focused, minimal
context payload containing:

  1. Architecture Overview (from Knowledge Graph)
  2. Relevant Subsystem/Service descriptions (from Semantic Store)
  3. Related files within 2 hops (from Knowledge Graph)
  4. AST signatures of direct dependencies (from existing AST Registry)
  5. Relevant ADRs (from Semantic Store)
  6. Recent change summaries

This allows the system to work with even 4k–8k token context windows
because it never loads the entire codebase — only the relevant subgraph.
"""

from __future__ import annotations
import logging
from typing import Dict, List

from core.brain.project_brain import ProjectBrain
from core.llm_client import LLMClient
from models.state import ProjectState

log = logging.getLogger(__name__)


class ContextEngine:
    """
    Hierarchical Context Builder that fuses Graph + Semantic + AST
    into a focused LLM prompt payload.

    The key insight: for a 50,000-file codebase, the LLM only needs
    to see ~50 relevant items to write any single file correctly.
    This class determines WHICH 50 items those are.
    """

    def __init__(self, brain: ProjectBrain, state: ProjectState):
        self.brain = brain
        self.state = state

    def build_context_for_file(
        self,
        file_path: str,
        task_description: str,
        token_budget: int = 8000,
    ) -> str:
        """
        Build a focused context string for generating or modifying a file.

        This is the v2 replacement for ContextAssembler.build_coder_prompt().
        Instead of injecting the full AST registry, it retrieves only what
        the LLM needs for this specific file.

        Args:
            file_path: The file being generated/modified
            task_description: What the LLM needs to do
            token_budget: Maximum tokens to spend on context

        Returns:
            A formatted context string ready for injection into the LLM prompt
        """
        parts = []
        used_tokens = 0

        # 1. Retrieve context from the Project Brain
        brain_context = self.brain.get_context_for_file(file_path, task_description)

        # 2. Architecture Overview (high priority — always included)
        arch_overview = brain_context.get("architecture_overview", [])
        if arch_overview:
            overview_text = self._format_architecture_overview(arch_overview)
            overview_tokens = LLMClient.count_tokens(overview_text)
            if used_tokens + overview_tokens < token_budget:
                parts.append(overview_text)
                used_tokens += overview_tokens

        # 3. Owning Subsystem (if known)
        subsystem = brain_context.get("subsystem")
        if subsystem:
            sub_text = self._format_subsystem_context(subsystem)
            sub_tokens = LLMClient.count_tokens(sub_text)
            if used_tokens + sub_tokens < token_budget:
                parts.append(sub_text)
                used_tokens += sub_tokens

        # 4. AST Registry for direct dependencies (from v1, kept intact)
        dep_chain = brain_context.get("dependency_chain", [])
        registry_text = self._format_dependency_registry(dep_chain)
        if registry_text:
            reg_tokens = LLMClient.count_tokens(registry_text)
            if used_tokens + reg_tokens < token_budget:
                parts.append(registry_text)
                used_tokens += reg_tokens

        # 5. Related files from the graph (2-hop neighborhood)
        related_files = brain_context.get("related_files", [])
        if related_files:
            related_text = self._format_related_files(related_files)
            related_tokens = LLMClient.count_tokens(related_text)
            if used_tokens + related_tokens < token_budget:
                parts.append(related_text)
                used_tokens += related_tokens

        # 6. Semantically similar files
        similar_files = brain_context.get("similar_files", [])
        if similar_files:
            similar_text = self._format_similar_files(similar_files)
            similar_tokens = LLMClient.count_tokens(similar_text)
            if used_tokens + similar_tokens < token_budget:
                parts.append(similar_text)
                used_tokens += similar_tokens

        # 7. Relevant ADRs (design decisions)
        adrs = brain_context.get("relevant_adrs", [])
        if adrs:
            adr_text = self._format_adrs(adrs)
            adr_tokens = LLMClient.count_tokens(adr_text)
            if used_tokens + adr_tokens < token_budget:
                parts.append(adr_text)
                used_tokens += adr_tokens

        # 8. Fall back to v1 full AST registry if brain is empty
        if not parts:
            parts.append(self.state.get_file_registry_string())

        log.info(
            "Context for '%s': %d tokens used (budget: %d), %d sections",
            file_path, used_tokens, token_budget, len(parts),
        )

        return "\n\n".join(parts)

    def build_impact_context(self, file_path: str) -> str:
        """
        Build a Change Impact Analysis report for display before modification.

        Shows the user exactly what will be affected by changing a file.
        """
        impact = self.brain.get_impact_analysis(file_path)

        lines = [f"=== CHANGE IMPACT ANALYSIS: {file_path} ==="]

        if impact["affected_files"]:
            lines.append(f"\nAffected Files ({len(impact['affected_files'])}):")
            for f in impact["affected_files"][:20]:
                lines.append(f"  - {f}")

        if impact["affected_services"]:
            lines.append(f"\nAffected Services ({len(impact['affected_services'])}):")
            for s in impact["affected_services"]:
                lines.append(f"  - {s}")

        if impact["affected_subsystems"]:
            lines.append(f"\nAffected Subsystems ({len(impact['affected_subsystems'])}):")
            for s in impact["affected_subsystems"]:
                lines.append(f"  - {s}")

        if not any(impact.values()):
            lines.append("\nNo downstream dependencies detected.")

        lines.append("=" * 50)
        return "\n".join(lines)

    # ── Formatters ────────────────────────────────────────────────────

    def _format_architecture_overview(self, overview: List[Dict]) -> str:
        """Format the high-level architecture for the LLM."""
        lines = ["=== SYSTEM ARCHITECTURE OVERVIEW ==="]
        for entry in overview:
            name = entry.get("subsystem", "Unknown")
            purpose = entry.get("purpose", "")
            services = entry.get("services", [])
            file_count = entry.get("file_count", 0)
            lines.append(f"\n  [{name}] ({file_count} files)")
            if purpose:
                lines.append(f"    Purpose: {purpose}")
            if services:
                lines.append(f"    Services: {', '.join(str(s) for s in services if s)}")
        lines.append("=" * 40)
        return "\n".join(lines)

    def _format_subsystem_context(self, subsystem: Dict) -> str:
        """Format the owning subsystem info."""
        name = subsystem.get("name", "Unknown")
        purpose = subsystem.get("purpose", "")
        desc = subsystem.get("description", "")
        lines = [f"=== CURRENT SUBSYSTEM: {name} ==="]
        if purpose:
            lines.append(f"Purpose: {purpose}")
        if desc:
            lines.append(f"Description: {desc[:500]}")
        lines.append("=" * 40)
        return "\n".join(lines)

    def _format_dependency_registry(self, dep_paths: List[str]) -> str:
        """Format AST registry entries for direct dependencies only."""
        if not dep_paths:
            return ""

        lines = ["=== DEPENDENCY FILE SIGNATURES ==="]
        for dep_path in dep_paths[:15]:  # Cap at 15 to save tokens
            # Find matching entry in the v1 file registry
            entry = next((e for e in self.state.file_registry if e.path == dep_path), None)
            if entry:
                lines.append(entry.to_registry_string())
        lines.append("=" * 40)
        return "\n".join(lines) if len(lines) > 2 else ""

    def _format_related_files(self, related: List[Dict]) -> str:
        """Format graph-retrieved related files."""
        lines = ["=== RELATED FILES (from Knowledge Graph) ==="]
        for entry in related[:10]:
            path = entry.get("path", "")
            purpose = entry.get("purpose", "")
            rels = entry.get("relationships", [])
            rel_str = " → ".join(str(r) for r in rels) if rels else ""
            lines.append(f"  {path}")
            if purpose:
                lines.append(f"    Purpose: {purpose}")
            if rel_str:
                lines.append(f"    Relationship: {rel_str}")
        lines.append("=" * 40)
        return "\n".join(lines)

    def _format_similar_files(self, similar: List[Dict]) -> str:
        """Format semantically similar files from ChromaDB."""
        lines = ["=== SEMANTICALLY SIMILAR FILES ==="]
        for entry in similar[:5]:
            path = entry.get("file_path", entry.get("id", ""))
            purpose = entry.get("purpose", "")
            distance = entry.get("distance", 1.0)
            lines.append(f"  {path} (similarity: {1 - distance:.2f})")
            if purpose:
                lines.append(f"    Purpose: {purpose}")
        lines.append("=" * 40)
        return "\n".join(lines)

    def _format_adrs(self, adrs: List[Dict]) -> str:
        """Format relevant Architectural Decision Records."""
        lines = ["=== RELEVANT DESIGN DECISIONS (ADRs) ==="]
        for adr in adrs[:3]:
            title = adr.get("title", "")
            doc = adr.get("document", "")
            if title:
                lines.append(f"\n  ADR: {title}")
            if doc:
                # Truncate long ADR documents
                lines.append(f"    {doc[:300]}")
        lines.append("=" * 40)
        return "\n".join(lines)
