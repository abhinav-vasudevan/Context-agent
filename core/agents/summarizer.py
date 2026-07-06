"""
Summarization Agent.

Runs after a file is generated or modified.
Reads the raw source code and uses the LLM to extract a SemanticSummary
which is then stored in the Project Brain (ChromaDB + Neo4j).
"""

from __future__ import annotations
import logging
import json
import re
from typing import Optional

from core.llm_client import LLMClient
from models.hierarchy import SemanticSummary

log = logging.getLogger(__name__)


class SummarizerAgent:
    """Extracts semantic meaning from raw code for storage in the Project Brain."""

    SYSTEM_PROMPT = """You are an expert Code Analyst.
Read the provided source code and extract its semantic meaning.
You must output a STRICT JSON object with this exact schema:

{
  "purpose": "A 1-2 sentence high-level summary of what this file does.",
  "responsibilities": [
    "Specific functional responsibility 1",
    "Specific functional responsibility 2"
  ],
  "exports": [
    "ClassName",
    "function_name"
  ],
  "dependencies": [
    "src/internal_module.py",
    "third_party_lib"
  ],
  "constraints": [
    "Must be thread-safe",
    "Requires Python 3.10+"
  ],
  "risks": [
    "Potential memory leak if cache not cleared",
    "Fails if network is down"
  ]
}

Focus on the BUSINESS LOGIC and SEMANTICS, not just syntax.
Output ONLY the JSON object. No markdown. No explanation."""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def summarize_file(self, file_path: str, code_content: str) -> Optional[SemanticSummary]:
        """
        Analyze code and return a SemanticSummary.
        """
        log.info("SummarizerAgent: analyzing %s (%d bytes)", file_path, len(code_content))

        # Truncate extremely long files to fit in context window if needed
        # We only need the essence of the file to summarize it
        truncated_code = self.llm.truncate_to_tokens(code_content, 4000)

        # Detect language for proper code fence
        lang = 'python'
        ext_map = {'.js': 'javascript', '.jsx': 'jsx', '.ts': 'typescript', '.tsx': 'tsx', '.css': 'css', '.html': 'html', '.md': 'markdown'}
        for ext, lang_name in ext_map.items():
            if file_path.endswith(ext):
                lang = lang_name
                break

        prompt = f"FILE PATH: {file_path}\n\nSOURCE CODE:\n```{lang}\n{truncated_code}\n```"

        raw_output = await self.llm.generate(prompt=prompt, system=self.SYSTEM_PROMPT)

        return self._parse_summary(raw_output, file_path)

    def _parse_summary(self, raw_output: str, file_path: str) -> Optional[SemanticSummary]:
        """Parse LLM output into a SemanticSummary object."""
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
            return SemanticSummary(
                entity_type="file",
                entity_path=file_path,
                purpose=data.get("purpose", ""),
                responsibilities=data.get("responsibilities", []),
                exports=data.get("exports", []),
                dependencies=data.get("dependencies", []),
                constraints=data.get("constraints", []),
                risks=data.get("risks", []),
            )
        except json.JSONDecodeError as e:
            log.warning("SummarizerAgent failed to parse JSON for %s: %s", file_path, e)
            return None
