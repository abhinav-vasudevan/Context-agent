"""
Master Planner — converts a user prompt into a System Vision.

This is the TOP of the planning hierarchy. It does NOT plan files.
It identifies the major SUBSYSTEMS needed to fulfill the user's request.

Example:
    Input:  "Build an Ubuntu clone"
    Output: ArchitectureSpec with subsystems:
            [Kernel, Filesystem, Networking, Drivers, Package Manager, Shell, GUI]

The Master Planner also determines the SCALE of the system:
    - Simple script → 1 subsystem, 1-2 services, 3-5 files
    - Medium app    → 2-4 subsystems, 5-10 services, 10-20 files
    - Large system  → 5+ subsystems, 15+ services, 30+ files

This ensures the planning hierarchy adapts dynamically to complexity.
"""

from __future__ import annotations
import logging
import re
import json
from typing import Optional, Callable, List

from core.llm_client import LLMClient
from models.hierarchy import (
    ArchitectureSpec, SubsystemSpec, ServiceSpec, ModuleSpec,
    ArchitectureDecisionRecord, NodeStatus,
)

log = logging.getLogger(__name__)


class MasterPlanner:
    """
    Top-level planner that decomposes a user request into subsystems.

    The MasterPlanner pipeline:
      1. generate_vision()   → High-level system vision + subsystem list
      2. generate_architecture() → Detailed architecture with services per subsystem
      3. generate_modules()  → Concrete file list per service

    Each stage produces progressively more detail, and each stage's output
    is reviewed by the user before the next stage begins.
    """

    # ── System Prompts ────────────────────────────────────────────────

    VISION_SYSTEM_PROMPT = """You are a world-class Principal Software Architect.

Your job is to analyze a user's request and decompose it into a hierarchical system architecture.

You must output a STRICT JSON object (no markdown, no prose, no code fences) with this exact schema:

{
  "name": "Project Name",
  "vision": "A 2-3 sentence vision statement describing the system's purpose and design philosophy.",
  "scale": "small | medium | large",
  "subsystems": [
    {
      "name": "Subsystem Name",
      "purpose": "One sentence explaining why this subsystem exists.",
      "responsibilities": ["responsibility 1", "responsibility 2"],
      "boundaries": ["What this subsystem does NOT do"],
      "dependencies": ["Names of other subsystems it depends on"]
    }
  ],
  "adrs": [
    {
      "title": "Why use X for Y?",
      "context": "The problem being solved.",
      "decision": "What was decided.",
      "alternatives": "What other options were considered.",
      "consequences": "Tradeoffs and downstream effects."
    }
  ],
  "constraints": ["Global constraint 1", "Global constraint 2"]
}

SCALING RULES (CRITICAL):
- For a SIMPLE request (calculator, script, CLI tool): output 1 subsystem with clear purpose.
- For a MEDIUM request (web app, API, game): output 2-4 subsystems.
- For a LARGE request (OS, distributed system, AI agent): output 5-10+ subsystems.
- NEVER under-plan. If the user asks for something complex, you MUST decompose it deeply.
- NEVER over-plan. A calculator does NOT need 8 subsystems.

ADR RULES:
- For every non-obvious design decision, create an ADR.
- Examples: "Why use SQLite instead of PostgreSQL?", "Why REST instead of GraphQL?"
- Simple projects may have 0-1 ADRs. Complex projects should have 3-5+.

Output ONLY the JSON object. No markdown. No explanation. No code fences."""

    SERVICES_SYSTEM_PROMPT = """You are a world-class Principal Software Architect.

You are given a system architecture with subsystems. Your job is to break each subsystem
into concrete SERVICES and MODULES (files).

You must output a STRICT JSON object (no markdown, no prose, no code fences) with this schema:

{
  "subsystems": [
    {
      "name": "Subsystem Name (must match input exactly)",
      "services": [
        {
          "name": "Service Name",
          "description": "What this service does and its public API contract.",
          "responsibilities": ["responsibility 1", "responsibility 2"],
          "interfaces": ["public_method_1(arg: type) -> return_type"],
          "dependencies": ["Names of other services it depends on"],
          "modules": [
            {
              "name": "Module Name",
              "file_path": "src/subsystem_name/module_name.py",
              "description": "Detailed description of this file's contents, including class names, function signatures, and internal logic.",
              "exports": ["ClassName", "function_name"],
              "dependencies": ["src/other_module.py"]
            }
          ]
        }
      ]
    }
  ]
}

MANDATORY RULES:
1. Every subsystem from the input MUST appear in the output.
2. File paths MUST use src/<subsystem_name>/<module_name>.py format for complex projects.
3. For simple projects (1 subsystem), use flat src/<module_name>.py format.
4. Every service MUST have at least 1 module.
5. Step 1 is ALWAYS main.py at the root (NOT in src/).
6. The LAST file is ALWAYS README.md.
7. Include a requirements.txt module.
8. Include an __init__.py for each subdirectory under src/.
9. Module descriptions must include exact class names, function signatures with types, and algorithm logic.
10. NEVER use placeholder descriptions. Be EXHAUSTIVELY specific.

Output ONLY the JSON object. No markdown. No explanation. No code fences."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    # ── Stage 1: System Vision ────────────────────────────────────────

    async def generate_vision(
        self,
        user_prompt: str,
        on_token: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None,
    ) -> ArchitectureSpec:
        """
        Stage 1: Convert user prompt into a System Vision with subsystems.

        Returns an ArchitectureSpec with populated subsystems but NO services/modules yet.
        Those are filled in by generate_services().
        """
        log.info("MasterPlanner: generating vision for prompt (len=%d)", len(user_prompt))

        chunks = []
        async for chunk in self.llm.generate_stream(
            prompt=f"USER REQUEST:\n{user_prompt}\n\nDecompose this into a hierarchical system architecture now.",
            system=self.VISION_SYSTEM_PROMPT,
            on_token=on_token,
            on_thinking=on_thinking,
        ):
            chunks.append(chunk)

        raw_output = "".join(chunks)
        return self._parse_vision(raw_output)

    def _parse_vision(self, raw_output: str) -> ArchitectureSpec:
        """Parse the LLM's JSON output into an ArchitectureSpec."""
        # Strip think blocks
        cleaned = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL)
        cleaned = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', cleaned, flags=re.DOTALL)

        # Extract JSON from potential markdown fences
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(1)

        # Try to find the JSON object
        cleaned = cleaned.strip()
        # Find first { and last }
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error("Failed to parse vision JSON: %s\nRaw output:\n%s", e, raw_output[:500])
            # Fallback: create a basic single-subsystem architecture
            return ArchitectureSpec(
                name="Project",
                vision="Generated from user request",
                description=raw_output[:500],
                subsystems=[SubsystemSpec(name="Core", purpose="Main application logic")],
            )

        # Build ArchitectureSpec from parsed JSON
        arch = ArchitectureSpec(
            name=data.get("name", "Project"),
            vision=data.get("vision", ""),
            description=data.get("vision", ""),
            constraints=data.get("constraints", []),
        )

        # Parse subsystems
        for sub_data in data.get("subsystems", []):
            subsystem = SubsystemSpec(
                name=sub_data.get("name", "Unknown"),
                purpose=sub_data.get("purpose", ""),
                description=sub_data.get("purpose", ""),
                responsibilities=sub_data.get("responsibilities", []),
                boundaries=sub_data.get("boundaries", []),
                # Dependencies are stored as names, resolved to IDs later
            )
            arch.subsystems.append(subsystem)

        # Resolve subsystem dependency names to IDs
        name_to_id = {s.name: s.id for s in arch.subsystems}
        for sub_data, subsystem in zip(data.get("subsystems", []), arch.subsystems):
            dep_names = sub_data.get("dependencies", [])
            subsystem.dependencies = [name_to_id[n] for n in dep_names if n in name_to_id]

        # Parse ADRs
        for adr_data in data.get("adrs", []):
            adr = ArchitectureDecisionRecord(
                title=adr_data.get("title", ""),
                context=adr_data.get("context", ""),
                decision=adr_data.get("decision", ""),
                alternatives=adr_data.get("alternatives", ""),
                consequences=adr_data.get("consequences", ""),
            )
            arch.adrs.append(adr)

        log.info(
            "MasterPlanner: parsed vision — %d subsystems, %d ADRs",
            len(arch.subsystems), len(arch.adrs),
        )
        return arch

    # ── Stage 2: Service & Module Decomposition ───────────────────────

    async def generate_services(
        self,
        arch: ArchitectureSpec,
        user_prompt: str,
        on_token: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None,
    ) -> ArchitectureSpec:
        """
        Stage 2: Break subsystems into services and concrete modules (files).

        Takes the ArchitectureSpec from Stage 1 and populates each subsystem
        with ServiceSpecs containing ModuleSpecs (file paths + descriptions).
        """
        log.info("MasterPlanner: generating services for %d subsystems", len(arch.subsystems))

        # Build a concise description of the architecture for the LLM
        arch_summary = json.dumps({
            "name": arch.name,
            "vision": arch.vision,
            "constraints": arch.constraints,
            "subsystems": [
                {
                    "name": s.name,
                    "purpose": s.purpose,
                    "responsibilities": s.responsibilities,
                    "boundaries": s.boundaries,
                }
                for s in arch.subsystems
            ],
        }, indent=2)

        prompt = f"""USER REQUEST:
{user_prompt}

SYSTEM ARCHITECTURE (from Stage 1):
{arch_summary}

Break each subsystem into concrete services and file modules now."""

        chunks = []
        async for chunk in self.llm.generate_stream(
            prompt=prompt,
            system=self.SERVICES_SYSTEM_PROMPT,
            on_token=on_token,
            on_thinking=on_thinking,
        ):
            chunks.append(chunk)

        raw_output = "".join(chunks)
        return self._parse_services(raw_output, arch)

    def _parse_services(self, raw_output: str, arch: ArchitectureSpec) -> ArchitectureSpec:
        """Parse services JSON and merge into the existing ArchitectureSpec."""
        # Strip think blocks
        cleaned = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL)
        cleaned = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', cleaned, flags=re.DOTALL)

        # Extract JSON
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', cleaned, re.DOTALL)
        if json_match:
            cleaned = json_match.group(1)

        cleaned = cleaned.strip()
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            cleaned = cleaned[start:end + 1]

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            log.error("Failed to parse services JSON: %s", e)
            # Fallback: create default services for each subsystem
            for subsystem in arch.subsystems:
                if not subsystem.services:
                    subsystem.services = [
                        ServiceSpec(
                            name=f"{subsystem.name} Core",
                            description=subsystem.purpose,
                            modules=[
                                ModuleSpec(
                                    name=f"{subsystem.name.lower().replace(' ', '_')}_core",
                                    file_path=f"src/{subsystem.name.lower().replace(' ', '_')}.py",
                                    description=subsystem.purpose,
                                )
                            ],
                        )
                    ]
            return arch

        # Map subsystem names to existing ArchitectureSpec subsystems
        name_to_subsystem = {s.name: s for s in arch.subsystems}

        for sub_data in data.get("subsystems", []):
            sub_name = sub_data.get("name", "")
            subsystem = name_to_subsystem.get(sub_name)
            if not subsystem:
                log.warning("Service planner returned unknown subsystem: %s", sub_name)
                continue

            subsystem.services = []
            for svc_data in sub_data.get("services", []):
                service = ServiceSpec(
                    name=svc_data.get("name", "Unknown"),
                    description=svc_data.get("description", ""),
                    responsibilities=svc_data.get("responsibilities", []),
                    interfaces=svc_data.get("interfaces", []),
                )

                # Parse modules
                for mod_data in svc_data.get("modules", []):
                    module = ModuleSpec(
                        name=mod_data.get("name", ""),
                        file_path=mod_data.get("file_path", ""),
                        description=mod_data.get("description", ""),
                        exports=mod_data.get("exports", []),
                        dependencies=mod_data.get("dependencies", []),
                    )
                    service.modules.append(module)

                subsystem.services.append(service)

        log.info("MasterPlanner: parsed services — total modules: %d", len(arch.get_all_modules()))
        return arch

    # ── Conversion to v1 PlanSteps ────────────────────────────────────

    def flatten_to_plan_steps(self, arch: ArchitectureSpec) -> list:
        """
        Convert the hierarchical ArchitectureSpec into a flat list of
        v1-compatible PlanSteps for the existing Orchestrator to execute.

        This bridges v2 planning with v1 execution — the orchestrator
        still iterates through steps one by one, but now the steps
        are derived from a hierarchical architecture.
        """
        from models.state import PlanStep

        steps = []
        step_number = 1

        # Step 1: main.py (always first)
        steps.append(PlanStep(
            step_number=step_number,
            title="Create main.py entry point",
            file_path="main.py",
            description=(
                "Create a completely empty main.py file. Only include "
                "`if __name__ == '__main__':` followed by `pass`. "
                "Do NOT add any imports — the system will wire this up automatically."
            ),
        ))
        step_number += 1

        # Iterate through the hierarchy to build ordered steps
        for subsystem in arch.subsystems:
            for service in subsystem.services:
                for module in service.modules:
                    if module.file_path in ("main.py", "README.md", "requirements.txt"):
                        continue

                    # Build a rich description that includes architecture context
                    description = module.description
                    if service.interfaces:
                        description += f"\n\nService Interfaces: {', '.join(service.interfaces)}"
                    if module.exports:
                        description += f"\nExpected Exports: {', '.join(module.exports)}"

                    # Calculate dependencies (step numbers of modules we depend on)
                    depends_on = [1]  # All files depend on main.py
                    for dep_path in module.dependencies:
                        dep_step = next(
                            (s for s in steps if s.file_path == dep_path),
                            None,
                        )
                        if dep_step:
                            depends_on.append(dep_step.step_number)

                    steps.append(PlanStep(
                        step_number=step_number,
                        title=f"{subsystem.name}/{service.name}: {module.name}",
                        file_path=module.file_path,
                        description=description,
                        depends_on=depends_on,
                    ))
                    step_number += 1

        # requirements.txt (depends on all code files)
        code_steps = [s.step_number for s in steps if s.file_path.endswith('.py')]
        steps.append(PlanStep(
            step_number=step_number,
            title="Create requirements.txt",
            file_path="requirements.txt",
            description="List all third-party pip dependencies used by the project.",
            depends_on=code_steps,
        ))
        step_number += 1

        # README.md (always last, depends on everything)
        all_steps = [s.step_number for s in steps]
        steps.append(PlanStep(
            step_number=step_number,
            title="Create README.md",
            file_path="README.md",
            description=(
                "Create comprehensive documentation. Include: project description, "
                "architecture overview with subsystems, how to activate venv, "
                "how to install dependencies, how to run, all features built, "
                "and any manual setup required."
            ),
            depends_on=all_steps,
        ))

        log.info("MasterPlanner: flattened to %d plan steps", len(steps))
        return steps

    # ── Display Helpers ───────────────────────────────────────────────

    def format_vision_for_display(self, arch: ArchitectureSpec) -> str:
        """Format the architecture spec for user review in the UI."""
        lines = []
        lines.append(f"# {arch.name}")
        lines.append(f"\n{arch.vision}\n")

        if arch.constraints:
            lines.append("## Constraints")
            for c in arch.constraints:
                lines.append(f"  - {c}")

        lines.append(f"\n## Subsystems ({len(arch.subsystems)})")
        for sub in arch.subsystems:
            lines.append(f"\n### {sub.name}")
            lines.append(f"  Purpose: {sub.purpose}")
            if sub.responsibilities:
                lines.append(f"  Responsibilities:")
                for r in sub.responsibilities:
                    lines.append(f"    - {r}")
            if sub.services:
                lines.append(f"  Services ({len(sub.services)}):")
                for svc in sub.services:
                    mod_count = len(svc.modules)
                    lines.append(f"    - {svc.name} ({mod_count} modules)")
                    for mod in svc.modules:
                        lines.append(f"      → {mod.file_path}")

        if arch.adrs:
            lines.append(f"\n## Design Decisions ({len(arch.adrs)})")
            for adr in arch.adrs:
                lines.append(f"\n  **{adr.title}**")
                lines.append(f"  Decision: {adr.decision}")
                if adr.consequences:
                    lines.append(f"  Consequences: {adr.consequences}")

        return "\n".join(lines)
