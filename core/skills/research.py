"""
Research Skill - Deep multi-source research on a topic.

Performs multiple searches, reads top sources, synthesizes findings.
Checks memory for prior research. Saves findings to RAG.
"""

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class ResearchSkill(SkillBase):
    name = "research"
    description = "Deep research on a topic using multiple sources"
    requires_tools = [Tools.WEB_SEARCH]

    MAX_SOURCES = 3
    MAX_CONTENT_PER_SOURCE = 5000

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for research synthesis")

        # Check memory for prior research
        prior = self._check_prior_research(query, ctx)

        # Phase 1: Search
        search_result = ctx.tools.execute(
            Tools.WEB_SEARCH, query=query, num_results=5
        )
        if not search_result.success:
            return SkillResult(success=False, error=f"Search failed: {search_result.error}")

        # Phase 2: Fetch top sources
        sources = []
        urls = search_result.data.get("urls", [])
        if not urls and search_result.data.get("results"):
            urls = [r.get("url", "") for r in search_result.data["results"] if r.get("url")]

        for url in urls[:self.MAX_SOURCES]:
            if not url:
                continue
            fetch = ctx.tools.execute(
                Tools.WEB_FETCH, url=url, max_length=self.MAX_CONTENT_PER_SOURCE
            )
            if fetch.success and fetch.output:
                sources.append({
                    "url": url,
                    "title": fetch.data.get("title", url),
                    "content": fetch.output[:self.MAX_CONTENT_PER_SOURCE],
                })

        # Phase 3: Synthesize with LLM
        return self._synthesize(query, search_result.output, sources, prior, ctx)

    def _check_prior_research(self, query: str, ctx: SkillContext) -> str:
        """Check if ARIA has researched this topic before."""
        if not ctx.memory:
            return ""
        try:
            results = ctx.memory.recall(query, limit=3)
            if results:
                prior_items = []
                for mem in results:
                    content = mem.content if hasattr(mem, 'content') else str(mem)
                    if len(content) > 50:
                        prior_items.append(content[:300])
                if prior_items:
                    return "Prior knowledge:\n" + "\n".join(f"- {p}" for p in prior_items)
        except Exception:
            pass
        return ""

    def _synthesize(self, query, search_summary, sources, prior, ctx) -> SkillResult:
        """Use LLM to synthesize all gathered information."""
        source_text = ""
        for i, src in enumerate(sources, 1):
            source_text += f"\n--- Source {i}: {src['title']} ({src['url']}) ---\n"
            source_text += src['content'][:2000] + "\n"

        prompt = f"""Research synthesis task. Topic: {query}

{prior}

Search results summary:
{search_summary[:2000]}

{source_text[:6000] if source_text else "(No detailed sources available)"}

Create a comprehensive research summary:
1. Key findings (3-5 bullet points)
2. Important details and nuances
3. Sources referenced
4. Any contradictions or gaps in the data

Be thorough but concise. Cite sources when possible."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
            )
            if response and response.content:
                # Try to save to RAG for future reference
                self._save_to_rag(query, response.content, ctx)

                return SkillResult(
                    success=True,
                    output=response.content,
                    data={
                        "topic": query,
                        "sources_count": len(sources),
                        "had_prior_knowledge": bool(prior),
                    },
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Synthesis failed: {e}")

        return SkillResult(
            success=True,
            output=f"Research on '{query}':\n{search_summary}",
            data={"topic": query, "sources_count": len(sources)},
        )

    def _save_to_rag(self, topic: str, summary: str, ctx: SkillContext):
        """Save research findings to RAG for future reference."""
        try:
            rag = ctx.tools.get(Tools.RAG) if ctx.tools else None
            if not rag:
                return

            import tempfile
            import hashlib
            import os

            safe = hashlib.md5(topic.encode()).hexdigest()[:10]
            path = os.path.join(tempfile.gettempdir(), f"aria_research_{safe}.txt")

            with open(path, "w", encoding="utf-8") as f:
                f.write(f"Research: {topic}\n\n{summary}")

            rag.execute(action="ingest", path=path)

            try:
                os.remove(path)
            except Exception:
                pass
        except Exception:
            pass
