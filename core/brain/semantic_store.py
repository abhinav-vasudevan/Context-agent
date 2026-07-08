"""
Semantic Store — ChromaDB-backed vector memory for project understanding.

Stores semantic summaries, ADRs, and architecture specs as embeddings.
Enables similarity-based retrieval: "find files with similar functionality"
without requiring exact keyword matches.

This is the second pillar of the Project Brain (alongside the Knowledge Graph).
While the Knowledge Graph stores *relationships*, the Semantic Store stores *meaning*.
"""

from __future__ import annotations
import logging
from typing import List, Dict, Optional, Any
from pathlib import Path

log = logging.getLogger(__name__)

# ── ChromaDB availability check ──────────────────────────────────────
try:
    import chromadb
    from chromadb.config import Settings
    HAS_CHROMADB = True
except ImportError:
    HAS_CHROMADB = False
    log.warning("chromadb not installed. Run: pip install chromadb")


class SemanticStore:
    """
    ChromaDB-backed semantic memory for the Project Brain.

    Collections:
      - file_summaries: Semantic summaries of each generated file
      - architecture_specs: Subsystem and service descriptions
      - adrs: Architectural Decision Records
      - change_history: Record of changes and their rationale

    Each document is stored with:
      - document: The natural-language text (for embedding)
      - metadata: Structured fields for filtering
      - id: Unique identifier
    """

    # Collection names
    FILES_COLLECTION = "file_summaries"
    ARCH_COLLECTION = "architecture_specs"
    ADR_COLLECTION = "adrs"
    CHANGES_COLLECTION = "change_history"
    DOCUMENTS_COLLECTION = "user_documents"

    def __init__(self, persist_dir: str):
        """
        Initialize the semantic store.

        Args:
            persist_dir: Directory where ChromaDB will persist its data.
                         Typically: <workspace>/.agent_brain/chroma/
        """
        self.persist_dir = persist_dir
        self._client = None

        if not HAS_CHROMADB:
            log.warning("ChromaDB not available. Semantic memory disabled.")
            return

        try:
            Path(persist_dir).mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=persist_dir,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
            log.info("ChromaDB initialized at %s", persist_dir)
        except Exception as e:
            log.error("Failed to initialize ChromaDB: %s", e)
            self._client = None

    @property
    def is_available(self) -> bool:
        """Check if ChromaDB is operational."""
        return self._client is not None

    def _get_or_create_collection(self, name: str):
        """Get or create a ChromaDB collection."""
        if not self._client:
            return None
        return self._client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    # ── File Summaries ────────────────────────────────────────────────

    def store_file_summary(
        self,
        file_path: str,
        purpose: str,
        responsibilities: List[str],
        exports: List[str],
        dependencies: List[str],
        constraints: List[str],
        risks: List[str],
        subsystem: str = "",
        service: str = "",
    ):
        """
        Store or update a semantic summary for a code file.

        This is called by the Summarization Agent after every file is written.
        The embedding is created from a natural-language representation
        so that similarity searches work semantically.
        """
        collection = self._get_or_create_collection(self.FILES_COLLECTION)
        if not collection:
            return

        # Build the embedding document
        doc_parts = [f"File: {file_path}"]
        if purpose:
            doc_parts.append(f"Purpose: {purpose}")
        if responsibilities:
            doc_parts.append(f"Responsibilities: {', '.join(responsibilities)}")
        if exports:
            doc_parts.append(f"Exports: {', '.join(exports)}")
        if constraints:
            doc_parts.append(f"Constraints: {', '.join(constraints)}")
        document = "\n".join(doc_parts)

        metadata = {
            "file_path": file_path,
            "purpose": purpose[:500] if purpose else "",
            "subsystem": subsystem,
            "service": service,
            "num_exports": len(exports),
            "num_dependencies": len(dependencies),
        }

        # Use file_path as the unique ID (upsert behavior)
        doc_id = file_path.replace("/", "_").replace("\\", "_").replace(".", "_")

        collection.upsert(
            ids=[doc_id],
            documents=[document],
            metadatas=[metadata],
        )
        log.debug("Stored semantic summary for %s", file_path)

    def query_similar_files(
        self,
        query_text: str,
        n_results: int = 5,
        subsystem_filter: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find files with similar functionality using semantic similarity.

        Args:
            query_text: Natural-language description of what you're looking for
            n_results: Number of results to return
            subsystem_filter: Optional subsystem to restrict search to

        Returns:
            List of dicts with file_path, purpose, distance, etc.
        """
        collection = self._get_or_create_collection(self.FILES_COLLECTION)
        if not collection:
            return []

        where_filter = None
        if subsystem_filter:
            where_filter = {"subsystem": subsystem_filter}

        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter,
            )
        except Exception as e:
            log.warning("Semantic query failed: %s", e)
            return []

        files = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                entry = {
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "distance": results["distances"][0][i] if results["distances"] else 1.0,
                }
                if results["metadatas"] and results["metadatas"][0]:
                    entry.update(results["metadatas"][0][i])
                files.append(entry)

        return files

    def get_file_summary(self, file_path: str) -> str:
        """Get the semantic summary for a specific file path."""
        collection = self._get_or_create_collection(self.FILES_COLLECTION)
        if not collection:
            return ""
        
        try:
            results = collection.get(
                where={"file_path": file_path},
                limit=1
            )
            if results and results["documents"] and len(results["documents"]) > 0:
                return results["documents"][0]
        except Exception as e:
            log.warning("Failed to get file summary: %s", e)
        return ""

    # ── Architecture Specs ────────────────────────────────────────────

    def store_architecture_spec(
        self,
        entity_id: str,
        entity_type: str,
        name: str,
        description: str,
        purpose: str = "",
        responsibilities: Optional[List[str]] = None,
    ):
        """Store a subsystem or service description for retrieval."""
        collection = self._get_or_create_collection(self.ARCH_COLLECTION)
        if not collection:
            return

        doc_parts = [f"{entity_type}: {name}"]
        if purpose:
            doc_parts.append(f"Purpose: {purpose}")
        if description:
            doc_parts.append(f"Description: {description}")
        if responsibilities:
            doc_parts.append(f"Responsibilities: {', '.join(responsibilities)}")
        document = "\n".join(doc_parts)

        metadata = {
            "entity_type": entity_type,
            "name": name,
            "purpose": purpose[:500] if purpose else "",
        }

        collection.upsert(
            ids=[entity_id],
            documents=[document],
            metadatas=[metadata],
        )

    def query_architecture(
        self,
        query_text: str,
        entity_type: Optional[str] = None,
        n_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """Find relevant architecture specs for a given task description."""
        collection = self._get_or_create_collection(self.ARCH_COLLECTION)
        if not collection:
            return []

        where_filter = None
        if entity_type:
            where_filter = {"entity_type": entity_type}

        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter,
            )
        except Exception as e:
            log.warning("Architecture query failed: %s", e)
            return []

        specs = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                entry = {
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "distance": results["distances"][0][i] if results["distances"] else 1.0,
                }
                if results["metadatas"] and results["metadatas"][0]:
                    entry.update(results["metadatas"][0][i])
                specs.append(entry)

        return specs

    # ── ADRs ──────────────────────────────────────────────────────────

    def store_adr(self, adr_id: str, title: str, context: str, decision: str, consequences: str):
        """Store an Architectural Decision Record."""
        collection = self._get_or_create_collection(self.ADR_COLLECTION)
        if not collection:
            return

        document = f"ADR: {title}\nContext: {context}\nDecision: {decision}\nConsequences: {consequences}"
        metadata = {"title": title, "decision": decision[:500] if decision else ""}

        collection.upsert(
            ids=[adr_id],
            documents=[document],
            metadatas=[metadata],
        )

    def query_adrs(self, query_text: str, n_results: int = 3) -> List[Dict[str, Any]]:
        """Find ADRs relevant to a given task or design question."""
        collection = self._get_or_create_collection(self.ADR_COLLECTION)
        if not collection:
            return []

        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
            )
        except Exception as e:
            log.warning("ADR query failed: %s", e)
            return []

        adrs = []
        if results and results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                entry = {
                    "id": doc_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "distance": results["distances"][0][i] if results["distances"] else 1.0,
                }
                if results["metadatas"] and results["metadatas"][0]:
                    entry.update(results["metadatas"][0][i])
                adrs.append(entry)

        return adrs

    # ── User Documents ────────────────────────────────────────────────

    def store_document_chunk(self, doc_id: str, chunk_index: int, chunk_content: str, source_file: str):
        """Store a chunk of a large user document."""
        collection = self._get_or_create_collection(self.DOCUMENTS_COLLECTION)
        if not collection:
            return

        chunk_id = f"{doc_id}_chunk_{chunk_index}"
        metadata = {
            "doc_id": doc_id,
            "chunk_index": chunk_index,
            "source_file": source_file,
        }

        collection.upsert(
            ids=[chunk_id],
            documents=[chunk_content],
            metadatas=[metadata],
        )

    def query_document_chunks(self, query_text: str, n_results: int = 3, doc_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Find relevant chunks from user documents."""
        collection = self._get_or_create_collection(self.DOCUMENTS_COLLECTION)
        if not collection:
            return []

        where_filter = None
        if doc_ids:
            if len(doc_ids) == 1:
                where_filter = {"doc_id": doc_ids[0]}
            else:
                where_filter = {"doc_id": {"$in": doc_ids}}

        try:
            results = collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=where_filter,
            )
        except Exception as e:
            log.warning("Document query failed: %s", e)
            return []

        chunks = []
        if results and results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                entry = {
                    "id": chunk_id,
                    "document": results["documents"][0][i] if results["documents"] else "",
                    "distance": results["distances"][0][i] if results["distances"] else 1.0,
                }
                if results["metadatas"] and results["metadatas"][0]:
                    entry.update(results["metadatas"][0][i])
                chunks.append(entry)

        return chunks

    # ── Utilities ─────────────────────────────────────────────────────

    def get_collection_count(self, collection_name: str) -> int:
        """Get the number of documents in a collection."""
        collection = self._get_or_create_collection(collection_name)
        if not collection:
            return 0
        return collection.count()

    def reset(self):
        """Reset all collections. DANGEROUS — only for testing."""
        if self._client:
            self._client.reset()
            log.warning("ChromaDB reset — all data deleted!")
