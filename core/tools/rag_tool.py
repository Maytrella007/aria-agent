"""
ARIA - Document RAG Tool
==========================

Ingest documents (PDF, TXT, MD, HTML) into a vector store,
then answer questions using relevant chunks as context.

Architecture:
  Document → Chunker → Embeddings → ChromaDB ("documents" collection)
  Query → Embedding → Semantic Search → Top chunks → LLM context
"""

import hashlib
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.rag")

# Chunking config
DEFAULT_CHUNK_SIZE = 800      # ~800 chars per chunk
DEFAULT_CHUNK_OVERLAP = 100   # Overlap between chunks for context continuity
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB max file size

# Supported file extensions
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".html", ".htm", ".csv", ".json", ".py", ".js", ".ts"}


class DocumentRAGTool(ToolBase):
    """Ingest documents and answer questions using RAG (Retrieval-Augmented Generation)."""

    name = "rag"
    description = (
        "Document knowledge base with RAG (Retrieval-Augmented Generation). "
        "Actions: ingest (add a document), query (search documents), "
        "list (show ingested documents), remove (delete a document). "
        "Use 'ingest' to add PDFs, text files, code, etc. "
        "Use 'query' to find relevant information from ingested documents."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: ingest, query, list, remove",
            required=True,
            enum=["ingest", "query", "list", "remove"],
        ),
        ToolParam(
            name="path",
            type="string",
            description="File path for ingest/remove (supports PDF, TXT, MD, HTML, code files)",
            required=False,
        ),
        ToolParam(
            name="query",
            type="string",
            description="Search query for the 'query' action",
            required=False,
        ),
        ToolParam(
            name="num_results",
            type="integer",
            description="Number of chunks to return (default: 5, max: 15)",
            required=False,
            default=5,
        ),
        ToolParam(
            name="chunk_size",
            type="integer",
            description="Characters per chunk for ingest (default: 800)",
            required=False,
            default=DEFAULT_CHUNK_SIZE,
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._collection = None
        self._embedding_fn = None
        self._metadata_db = None  # Track ingested documents

    def _get_collection(self):
        """Lazy-init ChromaDB collection for documents."""
        if self._collection is not None:
            return self._collection

        try:
            import chromadb
            from chromadb.utils import embedding_functions
        except ImportError:
            return None

        data_dir = self.context.get("data_dir", "data")
        chroma_path = os.path.join(data_dir, "rag_chroma")
        os.makedirs(chroma_path, exist_ok=True)

        client = chromadb.PersistentClient(path=chroma_path)
        self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-MiniLM-L12-v2"
        )
        self._collection = client.get_or_create_collection(
            name="documents",
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        return self._collection

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]

        if action == "ingest":
            return self._ingest(kwargs)
        elif action == "query":
            return self._query(kwargs)
        elif action == "list":
            return self._list_docs(kwargs)
        elif action == "remove":
            return self._remove(kwargs)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    # -------------------------------------------------------------------------
    # INGEST
    # -------------------------------------------------------------------------

    def _ingest(self, kwargs) -> ToolResult:
        path = kwargs.get("path")
        if not path:
            return ToolResult(success=False, error="'path' is required for ingest")

        path = os.path.expanduser(path)
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        # Check file size
        size = os.path.getsize(path)
        if size > MAX_FILE_SIZE:
            return ToolResult(success=False, error=f"File too large: {size / 1024 / 1024:.1f}MB (max: 50MB)")

        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            return ToolResult(success=False, error=f"Unsupported file type: {ext}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")

        collection = self._get_collection()
        if collection is None:
            return ToolResult(success=False, error="ChromaDB not available. Install: pip install chromadb sentence-transformers")

        # Extract text
        try:
            text = self._extract_text(path, ext)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to extract text: {e}")

        if not text or len(text.strip()) < 10:
            return ToolResult(success=False, error="No extractable text in file")

        # Chunk
        chunk_size = kwargs.get("chunk_size", DEFAULT_CHUNK_SIZE)
        chunks = self._chunk_text(text, chunk_size, DEFAULT_CHUNK_OVERLAP)

        # Generate document ID from path + content hash
        doc_id = hashlib.md5(f"{os.path.abspath(path)}:{size}".encode()).hexdigest()[:12]
        filename = os.path.basename(path)

        # Remove old version if re-ingesting
        try:
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

        # Add chunks to ChromaDB
        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [
            {
                "doc_id": doc_id,
                "filename": filename,
                "path": os.path.abspath(path),
                "chunk_index": chunk["index"],
                "total_chunks": len(chunks),
                "page": chunk.get("page", 0),
                "ingested_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "file_type": ext,
                "file_size": size,
            }
            for chunk in chunks
        ]

        collection.add(ids=ids, documents=documents, metadatas=metadatas)

        return ToolResult(
            success=True,
            output=f"Ingested '{filename}': {len(chunks)} chunks ({len(text)} chars) from {ext} file",
            data={
                "doc_id": doc_id,
                "filename": filename,
                "chunks": len(chunks),
                "text_length": len(text),
                "file_type": ext,
            },
        )

    # -------------------------------------------------------------------------
    # QUERY
    # -------------------------------------------------------------------------

    def _query(self, kwargs) -> ToolResult:
        query = kwargs.get("query")
        if not query:
            return ToolResult(success=False, error="'query' is required for search")

        collection = self._get_collection()
        if collection is None:
            return ToolResult(success=False, error="ChromaDB not available")

        n_results = min(kwargs.get("num_results", 5), 15)

        try:
            results = collection.query(
                query_texts=[query],
                n_results=n_results,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search failed: {e}")

        if not results or not results["documents"] or not results["documents"][0]:
            return ToolResult(
                success=True,
                output="No documents found. Use rag(action='ingest') to add documents first.",
                data={"results": [], "query": query},
            )

        # Format results
        lines = [f"Found {len(results['documents'][0])} relevant chunks for: '{query}'\n"]
        result_data = []

        for i, (doc, meta, distance) in enumerate(zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )):
            relevance = max(0, 1 - distance)  # cosine distance → relevance score
            filename = meta.get("filename", "unknown")
            page = meta.get("page", 0)
            chunk_idx = meta.get("chunk_index", 0)

            lines.append(f"--- [{i+1}] {filename} (chunk {chunk_idx}, relevance: {relevance:.0%}) ---")
            if page:
                lines.append(f"Page: {page}")
            lines.append(doc[:600])
            lines.append("")

            result_data.append({
                "filename": filename,
                "chunk_index": chunk_idx,
                "page": page,
                "relevance": round(relevance, 3),
                "text": doc[:800],
            })

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"results": result_data, "query": query, "count": len(result_data)},
        )

    # -------------------------------------------------------------------------
    # LIST
    # -------------------------------------------------------------------------

    def _list_docs(self, kwargs) -> ToolResult:
        collection = self._get_collection()
        if collection is None:
            return ToolResult(success=False, error="ChromaDB not available")

        try:
            all_data = collection.get(include=["metadatas"])
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to list: {e}")

        if not all_data or not all_data["metadatas"]:
            return ToolResult(success=True, output="No documents ingested yet.", data={"documents": []})

        # Group by doc_id
        docs = {}
        for meta in all_data["metadatas"]:
            doc_id = meta.get("doc_id", "unknown")
            if doc_id not in docs:
                docs[doc_id] = {
                    "doc_id": doc_id,
                    "filename": meta.get("filename", "unknown"),
                    "path": meta.get("path", ""),
                    "file_type": meta.get("file_type", ""),
                    "ingested_at": meta.get("ingested_at", ""),
                    "chunks": 0,
                }
            docs[doc_id]["chunks"] += 1

        lines = [f"Ingested documents ({len(docs)}):\n"]
        for d in docs.values():
            lines.append(f"  [{d['doc_id']}] {d['filename']} — {d['chunks']} chunks ({d['file_type']}) — {d['ingested_at']}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"documents": list(docs.values())},
        )

    # -------------------------------------------------------------------------
    # REMOVE
    # -------------------------------------------------------------------------

    def _remove(self, kwargs) -> ToolResult:
        path = kwargs.get("path")
        if not path:
            return ToolResult(success=False, error="'path' is required for remove")

        collection = self._get_collection()
        if collection is None:
            return ToolResult(success=False, error="ChromaDB not available")

        # Try to find by path or filename
        path = os.path.expanduser(path)
        abs_path = os.path.abspath(path)
        filename = os.path.basename(path)

        try:
            # Try by absolute path first
            results = collection.get(where={"path": abs_path})
            if not results or not results["ids"]:
                # Try by filename
                results = collection.get(where={"filename": filename})

            if not results or not results["ids"]:
                return ToolResult(success=False, error=f"Document not found: {path}")

            count = len(results["ids"])
            collection.delete(ids=results["ids"])

            return ToolResult(
                success=True,
                output=f"Removed '{filename}': {count} chunks deleted",
                data={"filename": filename, "chunks_removed": count},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to remove: {e}")

    # -------------------------------------------------------------------------
    # TEXT EXTRACTION
    # -------------------------------------------------------------------------

    def _extract_text(self, path: str, ext: str) -> str:
        """Extract text from a file based on its extension."""
        if ext == ".pdf":
            return self._extract_pdf(path)
        elif ext in (".html", ".htm"):
            return self._extract_html(path)
        else:
            # Plain text, markdown, code, CSV, JSON
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

    def _extract_pdf(self, path: str) -> str:
        """Extract text from PDF using PyPDF2."""
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            raise ImportError("PyPDF2 not installed. Run: pip install PyPDF2")

        reader = PdfReader(path)
        texts = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                texts.append(f"[Page {i + 1}]\n{text.strip()}")
        return "\n\n".join(texts)

    def _extract_html(self, path: str) -> str:
        """Extract text from HTML, stripping tags."""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        # Try BeautifulSoup
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            return soup.get_text(separator="\n", strip=True)
        except ImportError:
            pass

        # Fallback: regex strip
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    # -------------------------------------------------------------------------
    # CHUNKING
    # -------------------------------------------------------------------------

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[Dict[str, Any]]:
        """Split text into overlapping chunks, respecting paragraph boundaries.

        Returns list of {"text": str, "index": int, "page": int}
        """
        chunks = []
        current_page = 1

        # Split by paragraphs first for cleaner chunks
        paragraphs = re.split(r"\n\s*\n|\n(?=\[Page \d+\])", text)

        current_chunk = ""
        chunk_index = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # Track page markers
            page_match = re.match(r"\[Page (\d+)\]", para)
            if page_match:
                current_page = int(page_match.group(1))
                para = re.sub(r"^\[Page \d+\]\s*", "", para)

            # If adding this paragraph exceeds chunk_size, save current and start new
            if current_chunk and len(current_chunk) + len(para) + 2 > chunk_size:
                chunks.append({
                    "text": current_chunk.strip(),
                    "index": chunk_index,
                    "page": current_page,
                })
                chunk_index += 1
                # Overlap: keep the tail of the previous chunk
                if overlap > 0 and len(current_chunk) > overlap:
                    current_chunk = current_chunk[-overlap:] + "\n\n" + para
                else:
                    current_chunk = para
            else:
                current_chunk = current_chunk + "\n\n" + para if current_chunk else para

            # If single paragraph is too long, force-split it
            while len(current_chunk) > chunk_size * 1.5:
                split_at = current_chunk.rfind(". ", 0, chunk_size)
                if split_at == -1:
                    split_at = current_chunk.rfind(" ", 0, chunk_size)
                if split_at == -1:
                    split_at = chunk_size

                chunks.append({
                    "text": current_chunk[:split_at + 1].strip(),
                    "index": chunk_index,
                    "page": current_page,
                })
                chunk_index += 1
                current_chunk = current_chunk[split_at + 1:]

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append({
                "text": current_chunk.strip(),
                "index": chunk_index,
                "page": current_page,
            })

        return chunks
