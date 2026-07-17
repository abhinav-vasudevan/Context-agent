"""
Architecture Validator.

Ensures that the actual generated code does not violate the boundaries
established in the Knowledge Graph (Neo4j).

Example: If the "Frontend" subsystem imports from the "Database" subsystem
directly instead of through the "API" subsystem, this validator catches it.
"""

from __future__ import annotations
import ast
import logging
from typing import Tuple, List

from core.brain.project_brain import ProjectBrain

log = logging.getLogger(__name__)


class ArchitectureValidator:
    """Validates code against architectural boundaries."""

    def __init__(self, brain: ProjectBrain):
        self.brain = brain

    def validate_file_imports(self, file_path: str, code_content: str) -> Tuple[bool, List[str]]:
        """
        Parse imports in the generated code and verify they don't violate
        subsystem boundaries defined in the architecture spec.
        """
        if not self.brain.graph.is_available:
            return True, []

        try:
            tree = ast.parse(code_content)
        except SyntaxError:
            # Syntax errors are handled by StaticAnalyzer, ignore here
            return True, []

        # Extract all internal imports (starting with 'src.')
        internal_imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith("src."):
                    internal_imports.append(node.module.replace(".", "/") + ".py")
            elif isinstance(node, ast.Import):
                for name in node.names:
                    if name.name.startswith("src."):
                        internal_imports.append(name.name.replace(".", "/") + ".py")

        if not internal_imports:
            return True, []

        # Get the subsystem that owns this file
        owning_subsystem_info = self.brain.graph.get_subsystem_for_file(file_path)
        if not owning_subsystem_info:
            return True, []

        owning_subsystem_name = owning_subsystem_info.get("name")

        violations = []
        # Check each import against the allowed boundaries
        for imp_path in internal_imports:
            target_subsystem_info = self.brain.graph.get_subsystem_for_file(imp_path)
            if not target_subsystem_info:
                continue

            target_subsystem_name = target_subsystem_info.get("name")

            # If importing from a different subsystem, check if it's an allowed dependency
            if target_subsystem_name and target_subsystem_name != owning_subsystem_name:
                # In a full graph query, we'd check:
                # MATCH (a:Subsystem {name: owning})-[r:DEPENDS_ON]->(b:Subsystem {name: target})

                # For this implementation, we simply warn if boundaries are crossed
                # (The LLM integration agent will review these warnings)
                violations.append(
                    f"Boundary crossing: '{owning_subsystem_name}' imports from '{target_subsystem_name}' "
                    f"(via {imp_path})"
                )

        if violations:
            log.warning("Architecture violations found in %s: %s", file_path, violations)
            return False, violations

        return True, []
