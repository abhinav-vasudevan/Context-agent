import re

with open('backend/orchestrator.py', 'r') as f:
    content = f.read()

# Fix generate_plan signature
content = content.replace('async def generate_plan(self, prompt: str = "") -> dict:', 'async def generate_plan(self, prompt: str = "", file_paths: list[str] = None) -> dict:')

# Find the spot after setting original_prompt to process file_paths and extract requirements
# Look around line 298: 
#             if not self.state.original_prompt:
#                 return {"success": False, "error": "No prompt provided"}

insertion = """
            if not self.state.original_prompt:
                return {"success": False, "error": "No prompt provided"}

            if file_paths:
                for fp in file_paths:
                    from pathlib import Path
                    await self.doc_ingester.ingest_document(fp, Path(fp).name, on_status=self.ws.send_status)
                
                extracted_reqs = await self.chat_agent.process_task(
                    "Extract a detailed master specification and architecture plan from these documents to build the software.",
                    self.state.user_documents, 
                    return_result=True
                )
                self.state.global_master_summary = extracted_reqs
                self.state.save(self.workspace_dir / "project_state.json")
"""

content = re.sub(r'\s*if not self\.state\.original_prompt:\s*return \{"success": False, "error": "No prompt provided"\}', insertion, content, count=1)

with open('backend/orchestrator.py', 'w') as f:
    f.write(content)

print("Fixed generate_plan in orchestrator.py")
