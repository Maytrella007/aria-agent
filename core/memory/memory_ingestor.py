"""
Memory Ingestor - RAG search, web content ingestion, and tool memory storage.

Handles automatic ingestion of web results into the RAG knowledge base,
saving rich tool memories, and emotion detection.
"""

import logging

logger = logging.getLogger("aria")


class MemoryIngestor:
    """Manages automatic knowledge ingestion and tool memory storage."""

    def __init__(self, memory, tools, EmotionalTone):
        self.memory = memory
        self.tools = tools
        self._EmotionalTone = EmotionalTone

    def auto_rag_search(self, query: str, max_chunks: int = 3) -> str:
        """Automatically search ingested documents for relevant context.

        Runs a quick semantic search against the RAG collection.
        Only includes results above a relevance threshold to avoid noise.
        Returns formatted context string, or empty string if nothing relevant found.
        """
        RELEVANCE_THRESHOLD = 0.35  # Minimum cosine similarity to include

        rag_tool = self.tools.get("rag")
        if not rag_tool:
            return ""

        try:
            collection = rag_tool._get_collection()
            if collection is None:
                return ""

            # Quick check: any documents at all?
            count = collection.count()
            if count == 0:
                return ""

            # Search
            results = collection.query(
                query_texts=[query],
                n_results=max_chunks,
            )

            if not results or not results["documents"] or not results["documents"][0]:
                return ""

            # Filter by relevance threshold
            chunks = []
            for doc, meta, distance in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                relevance = max(0, 1 - distance)
                if relevance >= RELEVANCE_THRESHOLD:
                    filename = meta.get("filename", "unknown")
                    page = meta.get("page", 0)
                    page_info = f" (p.{page})" if page else ""
                    chunks.append(f"[{filename}{page_info}, {relevance:.0%}]: {doc[:400]}")

            if not chunks:
                return ""

            ctx = "\n\n=== RELEVANT DOCUMENTS ===\n"
            ctx += "The following excerpts from ingested documents may be relevant:\n\n"
            for i, chunk in enumerate(chunks, 1):
                ctx += f"{i}. {chunk}\n\n"

            return ctx

        except Exception as e:
            logger.debug(f"Auto-RAG search failed: {e}")
            return ""

    def auto_ingest_web_results(self, tool_results: list):
        """Auto-ingest web_fetch and web_search results into RAG.

        Every page ARIA reads gets chunked and stored in the document
        knowledge base, so future queries can recall web content without
        re-fetching.

        Args:
            tool_results: List of (ToolCall, ToolResult) tuples
        """
        rag_tool = self.tools.get("rag")
        if not rag_tool:
            return

        collection = rag_tool._get_collection()
        if collection is None:
            return

        import hashlib
        import time as _time

        for tc, result in tool_results:
            if not result.success:
                continue

            text = result.output or ""
            if len(text.strip()) < 50:
                continue

            if tc.name == "web_fetch":
                url = tc.args.get("url", "")
                doc_id = hashlib.md5(f"web:{url}".encode()).hexdigest()[:12]
                filename = url[:80]
                file_type = "web_fetch"
                # Use full fetched content
                content = text

            elif tc.name == "web_search":
                query = tc.args.get("query", "")
                doc_id = hashlib.md5(f"search:{query}".encode()).hexdigest()[:12]
                filename = f"search: {query[:60]}"
                file_type = "web_search"
                content = text

            else:
                continue

            # Remove old version if re-ingesting same URL/query
            try:
                existing = collection.get(where={"doc_id": doc_id})
                if existing and existing["ids"]:
                    collection.delete(ids=existing["ids"])
            except Exception:
                pass

            # Chunk using the RAG tool's chunker
            chunks = rag_tool._chunk_text(content, 800, 100)
            if not chunks:
                continue

            ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
            documents = [chunk["text"] for chunk in chunks]
            metadatas = [
                {
                    "doc_id": doc_id,
                    "filename": filename,
                    "path": tc.args.get("url", tc.args.get("query", "")),
                    "chunk_index": chunk["index"],
                    "total_chunks": len(chunks),
                    "page": 0,
                    "ingested_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
                    "file_type": file_type,
                    "file_size": len(content),
                    "auto_ingested": True,
                }
                for chunk in chunks
            ]

            try:
                collection.add(ids=ids, documents=documents, metadatas=metadatas)
                logger.info(f"Auto-ingested {file_type} into RAG: {filename[:50]} ({len(chunks)} chunks)")
            except Exception as e:
                logger.debug(f"Auto-ingest chunk add failed: {e}")

    def auto_ingest_cmd_output(self, cmd_name: str, args: str, output: str):
        """Auto-ingest output from intent commands (fetch/search) into RAG.

        This covers the intent-detection path that bypasses _handle_tool_calls.
        """
        rag_tool = self.tools.get("rag")
        if not rag_tool:
            return

        collection = rag_tool._get_collection()
        if collection is None:
            return

        import hashlib
        import time as _time

        if cmd_name == "fetch":
            doc_id = hashlib.md5(f"web:{args}".encode()).hexdigest()[:12]
            filename = args[:80]
            file_type = "web_fetch"
        elif cmd_name == "search":
            doc_id = hashlib.md5(f"search:{args}".encode()).hexdigest()[:12]
            filename = f"search: {args[:60]}"
            file_type = "web_search"
        else:
            return

        # Remove old version
        try:
            existing = collection.get(where={"doc_id": doc_id})
            if existing and existing["ids"]:
                collection.delete(ids=existing["ids"])
        except Exception:
            pass

        chunks = rag_tool._chunk_text(output, 800, 100)
        if not chunks:
            return

        ids = [f"{doc_id}_chunk_{i}" for i in range(len(chunks))]
        documents = [chunk["text"] for chunk in chunks]
        metadatas = [
            {
                "doc_id": doc_id,
                "filename": filename,
                "path": args,
                "chunk_index": chunk["index"],
                "total_chunks": len(chunks),
                "page": 0,
                "ingested_at": _time.strftime("%Y-%m-%d %H:%M:%S"),
                "file_type": file_type,
                "file_size": len(output),
                "auto_ingested": True,
            }
            for chunk in chunks
        ]

        collection.add(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(f"Auto-ingested {file_type} cmd into RAG: {filename[:50]} ({len(chunks)} chunks)")

    def save_tool_memories(self, tool_results: list, final_response: str):
        """Save rich, searchable memories from tool usage.

        Instead of just logging 'ARIA used calculator -> OK', we save
        WHAT was found/calculated/fetched so future conversations can
        recall the actual knowledge.

        Args:
            tool_results: List of (ToolCall, ToolResult) tuples from the agent loop
            final_response: The LLM's final text response summarizing results
        """
        from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

        for tc, result in tool_results:
            if not result.success:
                continue  # Don't memorize failed tool calls

            tool_name = tc.name
            args = tc.args
            output = str(result.output or "")[:800]

            # Build a rich, searchable memory based on tool type
            content, tags, importance = self._format_tool_memory(tool_name, args, output)

            if not content:
                continue

            self.memory.experience(
                content=content,
                emotional_tone=EmotionalTone.CURIOUS,
                involves=["system"],
                importance=importance,
                tags=list(set(["tool_result", tool_name] + tags)),
                origin=MemoryOrigin.DISCOVERED,
                context=f"Tool: {tool_name} | Args: {str(args)[:200]}",
            )

    def _format_tool_memory(self, tool_name: str, args: dict, output: str):
        """Format a tool result into a rich memory entry.

        Returns (content, tags, importance) or (None, [], 0) to skip.
        """
        tags = []
        importance = 0.5

        if tool_name == "web_search":
            query = args.get("query", "")
            content = f"Searched the web for '{query}'. Results:\n{output[:600]}"
            tags = ["web_search", "research"]
            importance = 0.6

        elif tool_name == "web_fetch":
            url = args.get("url", "")
            # Extract just the key info, not the full page
            content = f"Fetched content from {url}.\n{output[:500]}"
            tags = ["web_fetch", "reading"]
            importance = 0.5

        elif tool_name == "calculator":
            expr = args.get("expression", "")
            content = f"Calculated: {expr} = {output.strip()}"
            tags = ["calculation", "math"]
            importance = 0.4

        elif tool_name == "database":
            action = args.get("action", "")
            sql = args.get("sql", "")[:200]
            content = f"Database {action}: {sql}\nResult: {output[:400]}"
            tags = ["database", "data"]
            importance = 0.5

        elif tool_name == "project_knowledge":
            action = args.get("action", "")
            pk_content = args.get("content", "")[:300]
            content = f"Project knowledge {action}: {pk_content}"
            if output:
                content += f"\n{output[:300]}"
            tags = ["knowledge", "project"]
            importance = 0.7  # Knowledge decisions are important

        elif tool_name == "todo":
            action = args.get("action", "")
            text = args.get("text", "")
            content = f"Todo {action}: {text}\n{output[:200]}"
            tags = ["todo", "tasks"]
            importance = 0.5

        elif tool_name == "shell_exec":
            cmd = args.get("command", "")
            content = f"Ran command: {cmd}\nOutput: {output[:400]}"
            tags = ["shell", "command"]
            importance = 0.4

        elif tool_name == "http_request":
            url = args.get("url", "")
            method = args.get("method", "GET")
            content = f"HTTP {method} {url}\n{output[:400]}"
            tags = ["api", "http"]
            importance = 0.5

        elif tool_name == "system_info":
            content = f"System info check:\n{output[:400]}"
            tags = ["system", "status"]
            importance = 0.3

        elif tool_name == "compress":
            action = args.get("action", "")
            path = args.get("path", "")
            content = f"Archive {action}: {path}\n{output[:200]}"
            tags = ["files", "archive"]
            importance = 0.3

        elif tool_name == "file_manager":
            action = args.get("action", "")
            path = args.get("path", "")
            content = f"File {action}: {path}\n{output[:300]}"
            tags = ["files"]
            importance = 0.4

        elif tool_name == "git":
            action = args.get("action", "")
            content = f"Git {action}:\n{output[:400]}"
            tags = ["git", "code"]
            importance = 0.5

        elif tool_name == "translate":
            text = args.get("text", "")[:200]
            target = args.get("target_language", "")
            content = f"Translated to {target}: '{text}' -> {output[:300]}"
            tags = ["translation"]
            importance = 0.4

        else:
            # Generic fallback
            content = f"Used {tool_name}: {output[:400]}"
            importance = 0.3

        return content, tags, importance

    def detect_emotion(self, text: str):
        """Detect emotion from text (supports Spanish and English)"""
        EmotionalTone = self._EmotionalTone
        t = text.lower()

        # Joyful - Spanish and English
        if any(w in t for w in ['feliz', 'alegr', 'happy', 'glad', 'joy', '!']):
            return EmotionalTone.JOYFUL

        # Sad - Spanish and English
        if any(w in t for w in ['triste', 'sad', 'upset', 'unhappy']):
            return EmotionalTone.SAD

        # Curious - Spanish and English
        if any(w in t for w in ['curios', 'interesting', 'wonder', 'intrigued', '?']):
            return EmotionalTone.CURIOUS

        # Anxious - Spanish and English
        if any(w in t for w in ['ansi', 'nervous', 'worried', 'anxious', 'stress']):
            return EmotionalTone.ANXIOUS

        # Grateful - Spanish and English
        if any(w in t for w in ['gracias', 'agradec', 'thank', 'grateful', 'appreciate']):
            return EmotionalTone.CONNECTED

        # Frustrated - Spanish and English
        if any(w in t for w in ['frustr', 'angry', 'annoyed', 'irritated']):
            return EmotionalTone.ANGRY

        # Hopeful - Spanish and English
        if any(w in t for w in ['esper', 'hope', 'optimistic', 'looking forward']):
            return EmotionalTone.INSPIRED

        return EmotionalTone.NEUTRAL
