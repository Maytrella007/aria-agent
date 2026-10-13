"""Slack Assistant Skill."""

import re

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class SlackAssistantSkill(SkillBase):
    name = "slack_assistant"
    description = "Read Slack channels, summarize discussions, and send lightweight responses"
    requires_tools = [Tools.SLACK]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")
        op = self._detect_operation(query)
        channel = self._extract_channel(query)
        if not channel:
            return SkillResult(success=False, error="Specify a Slack channel ID like C12345")
        if op == "send":
            text = self._extract_message(query)
            if not text:
                return SkillResult(success=False, error="Provide the message to send")
            result = ctx.tools.execute(Tools.SLACK, action="send_message", channel=channel, text=text)
            return SkillResult(success=result.success, output=result.output, error=result.error, data={"operation": op, **(result.data or {})})
        result = ctx.tools.execute(Tools.SLACK, action="read_messages", channel=channel, limit=10)
        if not result.success:
            return SkillResult(success=False, error=result.error)
        output = result.output
        if ctx.llm and op == "summarize":
            try:
                response = ctx.llm.chat(messages=[{"role": "user", "content": f"Summarize these Slack messages:\n\n{output[:3000]}"}], max_tokens=300)
                if response and response.content:
                    output = response.content
            except Exception:
                pass
        return SkillResult(success=True, output=output, data={"operation": op, **(result.data or {})})

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["send", "post", "reply", "respond"]):
            return "send"
        return "summarize"

    def _extract_channel(self, query: str) -> str:
        m = re.search(r'\b(C[A-Z0-9]{4,})\b', query)
        return m.group(1) if m else ""

    def _extract_message(self, query: str) -> str:
        m = re.search(r'(?i)(?:send|post|reply|respond)(?:\s+in\s+\S+)?\s+(.+)$', query)
        return m.group(1).strip() if m else ""
