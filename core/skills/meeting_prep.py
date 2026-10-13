"""Meeting Prep Skill - Build a brief from calendar, mail, drive, and memory."""

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class MeetingPrepSkill(SkillBase):
    name = "meeting_prep"
    description = "Prepare for upcoming meetings by gathering calendar context, related emails, docs, and prior knowledge"
    requires_tools = [Tools.GOOGLE_CALENDAR]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        calendar = ctx.tools.execute(Tools.GOOGLE_CALENDAR, action="list", days_ahead=7, max_results=10)
        if not calendar.success:
            return SkillResult(success=False, error=f"Calendar lookup failed: {calendar.error}")

        event = self._pick_event(calendar.data.get("events", []), query)
        if not event:
            return SkillResult(success=False, error="No matching upcoming meeting found")

        topic = event.get("summary", "meeting")
        gmail = ctx.tools.execute(Tools.GMAIL, action="search", query=topic, max_results=5)
        drive = ctx.tools.execute(Tools.GOOGLE_DRIVE, action="search", query=topic, max_results=5)
        knowledge = ctx.tools.execute(Tools.PROJECT_KNOWLEDGE, action="recall", query=topic, limit=5)
        memories = self._recall_memories(topic, ctx)

        if ctx.llm:
            brief = self._build_llm_brief(event, gmail, drive, knowledge, memories, ctx)
            if brief:
                return SkillResult(success=True, output=brief, data={"event": event, "topic": topic})

        return SkillResult(success=True, output=self._fallback_brief(event, gmail, drive, knowledge, memories), data={"event": event, "topic": topic})

    def _pick_event(self, events: list, query: str):
        if not events:
            return None
        q = query.lower().strip()
        if not q:
            return events[0]
        for event in events:
            summary = (event.get("summary") or "").lower()
            if summary and any(token in summary for token in q.split() if len(token) > 2):
                return event
        return events[0]

    def _recall_memories(self, topic: str, ctx: SkillContext):
        if not ctx.memory:
            return []
        try:
            return ctx.memory.recall(topic, limit=3)
        except Exception:
            return []

    def _build_llm_brief(self, event, gmail, drive, knowledge, memories, ctx):
        prompt = f"""Prepare a concise meeting brief.

Meeting:
{event}

Related email results:
{gmail.output if gmail.success else gmail.error}

Related drive results:
{drive.output if drive.success else drive.error}

Project knowledge:
{knowledge.output if knowledge.success else knowledge.error}

Prior memories:
{[getattr(m, 'content', str(m))[:200] for m in memories]}

Return:
1. Purpose
2. Key context
3. Open questions
4. Suggested agenda
"""
        try:
            response = ctx.llm.chat(messages=[{"role": "user", "content": prompt}], max_tokens=500)
            return response.content if response and response.content else ""
        except Exception:
            return ""

    def _fallback_brief(self, event, gmail, drive, knowledge, memories):
        lines = [f"Meeting prep: {event.get('summary', '(no title)')}", ""]
        lines.append(f"When: {event.get('start', {}).get('dateTime', event.get('start', {}).get('date', ''))}")
        attendees = event.get("attendees", [])
        if attendees:
            lines.append("Attendees: " + ", ".join(a.get("email", "") for a in attendees[:5]))
        lines.append("")
        lines.append("Related email results:")
        lines.append((gmail.output if gmail.success else "No email context")[:500])
        lines.append("")
        lines.append("Related drive results:")
        lines.append((drive.output if drive.success else "No drive context")[:500])
        lines.append("")
        lines.append("Project knowledge:")
        lines.append((knowledge.output if knowledge.success else "No project knowledge")[:500])
        if memories:
            lines.append("")
            lines.append("Prior memories:")
            for memory in memories:
                lines.append(f"- {getattr(memory, 'content', str(memory))[:180]}")
        return "\n".join(lines)
