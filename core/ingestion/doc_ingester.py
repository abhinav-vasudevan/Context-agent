import logging
import asyncio
from pathlib import Path
from typing import List, Optional, Callable

from core.llm_client import LLMClient
from core.brain.semantic_store import SemanticStore
from core.ingestion.chunker import RecursiveCharacterChunker
from models.state import ProjectState, UserDocument

log = logging.getLogger(__name__)

class UserDocumentIngester:
    """
    Ingests large user-provided documents (PDF, MD, TXT).
    Implements Map-Reduce summarization for large contexts and
    stores the raw chunks in ChromaDB for Retrieval-Augmented Generation.
    """

    def __init__(self, llm_client: LLMClient, semantic_store: SemanticStore, state: ProjectState):
        self.llm = llm_client
        self.semantic = semantic_store
        self.state = state
        self.chunker = RecursiveCharacterChunker(chunk_size=8000, overlap=400)

    def _read_file(self, file_path: Path) -> str:
        ext = file_path.suffix.lower()
        if ext == ".pdf":
            try:
                import PyPDF2
                text = []
                with open(file_path, "rb") as f:
                    reader = PyPDF2.PdfReader(f)
                    for page in reader.pages:
                        text.append(page.extract_text() or "")
                return "\n".join(text)
            except ImportError:
                raise ImportError("PyPDF2 is required to read PDF files. Add it to requirements.txt")
        else:
            return file_path.read_text(encoding="utf-8", errors="ignore")

    async def ingest_document(
        self,
        file_path_str: str,
        doc_id: str,
        on_status: Optional[Callable[[str], None]] = None
    ) -> UserDocument:
        """
        Parses, chunks, and summarizes a large document.
        """
        file_path = Path(file_path_str)
        if not file_path.exists():
            raise FileNotFoundError(f"Document not found: {file_path}")
        import inspect
        if on_status:
            if inspect.iscoroutinefunction(on_status):
                await on_status(f"Reading document: {file_path.name}...")
            else:
                on_status(f"Reading document: {file_path.name}...")


        text = self._read_file(file_path)
        chunks = self.chunker.chunk_text(text)
        if on_status:
            if inspect.iscoroutinefunction(on_status):
                await on_status(f"Document split into {len(chunks)} chunks. Storing...")
            else:
                on_status(f"Document split into {len(chunks)} chunks. Storing...")


        for i, chunk in enumerate(chunks):
            # Store in ChromaDB for granular retrieval later
            self.semantic.store_document_chunk(
                doc_id=doc_id,
                chunk_index=i,
                chunk_content=chunk,
                source_file=file_path.name
            )

        doc = UserDocument(
            id=doc_id,
            file_path=str(file_path),
            filename=file_path.name,
            master_summary="",
            chunk_count=len(chunks)
        )

        self.state.user_documents.append(doc)
        if self.state.workspace_path:
            self.state.save(Path(self.state.workspace_path) / "project_state.json")
        if on_status:
            if inspect.iscoroutinefunction(on_status):
                await on_status(f"Successfully ingested {file_path.name}.")
            else:
                on_status(f"Successfully ingested {file_path.name}.")


        return doc

    async def consolidate_all_documents(self) -> str:
        """
        Merges all existing document master summaries into one global specification.
        """
        if not self.state.user_documents:
            return "No documents to consolidate."

        master_prompt = "You have been provided with several requirement documents for a project. Combine them into a single, comprehensive Master Specification. Resolve any contradictions and ensure the end goal is clearly defined.\n\n"
        for doc in self.state.user_documents:
            master_prompt += f"--- Document: {doc.filename} ---\n{doc.master_summary}\n\n"

        global_summary = await self.llm.generate(master_prompt, system="You are a lead software architect writing a master specification.")

        self.state.global_master_summary = global_summary
        if self.state.workspace_path:
            self.state.save(Path(self.state.workspace_path) / "project_state.json")

        return global_summary
