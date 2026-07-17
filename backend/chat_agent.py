import asyncio
from typing import List
import logging
from core.llm_client import LLMClient
from models.state import ProjectState
from backend.ws_manager import ConnectionManager

log = logging.getLogger(__name__)

class ChatAgent:
    def __init__(self, llm: LLMClient, ws: ConnectionManager, state: ProjectState):
        self.llm = llm
        self.ws = ws
        self.state = state

    async def _stream_response(self, text: str):
        for char in text:
            await self.ws.send_llm_token(char)
            await asyncio.sleep(0.01)

    async def process_task(self, prompt: str, user_documents: List, return_result: bool = False) -> str:
        # We need to answer the user's prompt using the documents.
        # Since documents might be huge, we will do a map-reduce style read.

        if not user_documents:
            if not return_result:
                await self._stream_response("No documents are available to process this request.")
            return "No documents available."

        await self.ws.send_status("planning", f"Reading {len(user_documents)} documents...")

        import os
        from core.ingestion.chunker import RecursiveCharacterChunker
        chunker = RecursiveCharacterChunker(chunk_size=8000, overlap=400)

        all_chunk_summaries = []

        for idx, doc in enumerate(user_documents):
            await self.ws.send_status("planning", f"Reading document {idx+1}/{len(user_documents)}: {doc.filename}...")

            # Read file text
            text = ""
            ext = doc.file_path.lower()
            if ext.endswith(".pdf"):
                try:
                    import PyPDF2
                    with open(doc.file_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        text = "\n".join([p.extract_text() or "" for p in reader.pages])
                except Exception:
                    text = f"[Failed to read PDF: {doc.filename}]"
            else:
                try:
                    with open(doc.file_path, "r", encoding="utf-8") as f:
                        text = f.read()
                except Exception:
                    text = f"[Failed to read text: {doc.filename}]"

            chunks = chunker.chunk_text(text)

            for c_idx, chunk in enumerate(chunks):
                await self.ws.send_status("planning", f"Analyzing {doc.filename} (part {c_idx+1}/{len(chunks)})...")
                map_prompt = f"User Request: {prompt}\n\nDocument Section ({doc.filename}):\n{chunk}\n\nExtract or summarize the information from this section that helps fulfill the user request. If nothing is relevant, just say 'Not relevant'."
                summary = await self.llm.generate(map_prompt, system="You are an analyst.")
                if "not relevant" not in summary.lower():
                    all_chunk_summaries.append(f"From {doc.filename}:\n{summary}")

        await self.ws.send_status("planning", "Consolidating findings...")

        reduce_prompt = f"User Request: {prompt}\n\nHere are the extracted findings from the documents:\n\n" + "\n\n".join(all_chunk_summaries)
        reduce_prompt += "\n\nSynthesize these findings into a final, comprehensive response to the user's request."

        await self.ws.send_status("planning", "Generating response...")

        if return_result:
            final_answer = await self.llm.generate(reduce_prompt, system="You are an expert AI assistant.")
            return final_answer
        else:
            final_answer = ""
            async for chunk in self.llm.generate_stream(reduce_prompt, system="You are an expert AI assistant."):
                final_answer += chunk
                await self.ws.send_llm_token(chunk)

            await self.ws.send_llm_done(final_answer)

            # Save to chat history
            self.state.chat_history.append({"role": "assistant", "content": final_answer})
            if self.state.workspace_path:
                import pathlib
                self.state.save(pathlib.Path(self.state.workspace_path) / "project_state.json")

            await self.ws.send_status("idle", "Ready")
            return final_answer
