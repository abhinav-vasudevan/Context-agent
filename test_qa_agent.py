import asyncio
from pathlib import Path
import os
import sys

# Add Context-agent to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.qa_agent import QAAgent
from core.llm_client import LLMClient

async def run_test():
    workspace = Path(__file__).parent / "projects" / "qa_test"
    workspace.mkdir(parents=True, exist_ok=True)
    
    # 1. Create a mock Calculator app
    calc_path = workspace / "main.py"
    calc_path.write_text("""
import sys

print("Welcome to the CLI Calculator!")
print("Type 'exit' to quit.")

while True:
    try:
        expr = input("Enter expression (e.g. 5 + 5): ")
        if expr.strip().lower() == 'exit':
            break
        result = eval(expr)
        print(f"Result: {result}")
    except Exception as e:
        print(f"Error: {e}")
""", encoding="utf-8")

    # 2. Run QA Agent against it
    llm = LLMClient()
    qa = QAAgent(llm, original_prompt="Build a CLI calculator that evaluates math expressions and prints the result.")
    
    def on_stdout(text):
        print(text, end="")
        
    def on_stderr(text):
        print(text, end="", file=sys.stderr)
        
    def on_status(text):
        print(f"\n[STATUS] {text}\n")
        
    print("=== TESTING QA AGENT ===")
    result = await qa.test_application(
        python_cmd="python3",
        main_file="main.py",
        workspace=str(workspace),
        on_stdout=on_stdout,
        on_stderr=on_stderr,
        on_status=on_status
    )
    
    print("\n\n=== QA AGENT RESULT ===")
    print(f"Success: {result.success}")
    for i, interaction in enumerate(result.interactions):
        print(f"Interaction {i+1}:")
        print(f"  Prompt: {interaction['prompt']}")
        print(f"  Agent Typed: {interaction['response']}")

if __name__ == "__main__":
    asyncio.run(run_test())
