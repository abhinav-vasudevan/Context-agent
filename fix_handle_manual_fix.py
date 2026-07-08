import re

with open('backend/orchestrator.py', 'r') as f:
    content = f.read()

replacement = """
        if intent_type == "feature_update":
            await self.ws.send_status("planning", "Request classified as Feature Update. Generating new plan...")
            
            if file_paths:
                for fp in file_paths:
                    from pathlib import Path
                    await self.doc_ingester.ingest_document(fp, Path(fp).name, on_status=self.ws.send_status)
                
                extracted_reqs = await self.chat_agent.process_task(
                    "Extract a detailed master specification and architecture plan from these documents to build the requested feature.",
                    self.state.user_documents, 
                    return_result=True
                )
                self.state.global_master_summary = extracted_reqs
                self.state.save(self.workspace_dir / "project_state.json")
                
            return await self._update_project(prompt)
"""

content = re.sub(r'\s*if intent_type == "feature_update":\s*await self\.ws\.send_status\("planning", "Request classified as Feature Update\. Generating new plan\.\.\."\)\s*return await self\._update_project\(prompt\)', replacement, content)

with open('backend/orchestrator.py', 'w') as f:
    f.write(content)

print("Fixed handle_manual_fix in orchestrator.py")
