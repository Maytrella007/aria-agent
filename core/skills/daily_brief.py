"""
Daily Brief Skill - Personalized daily summary.

Aggregates weather, calendar, news, and pending tasks into a morning brief.
Uses memory to know user's location and interests.
"""

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class DailyBriefSkill(SkillBase):
    name = "daily_brief"
    description = "Generate a personalized daily briefing"
    requires_tools = [Tools.WEB_SEARCH]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for daily brief")

        sections = []

        # 1. Weather (if tools available)
        weather = self._get_weather(ctx)
        if weather:
            sections.append(("Weather", weather))

        # 2. News headlines
        news = self._get_news(query, ctx)
        if news:
            sections.append(("Top News", news))

        # 3. Memory-based reminders
        reminders = self._get_reminders(ctx)
        if reminders:
            sections.append(("Reminders", reminders))

        # If we have nothing, do a general brief via LLM
        if not sections:
            return self._general_brief(ctx)

        # Compose with LLM
        return self._compose_brief(sections, ctx)

    def _get_weather(self, ctx: SkillContext) -> str:
        """Fetch weather for user's location."""
        if not ctx.tools:
            return ""

        location = self._recall_location(ctx)
        if not location:
            location = "New York"  # fallback

        try:
            result = ctx.tools.execute(
                Tools.WEB_SEARCH,
                query=f"weather {location} today",
                num_results=2,
            )
            if result.success:
                return result.output[:500]
        except Exception:
            pass
        return ""

    def _recall_location(self, ctx: SkillContext) -> str:
        """Try to recall user's location from memory."""
        if not ctx.memory:
            return ""
        try:
            results = ctx.memory.recall("user location city", limit=3)
            for mem in results:
                content = mem.content if hasattr(mem, 'content') else str(mem)
                import re
                match = re.search(
                    r'(?:live[sd]?\s+in|from|based\s+in|located\s+in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',
                    content,
                )
                if match:
                    return match.group(1)
        except Exception:
            pass
        return ""

    def _get_news(self, query: str, ctx: SkillContext) -> str:
        """Fetch top news headlines."""
        if not ctx.tools:
            return ""

        # Use user interests if available from memory
        interests = self._recall_interests(ctx)
        search_query = f"top news today {interests}" if interests else "top news today"

        try:
            result = ctx.tools.execute(
                Tools.WEB_SEARCH,
                query=search_query,
                num_results=3,
            )
            if result.success:
                return result.output[:800]
        except Exception:
            pass
        return ""

    def _recall_interests(self, ctx: SkillContext) -> str:
        """Try to recall user's interests from memory."""
        if not ctx.memory:
            return ""
        try:
            results = ctx.memory.recall("user interests topics", limit=2)
            for mem in results:
                content = mem.content if hasattr(mem, 'content') else str(mem)
                if len(content) > 10:
                    return content[:100]
        except Exception:
            pass
        return ""

    def _get_reminders(self, ctx: SkillContext) -> str:
        """Check memory for pending tasks or reminders."""
        if not ctx.memory:
            return ""
        try:
            results = ctx.memory.recall("reminder task pending todo", limit=5)
            items = []
            for mem in results:
                content = mem.content if hasattr(mem, 'content') else str(mem)
                if len(content) > 5:
                    items.append(content[:150])
            if items:
                return "\n".join(f"- {item}" for item in items[:5])
        except Exception:
            pass
        return ""

    def _compose_brief(self, sections, ctx: SkillContext) -> SkillResult:
        """Use LLM to compose a polished daily briefing."""
        raw = ""
        for title, content in sections:
            raw += f"\n## {title}\n{content}\n"

        prompt = f"""Create a concise, friendly daily briefing from this data:

{raw[:4000]}

Format as a morning brief:
- Start with a greeting
- Weather summary (1-2 lines)
- Top 3-5 news headlines with brief context
- Any reminders or tasks
- End with a motivational note

Keep it concise and scannable. Use bullet points."""

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
                        "sections": [s[0] for s in sections],
                        "section_count": len(sections),
                    },
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Brief composition failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")

    def _general_brief(self, ctx: SkillContext) -> SkillResult:
        """Generate a general brief when no data sources are available."""
        prompt = """Generate a brief, friendly daily briefing.
Include: a greeting, today's date context, and a motivational thought.
Keep it to 3-4 sentences. Be warm but concise."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"sections": [], "fallback": True},
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Brief generation failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")
