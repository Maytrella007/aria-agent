"""Research Monitor Skill - Watch sources and summarize new updates."""

import re

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class ResearchMonitorSkill(SkillBase):
    name = "research_monitor"
    description = "Monitor feeds or pages for updates, scan watched sources, and summarize new items"
    requires_tools = [Tools.FEED_WATCHER]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        op = self._detect_operation(query)
        if op == "watch":
            url = self._extract_url(query)
            if not url:
                return SkillResult(success=False, error="Provide a URL to monitor")
            result = ctx.tools.execute(Tools.FEED_WATCHER, action="add", url=url)
            if result.success:
                return SkillResult(success=True, output=result.output, data={"operation": "watch", "url": url})
            return SkillResult(success=False, error=result.error)

        if op == "scan":
            url = self._extract_url(query)
            result = ctx.tools.execute(Tools.FEED_WATCHER, action="scan", url=url or None)
            if not result.success:
                return SkillResult(success=False, error=result.error)
            return self._summarize_scan(result, ctx)

        result = ctx.tools.execute(Tools.FEED_WATCHER, action="items", unread_only=True, limit=10)
        if result.success:
            return SkillResult(success=True, output=result.output, data={"operation": "items", **(result.data or {})})
        return SkillResult(success=False, error=result.error)

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["scan", "check updates", "update", "updates", "refresh", "revisar"]):
            return "scan"
        if any(w in q for w in ["watch", "monitor", "follow", "vigila", "vigilar"]):
            return "watch"
        return "items"

    def _extract_url(self, query: str) -> str:
        match = re.search(r'https?://\S+', query)
        return match.group(0).rstrip('.,)') if match else ""

    def _summarize_scan(self, result, ctx: SkillContext) -> SkillResult:
        new_items = result.data.get("new_items", 0)
        if not ctx.llm or new_items == 0:
            return SkillResult(success=True, output=result.output, data={"operation": "scan", **(result.data or {})})

        collected = []
        for watcher in result.data.get("scanned", []):
            for item in watcher.get("items", [])[:5]:
                collected.append(f"- {item['title']}: {item.get('summary', '')[:120]}")
        prompt = "Summarize these new monitored-source updates for quick review:\n\n" + "\n".join(collected)
        try:
            response = ctx.llm.chat(messages=[{"role": "user", "content": prompt}], max_tokens=300)
            if response and response.content:
                return SkillResult(success=True, output=response.content, data={"operation": "scan", **(result.data or {})})
        except Exception:
            pass
        return SkillResult(success=True, output=result.output, data={"operation": "scan", **(result.data or {})})
