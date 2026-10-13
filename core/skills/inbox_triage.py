"""Inbox Triage Skill - Review unread mail and turn it into an action list."""

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class InboxTriageSkill(SkillBase):
    name = "inbox_triage"
    description = "Review unread Gmail messages, prioritize them, and optionally create follow-up todos"
    requires_tools = [Tools.GMAIL]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        result = ctx.tools.execute(Tools.GMAIL, action="search", query="is:unread", max_results=10)
        if not result.success:
            return SkillResult(success=False, error=f"Inbox triage failed: {result.error}")

        messages = result.data.get("results", [])
        triaged = [self._triage_message(msg) for msg in messages]
        created = []
        if self._should_create_todos(query) and triaged:
            created = self._create_todos(triaged, ctx)

        if ctx.llm and triaged:
            summarized = self._summarize_with_llm(triaged, created, ctx)
            if summarized:
                return SkillResult(success=True, output=summarized, data={"triaged": triaged, "created_todos": created})

        return SkillResult(success=True, output=self._format_triage(triaged, created), data={"triaged": triaged, "created_todos": created})

    def _triage_message(self, msg: dict) -> dict:
        text = f"{msg.get('subject', '')} {msg.get('snippet', '')}".lower()
        if any(w in text for w in ["urgent", "asap", "today", "deadline", "blocked"]):
            priority = "high"
        elif any(w in text for w in ["meeting", "invoice", "review", "follow up", "reminder"]):
            priority = "medium"
        else:
            priority = "low"
        action = "reply" if any(w in text for w in ["please", "reply", "respond", "confirm"]) else "review"
        return {
            "id": msg.get("id", ""),
            "subject": msg.get("subject", "(no subject)"),
            "from": msg.get("from", ""),
            "snippet": msg.get("snippet", ""),
            "priority": priority,
            "action": action,
        }

    def _should_create_todos(self, query: str) -> bool:
        q = query.lower()
        return any(w in q for w in ["todo", "task", "follow up", "seguimiento", "tarea"])

    def _create_todos(self, triaged: list, ctx: SkillContext) -> list:
        created = []
        for item in triaged[:5]:
            if item["priority"] == "low":
                continue
            result = ctx.tools.execute(Tools.TODO, action="add", text=f"{item['action'].title()}: {item['subject']}")
            if result.success:
                created.append(result.data.get("todo", {}))
        return created

    def _summarize_with_llm(self, triaged: list, created: list, ctx: SkillContext):
        lines = [f"- [{item['priority']}] {item['subject']} from {item['from']} -> {item['action']}" for item in triaged]
        if created:
            lines.append("")
            lines.append(f"Created {len(created)} follow-up todos.")
        try:
            response = ctx.llm.chat(messages=[{"role": "user", "content": "Summarize this inbox triage:\n\n" + "\n".join(lines)}], max_tokens=300)
            return response.content if response and response.content else ""
        except Exception:
            return ""

    def _format_triage(self, triaged: list, created: list) -> str:
        if not triaged:
            return "Inbox clear. No unread messages need triage."
        lines = [f"Inbox triage ({len(triaged)} unread):", ""]
        for item in triaged:
            lines.append(f"- [{item['priority']}] {item['subject']} from {item['from']} -> {item['action']}")
        if created:
            lines.append("")
            lines.append(f"Created {len(created)} todos for follow-up.")
        return "\n".join(lines)
