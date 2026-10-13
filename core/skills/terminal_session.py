"""Terminal Session Skill."""

import re

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class TerminalSessionSkill(SkillBase):
    name = "terminal_session"
    description = "Inspect tmux sessions, capture pane output, and send commands to persistent terminal sessions"
    requires_tools = [Tools.TMUX]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")
        op = self._detect_operation(query)
        if op == "list":
            result = ctx.tools.execute(Tools.TMUX, action="list_sessions")
        elif op == "capture":
            target = self._extract_target(query)
            if not target:
                return SkillResult(success=False, error="Specify a tmux target")
            result = ctx.tools.execute(Tools.TMUX, action="capture", target=target, lines=50)
        else:
            target = self._extract_target(query)
            text = self._extract_text(query)
            if not target or not text:
                return SkillResult(success=False, error="Specify a tmux target and command text")
            result = ctx.tools.execute(Tools.TMUX, action="send_keys", target=target, text=text)
        return SkillResult(success=result.success, output=result.output, error=result.error, data={"operation": op, **(result.data or {})})

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["list sessions", "show sessions", "tmux sessions"]):
            return "list"
        if any(w in q for w in ["capture", "show output", "read pane"]):
            return "capture"
        return "send"

    def _extract_target(self, query: str) -> str:
        m = re.search(r'([\w-]+:\d+(?:\.\d+)?)', query)
        return m.group(1) if m else ""

    def _extract_text(self, query: str) -> str:
        m = re.search(r'(?i)(?:send|run|type)\s+(.+?)\s+(?:to|in)\s+[\w-]+:\d+(?:\.\d+)?', query)
        return m.group(1).strip() if m else ""
