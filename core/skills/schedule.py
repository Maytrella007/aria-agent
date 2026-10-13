"""
Schedule Skill - Create reminders, cron tasks, and calendar events.

Parses natural language time expressions and routes to cron or Google Calendar.
"""

import re
import hashlib

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class ScheduleSkill(SkillBase):
    name = "schedule"
    description = "Schedule reminders, recurring tasks, and calendar events"
    requires_tools = [Tools.CRON]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        # Detect if this is a calendar event or a cron/reminder
        if self._is_calendar_event(query):
            return self._create_calendar_event(query, ctx)
        else:
            return self._create_reminder(query, ctx)

    def _is_calendar_event(self, query: str) -> bool:
        """Detect if the request is for a calendar event vs a reminder."""
        q = query.lower()
        calendar_words = ["calendar", "calendario", "event", "evento", "meeting", "reunión", "appointment", "cita"]
        return any(w in q for w in calendar_words)

    def _create_reminder(self, query: str, ctx: SkillContext) -> SkillResult:
        """Create a cron-based reminder."""
        # Try to parse time expression
        schedule_expr = self._parse_time_expression(query)
        task_desc = self._extract_task_description(query)

        if not task_desc:
            task_desc = query

        if schedule_expr:
            # Use cron tool
            job_name = self._build_job_name(task_desc or query)
            cron_tool = ctx.tools.get(Tools.CRON) if hasattr(ctx.tools, "get") else None
            if not cron_tool:
                return SkillResult(success=False, error="Cron tool not available")
            cron_schedule = self._to_cron_tool_schedule(schedule_expr)
            if not cron_schedule:
                return SkillResult(success=False, error=f"Unsupported reminder schedule: {schedule_expr}")
            result = cron_tool.execute(
                action="add",
                name=job_name,
                schedule=cron_schedule,
                task=f"REMINDER: {task_desc}",
            )
            if result.success:
                return SkillResult(
                    success=True,
                    output=f"Reminder set: {task_desc}\nSchedule: {cron_schedule}\n{result.output}",
                    data={"type": "cron", "schedule": cron_schedule, "task": task_desc, "name": job_name},
                )
            return SkillResult(success=False, error=f"Failed to create reminder: {result.error}")

        # If no parseable time, use LLM to help
        if ctx.llm:
            return self._llm_parse_schedule(query, ctx)

        return SkillResult(
            success=False,
            error="Could not parse time. Examples: 'remind me in 30 minutes', 'every day at 9:00'",
        )

    def _create_calendar_event(self, query: str, ctx: SkillContext) -> SkillResult:
        """Create a Google Calendar event."""
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for calendar event creation")

        prompt = f"""Parse this event request and extract details:

Request: {query}

Extract:
- title: Event title
- date: Date (YYYY-MM-DD format)
- start_time: Start time (HH:MM format, 24h)
- end_time: End time (HH:MM format, 24h) - default 1 hour after start
- description: Brief description

Respond in this exact format (one per line):
TITLE: <title>
DATE: <date>
START: <time>
END: <time>
DESCRIPTION: <description>"""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
            )
            if not response or not response.content:
                return SkillResult(success=False, error="LLM returned empty response")

            # Parse LLM response
            text = response.content
            title = self._extract_field(text, "TITLE") or "Event"
            date = self._extract_field(text, "DATE") or ""
            start = self._extract_field(text, "START") or ""
            end = self._extract_field(text, "END") or ""
            desc = self._extract_field(text, "DESCRIPTION") or ""

            if date and start:
                start_dt = f"{date}T{start}:00"
                end_dt = f"{date}T{end}:00" if end else f"{date}T{start.split(':')[0]}:00:00"

                result = ctx.tools.execute(
                    Tools.GOOGLE_CALENDAR,
                    action="create",
                    title=title,
                    start=start_dt,
                    end=end_dt,
                    description=desc,
                )
                if result.success:
                    return SkillResult(
                        success=True,
                        output=f"Calendar event created:\n  {title}\n  {date} {start}-{end}\n{result.output}",
                        data={"type": "calendar", "title": title, "date": date},
                    )
                return SkillResult(success=False, error=f"Calendar creation failed: {result.error}")

            return SkillResult(
                success=True,
                output=f"Event parsed but missing date/time:\n{text}\n\nPlease specify a date and time.",
                data={"type": "calendar", "parsed": True, "incomplete": True},
            )

        except Exception as e:
            return SkillResult(success=False, error=f"Calendar event creation failed: {e}")

    def _parse_time_expression(self, query: str) -> str:
        """Parse natural language into cron-like schedule."""
        q = query.lower()

        # "every X minutes/hours"
        m = re.search(r'every\s+(\d+)\s*min', q)
        if m:
            return f"*/{m.group(1)} * * * *"

        m = re.search(r'every\s+(\d+)\s*hour', q)
        if m:
            return f"0 */{m.group(1)} * * *"

        m = re.search(r'cada\s+(\d+)\s*min', q)
        if m:
            return f"*/{m.group(1)} * * * *"

        m = re.search(r'cada\s+(\d+)\s*hora', q)
        if m:
            return f"0 */{m.group(1)} * * *"

        # "at HH:MM" or "a las HH:MM"
        m = re.search(r'(?:at|a\s+las?)\s+(\d{1,2}):(\d{2})', q)
        if m:
            hour, minute = m.group(1), m.group(2)
            if "every day" in q or "cada día" in q or "daily" in q or "diario" in q:
                return f"{minute} {hour} * * *"
            return f"{minute} {hour} * * *"

        # "in X minutes"
        m = re.search(r'in\s+(\d+)\s*min', q)
        if m:
            return f"+{m.group(1)}m"

        m = re.search(r'en\s+(\d+)\s*min', q)
        if m:
            return f"+{m.group(1)}m"

        return ""

    def _extract_task_description(self, query: str) -> str:
        """Extract the task description from the reminder query."""
        # Remove time expressions
        cleaned = re.sub(
            r'(?:remind\s+me|recuérdame|set\s+(?:a\s+)?reminder|schedule)\s*(?:to|que|para)?\s*',
            '', query, flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r'(?:every|cada|in|en|at|a\s+las?)\s+\d+\s*(?:min\w*|hour\w*|hora\w*|day\w*|día\w*|week\w*|semana\w*|:\d{2})',
            '', cleaned, flags=re.IGNORECASE,
        )
        return cleaned.strip()

    def _extract_field(self, text: str, field: str) -> str:
        """Extract a field value from structured text."""
        m = re.search(rf'{field}:\s*(.+)', text, re.IGNORECASE)
        return m.group(1).strip() if m else ""

    def _llm_parse_schedule(self, query: str, ctx: SkillContext) -> SkillResult:
        """Use LLM to parse complex time expressions."""
        prompt = f"""Parse this scheduling request into a cron expression:

Request: {query}

Respond with ONLY:
CRON: <cron expression or +Xm for one-time>
TASK: <what to remind about>"""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            if response and response.content:
                cron = self._extract_field(response.content, "CRON")
                task = self._extract_field(response.content, "TASK") or query

                if cron:
                    cron_tool = ctx.tools.get(Tools.CRON) if hasattr(ctx.tools, "get") else None
                    if not cron_tool:
                        return SkillResult(success=False, error="Cron tool not available")
                    cron_schedule = self._to_cron_tool_schedule(cron)
                    if not cron_schedule:
                        return SkillResult(success=False, error=f"Unsupported reminder schedule: {cron}")
                    result = cron_tool.execute(
                        action="add",
                        name=self._build_job_name(task),
                        schedule=cron_schedule,
                        task=f"REMINDER: {task}",
                    )
                    if result.success:
                        return SkillResult(
                            success=True,
                            output=f"Reminder set: {task}\nSchedule: {cron_schedule}\n{result.output}",
                            data={"type": "cron", "schedule": cron_schedule, "task": task, "name": self._build_job_name(task)},
                        )
        except Exception:
            pass

        return SkillResult(
            success=False,
            error="Could not parse schedule. Try: 'remind me in 30 min to call John'",
        )

    def _build_job_name(self, task: str) -> str:
        cleaned = re.sub(r'[^a-z0-9]+', '-', task.lower()).strip('-')
        if not cleaned:
            cleaned = "reminder"
        digest = hashlib.md5(task.encode("utf-8")).hexdigest()[:6]
        return f"{cleaned[:24]}-{digest}"

    def _to_cron_tool_schedule(self, schedule_expr: str) -> str:
        expr = schedule_expr.strip()

        m = re.fullmatch(r'\*/(\d+) \* \* \* \*', expr)
        if m:
            return f"every {m.group(1)} minutes"

        m = re.fullmatch(r'0 \*/(\d+) \* \* \*', expr)
        if m:
            return f"every {m.group(1)} hours"

        m = re.fullmatch(r'(\d{1,2}) (\d{1,2}) \* \* \*', expr)
        if m:
            minute, hour = m.group(1), m.group(2)
            return f"every day at {int(hour):02d}:{int(minute):02d}"

        m = re.fullmatch(r'\+(\d+)m', expr)
        if m:
            return f"every {m.group(1)} minutes"

        return expr if any(word in expr.lower() for word in ["every", "minute", "hour", "day", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]) else ""
