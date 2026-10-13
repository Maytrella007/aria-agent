"""
Summarize Skill - Summarize URLs, PDFs, or text.

Detects input type (URL, file path, or raw text), fetches content,
and produces a structured summary with key points.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class SummarizeSkill(SkillBase):
    name = "summarize"
    description = "Summarize a URL, PDF, document, or text"
    requires_tools = []

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for summarization")

        # Detect input type
        content, source_type, source_name = self._fetch_content(query, ctx)

        if not content:
            return SkillResult(
                success=False,
                error="Could not retrieve content to summarize. Provide a URL, file path, or paste text.",
            )

        # Summarize with LLM
        return self._summarize(content, source_type, source_name, ctx)

    def _fetch_content(self, query: str, ctx: SkillContext):
        """Detect input type and fetch content."""
        query = query.strip()

        # Check for URL
        url_match = re.search(r'https?://\S+', query)
        if url_match and ctx.tools:
            url = url_match.group()
            result = ctx.tools.execute(Tools.WEB_FETCH, url=url, max_length=10000)
            if result.success:
                title = result.data.get("title", url)
                return result.output, "url", title

        # Check for PDF file path
        if query.endswith('.pdf') and ctx.tools:
            result = ctx.tools.execute(Tools.PDF_READ, path=query)
            if result.success:
                return result.output, "pdf", query

        # Check for any file path (starts with / or C:\ or ~)
        if ctx.tools and re.match(r'^[/~]|^[A-Z]:\\', query):
            result = ctx.tools.execute(Tools.FILE_MANAGER, action="read", path=query)
            if result.success:
                return result.output, "file", query

        # Raw text (if long enough to summarize)
        if len(query) > 100:
            return query, "text", "provided text"

        # Try as a search query
        if ctx.tools and len(query) > 5:
            result = ctx.tools.execute(Tools.WEB_SEARCH, query=query, num_results=1)
            if result.success and result.data.get("urls"):
                url = result.data["urls"][0]
                fetch = ctx.tools.execute(Tools.WEB_FETCH, url=url, max_length=10000)
                if fetch.success:
                    return fetch.output, "url", fetch.data.get("title", url)

        return None, None, None

    def _summarize(self, content, source_type, source_name, ctx) -> SkillResult:
        """Generate structured summary using LLM."""
        prompt = f"""Summarize the following {source_type} content from "{source_name}".

Content:
{content[:8000]}

Provide:
1. **Title/Topic** (1 line)
2. **Key Points** (3-5 bullet points)
3. **Summary** (2-3 sentences)
4. **Notable details** (if any)

Be concise and focus on the most important information."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={
                        "source_type": source_type,
                        "source_name": source_name,
                        "content_length": len(content),
                    },
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Summarization failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")
