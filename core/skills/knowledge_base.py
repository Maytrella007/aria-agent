"""
Knowledge Base Skill - Save and recall project knowledge.

Combines project_knowledge and RAG tools to maintain
a searchable knowledge base of decisions, patterns, and facts.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.memory.memory_v2 import EmotionalTone
from core.tools.tool_names import Tools


class KnowledgeBaseSkill(SkillBase):
    name = "knowledge_base"
    description = "Save and recall project knowledge, decisions, and facts"
    requires_tools = [Tools.RAG]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        op = self._detect_operation(query)

        if op == "save":
            return self._save_knowledge(query, ctx)
        else:
            return self._recall_knowledge(query, ctx)

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        save_words = [
            "remember that", "recuerda que", "save", "guardar",
            "note that", "anotar", "learn that",
        ]
        if any(w in q for w in save_words):
            return "save"
        return "recall"

    def _save_knowledge(self, query: str, ctx: SkillContext) -> SkillResult:
        """Save a piece of knowledge."""
        # Extract what to save
        content = self._extract_content(query)
        if not content or len(content) < 5:
            return SkillResult(
                success=False,
                error="Please specify what to save. Example: remember that the API uses v2 endpoints",
            )

        # Classify the knowledge type
        knowledge_type = self._classify(content)

        # Save to project_knowledge
        result = ctx.tools.execute(
            "project_knowledge",
            action="save",
            content=content,
            category=knowledge_type,
        )

        # Also save to RAG if available
        rag = ctx.tools.get(Tools.RAG) if hasattr(ctx.tools, 'get') else None
        if rag:
            try:
                import tempfile, os, hashlib
                safe = hashlib.md5(content.encode()).hexdigest()[:10]
                path = os.path.join(tempfile.gettempdir(), f"aria_kb_{safe}.txt")
                with open(path, "w", encoding="utf-8") as f:
                    f.write(f"Knowledge ({knowledge_type}): {content}")
                ctx.tools.execute(Tools.RAG, action="ingest", path=path)
                try:
                    os.remove(path)
                except Exception:
                    pass
            except Exception:
                pass

        # Save to memory
        if ctx.memory:
            try:
                ctx.memory.experience(
                    content=f"Knowledge saved ({knowledge_type}): {content}",
                    emotional_tone=EmotionalTone.NEUTRAL,
                    involves=[ctx.user] if ctx.user else [],
                    importance=0.7,
                    context="knowledge_base",
                )
            except Exception:
                pass

        if result.success:
            return SkillResult(
                success=True,
                output=f"Saved ({knowledge_type}): {content}\n{result.output}",
                data={"action": "save", "type": knowledge_type, "content": content},
            )

        return SkillResult(success=False, error=f"Failed to save: {result.error}")

    def _recall_knowledge(self, query: str, ctx: SkillContext) -> SkillResult:
        """Recall knowledge about a topic."""
        topic = self._extract_topic(query)
        if not topic:
            topic = query

        results = []

        # Search project_knowledge
        pk_result = ctx.tools.execute(
            "project_knowledge",
            action="recall",
            query=topic,
        )
        if pk_result.success and pk_result.output:
            results.append(("Project Knowledge", pk_result.output))

        # Search RAG
        try:
            rag_result = ctx.tools.execute(Tools.RAG, action="query", query=topic)
            if rag_result.success and rag_result.output:
                results.append(("Documents", rag_result.output))
        except Exception:
            pass

        # Search memory
        if ctx.memory:
            try:
                memories = ctx.memory.recall(topic, limit=5)
                if memories:
                    mem_text = "\n".join(
                        f"- {(m.content if hasattr(m, 'content') else str(m))[:150]}"
                        for m in memories
                    )
                    results.append(("Memory", mem_text))
            except Exception:
                pass

        if not results:
            return SkillResult(
                success=True,
                output=f"No knowledge found about: {topic}",
                data={"action": "recall", "topic": topic, "found": False},
            )

        # Combine results
        if ctx.llm and len(results) > 1:
            return self._synthesize(topic, results, ctx)

        output = "\n\n".join(f"## {source}\n{content}" for source, content in results)
        return SkillResult(
            success=True,
            output=output,
            data={"action": "recall", "topic": topic, "sources": len(results)},
        )

    def _synthesize(self, topic, results, ctx) -> SkillResult:
        """Use LLM to synthesize knowledge from multiple sources."""
        raw = "\n\n".join(f"Source: {src}\n{content}" for src, content in results)

        prompt = f"""Synthesize what we know about "{topic}" from these sources:

{raw[:4000]}

Provide a clear, organized summary of the relevant knowledge.
Highlight key decisions, facts, and patterns."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"action": "recall", "topic": topic, "sources": len(results), "synthesized": True},
                )
        except Exception:
            pass

        output = "\n\n".join(f"## {src}\n{content}" for src, content in results)
        return SkillResult(
            success=True,
            output=output,
            data={"action": "recall", "topic": topic, "sources": len(results)},
        )

    def _extract_content(self, query: str) -> str:
        """Extract the knowledge content to save."""
        cleaned = re.sub(
            r'\b(remember|recuerda|save|guardar|note|anotar|learn|that|que|this|esta|the)\b',
            '', query, flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r'\b(decision|fact|note|knowledge|decisión|nota|dato)\b',
            '', cleaned, flags=re.IGNORECASE,
        )
        return cleaned.strip().strip(':').strip()

    def _extract_topic(self, query: str) -> str:
        """Extract the topic to recall."""
        m = re.search(r'(?:about|on|sobre|de|regarding)\s+(.+)', query, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        cleaned = re.sub(
            r'\b(what|do|you|know|remember|recall|qué|sabes|recuerdas|knowledge|about|on)\b',
            '', query, flags=re.IGNORECASE,
        )
        return cleaned.strip()

    def _classify(self, content: str) -> str:
        """Classify the type of knowledge."""
        c = content.lower()
        if any(w in c for w in ["decided", "decision", "chose", "eligió", "decidió"]):
            return "decision"
        if any(w in c for w in ["pattern", "convention", "patrón", "convención", "always", "never"]):
            return "pattern"
        if any(w in c for w in ["prefer", "like", "want", "prefiere", "gusta", "quiere"]):
            return "convention"
        if any(w in c for w in ["api", "architecture", "endpoint", "service", "module", "system"]):
            return "architecture"
        return "context"
