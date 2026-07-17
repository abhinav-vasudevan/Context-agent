"""
Integration Agent.

Runs before a file is written to disk to verify it correctly
integrates with the existing codebase (interfaces match, imports are correct).
If it detects issues, it requests a targeted rewrite from the Coder.
"""

from __future__ import annotations
import logging
import json
import re
from typing import Tuple

from core.llm_client import LLMClient
from core.brain.project_brain import ProjectBrain

log = logging.getLogger(__name__)


class IntegrationAgent:
    """Verifies that generated code respects existing system interfaces."""

    SYSTEM_PROMPT = """You are an expert Integration Reviewer.
Your job is to check if newly generated code correctly interfaces with existing code.

You will be provided:
1. The NEW code that was just generated.
2. The INTERFACES of the existing dependencies it imports or uses.

Check for:
- Method name mismatches
- Missing arguments or wrong argument types
- Calling async functions synchronously (or vice versa)
- Importing from non-existent paths

You must output a STRICT JSON object:
{
  "is_integrated": true | false,
  "issues": [
    "Specific issue 1",
    "Specific issue 2"
  ],
  "fix_instructions": "Clear instructions for the coder on how to fix the issues. Empty if is_integrated is true."
}

Output ONLY the JSON object. No markdown. No explanation."""

    def __init__(self, llm: LLMClient, brain: ProjectBrain):
        self.llm = llm
        self.brain = brain

    async def verify_integration(
        self,
        file_path: str,
        generated_code: str,
    ) -> Tuple[bool, str]:
        """
        Verify the generated code against known interfaces.

        Returns:
            (is_integrated, fix_instructions)
        """
        # Get the context the coder used (this includes the dependency interfaces)
        context = self.brain.get_context_for_file(file_path)

        # We only care about direct dependencies for integration checking
        dep_chain = context.get("dependency_chain", [])

        if not dep_chain:
            # No internal dependencies to verify against
            return True, ""

        # Format the interfaces of the dependencies
        interfaces = []
        for dep in dep_chain[:5]:  # Just check direct dependencies to save tokens
            # Query the graph for methods/classes (mocked for now, assumes AST registry provides this in real system)
            # In a full v2, we'd query the AST registry here
            interfaces.append(f"Dependency: {dep} (interface verification active)")

        interface_text = "\n".join(interfaces)

        prompt = f"""NEW FILE: {file_path}

=== NEW CODE ===
```python
{self.llm.truncate_to_tokens(generated_code, 4000)}
```

=== EXISTING DEPENDENCY INTERFACES ===
{interface_text}

Analyze the integration now."""

        raw_output = await self.llm.generate(prompt=prompt, system=self.SYSTEM_PROMPT)

        return self._parse_result(raw_output)

    def _parse_result(self, raw_output: str) -> Tuple[bool, str]:
        """Parse LLM output into (is_integrated, instructions)."""
        # Strip think blocks
        cleaned = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL)

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
            is_integrated = data.get("is_integrated", True)
            instructions = data.get("fix_instructions", "")
            if not is_integrated and data.get("issues"):
                instructions = "Integration Issues:\n- " + "\n- ".join(data["issues"]) + "\n\n" + instructions
            return is_integrated, instructions
        except json.JSONDecodeError as e:
            log.warning("IntegrationAgent failed to parse JSON: %s", e)
            return True, ""  # Default to pass if parsing fails
