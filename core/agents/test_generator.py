import logging
from typing import Dict, List, Optional
from pathlib import Path

from core.llm_client import LLMClient
from models.hierarchy import ModuleSpec

log = logging.getLogger(__name__)

class TestGeneratorAgent:
    """
    Generates Pytest tests based on Contract-First skeletons.
    This enables Test-Driven Development (TDD) as part of Phase 8.
    """
    
    SYSTEM_PROMPT = """You are an expert QA Engineer. 
You are presented with a Python stub file (skeleton) containing empty methods and classes.
Your task is to write comprehensive Pytest test cases for this skeleton.
Assume the logic will be implemented shortly.

Rules:
1. Use `pytest` style, not `unittest`.
2. Mock external dependencies using `unittest.mock`.
3. Include edge cases and error handling tests.
4. Output ONLY the raw python test code. Do not output markdown codeblocks like ```python...```. Do not output explanations.
"""

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def generate_tests(self, stubs: Dict[str, str], on_token=None) -> Dict[str, str]:
        """
        Generate pytest files for the given stubs.
        Returns a dict of {test_file_path: test_code}.
        """
        tests = {}
        for original_path, stub_content in stubs.items():
            if not original_path.endswith(".py") or "test_" in original_path:
                continue
                
            path_obj = Path(original_path)
            test_file_name = f"test_{path_obj.name}"
            test_path = path_obj.parent / test_file_name
            test_path_str = str(test_path).replace("\\", "/")
            
            prompt = f"TARGET FILE PATH: {original_path}\n\nSTUB CONTENT:\n{stub_content}\n\nWrite the pytest suite for this stub now."
            
            log.info(f"TestGeneratorAgent: Generating tests for {original_path}")
            
            chunks = []
            async for chunk in self.llm.generate_stream(
                prompt=prompt,
                system=self.SYSTEM_PROMPT,
                on_token=on_token
            ):
                chunks.append(chunk)
                
            test_code = "".join(chunks).strip()
            
            # Clean up markdown formatting if the LLM leaked it despite instructions
            if test_code.startswith("```python"):
                test_code = test_code[9:]
            elif test_code.startswith("```"):
                test_code = test_code[3:]
            if test_code.endswith("```"):
                test_code = test_code[:-3]
                
            tests[test_path_str] = test_code.strip()
            
        return tests
