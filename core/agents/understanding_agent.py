import logging
import re
from typing import Optional, Callable
from core.llm_client import LLMClient
from core.brain.project_brain import ProjectBrain

log = logging.getLogger(__name__)

class UnderstandingAgent:
    """
    Agent responsible for analyzing a newly ingested codebase and generating
    an in-depth architectural map and file summary for the LLM's future reference.
    """

    SYSTEM_PROMPT = """You are a Principal Software Architect.
Your task is to analyze the provided list of files, their relationships, and semantic summaries from a newly ingested codebase.
You must output a highly detailed `architecture.md` document that maps out the entire project.

CRITICAL INSTRUCTIONS:
1. Explain the primary purpose of the project.
2. Identify the main entry points (e.g., main.py, server.py, index.js, cli.py) based on standard conventions or provided data.
3. Group the files into logical Subsystems or Modules (e.g., Backend, Frontend, Core Logic, Database).
4. For every file provided, explain exactly what it does, what it is responsible for, and how it connects to other files (based on the imports/relationships shown).
5. Output ONLY raw markdown. Do NOT wrap it in JSON. Do NOT use <think> tags in the final output markdown (you may use <think> before it).
6. Make this document extremely in-depth so that another AI agent reading it will instantly know exactly where to go to fix a bug or add a feature.
"""

    def __init__(self, llm: LLMClient, brain: ProjectBrain):
        self.llm = llm
        self.brain = brain

    async def analyze_codebase(
        self,
        on_token: Optional[Callable] = None,
        on_thinking: Optional[Callable] = None
    ) -> str:
        """
        Analyze the graph and semantic summaries, and generate a markdown architecture map.
        """
        log.info("UnderstandingAgent: Generating codebase architecture map")
        
        # 1. Fetch file list and basic relationships from Neo4j
        files_data = []
        if self.brain.graph and self.brain.graph.is_available:
            try:
                # Fetch all files and the symbols they contain
                query = """
                MATCH (f:File)
                OPTIONAL MATCH (f)-[:CONTAINS]->(s:Symbol)
                RETURN f.path AS path, collect(s.name) AS symbols
                LIMIT 200
                """
                records = self.brain.graph.execute_query(query)
                for r in records:
                    files_data.append({
                        "path": r["path"],
                        "symbols": r["symbols"]
                    })
            except Exception as e:
                log.warning(f"Failed to query graph for files: {e}")

        # 2. Fetch semantic summaries for those files from ChromaDB (if available)
        # For simplicity in this prompt, we'll format the graph data and whatever semantic data we can easily grab.
        # Since we just summarized them in ingester.py, we can retrieve them.
        file_descriptions = []
        for file_info in files_data:
            path = file_info["path"]
            symbols = file_info["symbols"]
            
            # Try to get semantic summary
            summary = ""
            if self.brain.semantic and self.brain.semantic.is_available:
                summary = self.brain.semantic.get_file_summary(path)
            
            desc = f"### File: {path}\n"
            if symbols:
                desc += f"- Key Symbols (Classes/Functions): {', '.join(symbols[:20])}\n"
            if summary:
                desc += f"- Semantic Summary: {summary}\n"
            file_descriptions.append(desc)

        prompt = "Here is the raw data from the codebase ingestion. Please generate the detailed Architecture Map.\n\n"
        prompt += "\n\n".join(file_descriptions)
        
        chunks = []
        async for chunk in self.llm.generate_stream(
            prompt=prompt,
            system=self.SYSTEM_PROMPT,
            on_token=on_token,
            on_thinking=on_thinking,
        ):
            chunks.append(chunk)

        raw_output = "".join(chunks)
        
        # Clean up think tags if they leaked
        cleaned = re.sub(r'<think>.*?</think>', '', raw_output, flags=re.DOTALL)
        cleaned = re.sub(r'Thinking\.\.\..*?\.\.\.done thinking\.', '', cleaned, flags=re.DOTALL)
        
        return cleaned.strip()
