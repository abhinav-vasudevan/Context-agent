import logging
import json
import re
from typing import List, Dict, Callable, Optional
from core.llm_client import LLMClient
from models.hierarchy import ModuleSpec

log = logging.getLogger(__name__)

class ArchitectAgent:
    """
    Agent responsible for Contract-First development.
    Generates strict stub files (skeletons) for all modules in a sprint BEFORE implementation.
    This entirely eliminates "Code Stitching" errors by establishing the API boundaries upfront.
    """

    SYSTEM_PROMPT = """You are a Principal Software Architect.
Your task is to generate strict Contract-First stub files for the provided list of modules.

CRITICAL INSTRUCTIONS:
1. You MUST generate the skeleton code for EVERY module listed.
2. Skeletons MUST contain:
   - All necessary import statements
   - Class definitions with method signatures (including type hints)
   - Standalone function signatures (including type hints)
   - Constants or global variables if mentioned in the description
3. Skeletons MUST NOT contain any implementation logic.
   - Use `pass` or `raise NotImplementedError("Stub - to be implemented")` for all bodies.
4. DO NOT invent classes or functions that aren't strongly implied by the module description or dependencies.
5. You MUST output ONLY a valid JSON object matching this schema:
{
  "stubs": {
    "src/file1.py": "import os\\n\\nclass MyClass:\\n    def __init__(self):\\n        raise NotImplementedError()",
    "src/file2.py": "def my_func(a: int) -> bool:\\n    pass"
  }
}
DO NOT use <think> tags. DO NOT output markdown outside the JSON.
"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def generate_stubs(
        self,
        sprint_modules: List[ModuleSpec],
        on_token: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None
    ) -> Dict[str, str]:
        """
        Generate skeleton code for a list of modules.
        Returns a dict mapping file_path to the stub code.
        """
        if not sprint_modules:
            return {}

        log.info(f"ArchitectAgent: Generating stubs for {len(sprint_modules)} modules")

        # Build prompt
        module_descriptions = []
        for mod in sprint_modules:
            desc = f"- Path: {mod.file_path}\n  Description: {mod.description}"
            if mod.exports:
                desc += f"\n  Expected Exports: {', '.join(mod.exports)}"
            module_descriptions.append(desc)

        user_prompt = "Generate stubs for the following modules:\n\n" + "\n\n".join(module_descriptions)

        chunks = []
        async for chunk in self.llm.generate_stream(
            prompt=user_prompt,
            system=self.SYSTEM_PROMPT,
            on_token=on_token,
            on_thinking=on_thinking,
        ):
            chunks.append(chunk)

        raw_output = "".join(chunks)

        # Parse JSON
        cleaned = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL)
        cleaned = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', cleaned, flags=re.DOTALL)
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
            return data.get("stubs", {})
        except Exception as e:
            log.error(f"Failed to parse stub JSON: {e}")
            return {}
