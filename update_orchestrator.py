import re

with open('backend/orchestrator.py', 'r') as f:
    content = f.read()

# Replace the intent handling in handle_manual_fix
new_intent_block = """
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
            return await self._update_project(prompt)
"""

pattern = re.compile(r'        try:\n            intent_raw = await self\.llm\.generate\(prompt=intent_prompt, system="You are an intent classifier\. Respond with ONE word\."\)\n            intent = intent_raw\.strip\(\)\.lower\(\)\n        except Exception:\n            is_feature = True  # default to feature if LLM fails here\n\n        if is_feature:\n            await self\.ws\.send_status\("planning", "Request classified as Feature Update\. Generating new plan\.\.\."\)\n            return await self\._update_project\(prompt\)')

new_content = pattern.sub(new_intent_block.lstrip('\n'), content)

with open('backend/orchestrator.py', 'w') as f:
    f.write(new_content)

print("Updated orchestrator.py")
