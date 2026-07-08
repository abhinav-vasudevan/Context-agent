with open('backend/orchestrator.py', 'r') as f:
    lines = f.readlines()

# find index of "try:" after intent_prompt
try_index = -1
for i, line in enumerate(lines):
    if 'try:' in line and 'intent_raw = await self.llm.generate' in lines[i+1]:
        try_index = i
        break

if try_index != -1:
    # find where the if is_feature block ends
    end_index = -1
    for i in range(try_index, len(lines)):
        if 'return await self._update_project(prompt)' in lines[i]:
            end_index = i
            break
            
    if end_index != -1:
        replacement = """        try:
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
        
        del lines[try_index:end_index+1]
        lines.insert(try_index, replacement)
        
        with open('backend/orchestrator.py', 'w') as f:
            f.writelines(lines)
            
        print(f"SUCCESS: Replaced from line {try_index} to {end_index}")
    else:
        print("FAILED: Could not find end index")
else:
    print("FAILED: Could not find try_index")
