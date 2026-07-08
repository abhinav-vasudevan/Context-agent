import re

with open('backend/orchestrator.py', 'r') as f:
    content = f.read()

replacement = """
        try:
            intent_raw = await self.llm.generate(prompt=intent_prompt, system="You are an intent classifier. Respond with ONE word.")
            intent = intent_raw.strip().lower()
            if "doc" in intent or "chat" in intent or "sum" in intent or intent == "document_task":
                intent_type = "document_task"
            elif "bug" in intent or "fix" in intent or "error" in intent:
                intent_type = "bug_fix"
            else:
                intent_type = "feature_update"
        except Exception:
            intent_type = "feature_update"  # default to feature if LLM fails here

        if intent_type == "document_task":
            await self.ws.send_status("planning", "Request classified as Document Task. Reading documents...")
            if file_paths:
                for fp in file_paths:
                    from pathlib import Path
                    await self.doc_ingester.ingest_document(fp, Path(fp).name, on_status=self.ws.send_status)
            
            await self.chat_agent.process_task(prompt, self.state.user_documents)
            return {"success": True, "message": "Document task processed."}

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

content = re.sub(r'\s*try:\n\s*intent_raw = await self.llm.generate\(prompt=intent_prompt, system="You are an intent classifier\. Respond with ONE word\."\)\n\s*intent = intent_raw\.strip\(\)\.lower\(\)\n\s*except Exception:\n\s*is_feature = True  # default to feature if LLM fails here\n\n\s*if is_feature:\n\s*await self\.ws\.send_status\("planning", "Request classified as Feature Update\. Generating new plan\.\.\."\)\n\s*return await self\._update_project\(prompt\)', replacement, content, count=1)

with open('backend/orchestrator.py', 'w') as f:
    f.write(content)

print("Fixed intent parsing in orchestrator.py")
