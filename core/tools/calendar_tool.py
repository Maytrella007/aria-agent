"""
ARIA - Google Calendar Tool
=============================

Access Google Calendar via Google API using OAuth tokens.
Actions: list, create, update, delete, calendars.

Uses raw HTTP (no SDK) with Authorization: Bearer tokens
managed by ARIA's AuthManager.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.calendar")

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarTool(ToolBase):
    """Manage Google Calendar events: list, create, update, delete."""

    name = "google_calendar"
    description = (
        "Access Google Calendar: list upcoming events, create new events, "
        "update existing events, delete events, and list available calendars. "
        "Requires Google OAuth login. Use 'auth login google' to authenticate first."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="The Calendar action to perform",
            required=True,
            enum=["list", "create", "update", "delete", "calendars"],
        ),
        ToolParam(
            name="calendar_id",
            type="string",
            description="Calendar ID (default: 'primary'). Used with all actions.",
            default="primary",
        ),
        ToolParam(
            name="event_id",
            type="string",
            description="Event ID. Required for 'update' and 'delete' actions.",
        ),
        ToolParam(
            name="summary",
            type="string",
            description="Event title. Used with 'create' and 'update'.",
        ),
        ToolParam(
            name="description",
            type="string",
            description="Event description. Used with 'create' and 'update'.",
        ),
        ToolParam(
            name="start",
            type="string",
            description="Start datetime (ISO 8601, e.g. '2026-04-05T10:00:00'). Used with 'create' and 'update'.",
        ),
        ToolParam(
            name="end",
            type="string",
            description="End datetime (ISO 8601). If omitted, defaults to start + 1 hour.",
        ),
        ToolParam(
            name="location",
            type="string",
            description="Event location. Used with 'create' and 'update'.",
        ),
        ToolParam(
            name="attendees",
            type="string",
            description="Comma-separated email addresses of attendees.",
        ),
        ToolParam(
            name="days_ahead",
            type="integer",
            description="Number of days ahead to list events (default: 7). Used with 'list'.",
            default=7,
        ),
        ToolParam(
            name="max_results",
            type="integer",
            description="Max events to return (default: 20). Used with 'list'.",
            default=20,
        ),
    ]

    def _get_token(self) -> Optional[str]:
        auth = self.context.get("auth_manager")
        if not auth:
            return None
        return auth.get_credential("google")

    def _api_get(self, url: str, token: str, params: dict = None) -> Dict[str, Any]:
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 401:
            auth = self.context.get("auth_manager")
            if auth:
                from ..auth_manager import ErrorType
                auth.report_failure("google", ErrorType.AUTH)
            return {"error": "Token expired. Run 'auth login google'."}
        if resp.status_code == 403:
            return {"error": f"Permission denied. Ensure Calendar API is enabled. ({resp.text[:200]})"}
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, url: str, token: str, data: dict) -> Dict[str, Any]:
        import requests
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(url, headers=headers, json=data, timeout=30)
        if resp.status_code == 401:
            return {"error": "Token expired. Run 'auth login google'."}
        if resp.status_code == 403:
            return {"error": "Permission denied. Check calendar access."}
        resp.raise_for_status()
        return resp.json()

    def _api_patch(self, url: str, token: str, data: dict) -> Dict[str, Any]:
        import requests
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.patch(url, headers=headers, json=data, timeout=30)
        if resp.status_code == 401:
            return {"error": "Token expired. Run 'auth login google'."}
        resp.raise_for_status()
        return resp.json()

    def _api_delete(self, url: str, token: str) -> Optional[Dict[str, Any]]:
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.delete(url, headers=headers, timeout=30)
        if resp.status_code == 401:
            return {"error": "Token expired. Run 'auth login google'."}
        if resp.status_code == 204:
            return None  # Success, no content
        resp.raise_for_status()
        return resp.json() if resp.text else None

    def _execute(self, **kwargs) -> ToolResult:
        token = self._get_token()
        if not token:
            return ToolResult(
                success=False,
                error="Google not authenticated. Run 'auth login google' first."
            )

        action = kwargs["action"]
        dispatch = {
            "list": self._list,
            "create": self._create,
            "update": self._update,
            "delete": self._delete,
            "calendars": self._calendars,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        try:
            return handler(kwargs, token)
        except Exception as e:
            logger.error(f"Calendar {action} failed: {e}")
            return ToolResult(success=False, error=str(e))

    # =========================================================================
    # Actions
    # =========================================================================

    def _list(self, kwargs: dict, token: str) -> ToolResult:
        """List upcoming events."""
        calendar_id = kwargs.get("calendar_id", "primary")
        days_ahead = kwargs.get("days_ahead", 7)
        max_results = min(kwargs.get("max_results", 20), 100)

        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()

        data = self._api_get(
            f"{CALENDAR_API}/calendars/{calendar_id}/events",
            token,
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "maxResults": max_results,
                "singleEvents": "true",
                "orderBy": "startTime",
            },
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        events = data.get("items", [])
        if not events:
            return ToolResult(
                success=True,
                output=f"No events in the next {days_ahead} days.",
                data={"events": []},
            )

        lines = [f"Upcoming events (next {days_ahead} days):", ""]
        for i, ev in enumerate(events, 1):
            start = ev.get("start", {})
            start_str = start.get("dateTime", start.get("date", ""))
            end = ev.get("end", {})
            end_str = end.get("dateTime", end.get("date", ""))

            lines.append(f"{i}. {ev.get('summary', '(no title)')}")
            lines.append(f"   When: {self._format_datetime(start_str)} → {self._format_datetime(end_str)}")
            if ev.get("location"):
                lines.append(f"   Where: {ev['location']}")
            if ev.get("description"):
                desc = ev["description"][:100]
                lines.append(f"   Note: {desc}")
            attendees = ev.get("attendees", [])
            if attendees:
                names = [a.get("email", "") for a in attendees[:5]]
                lines.append(f"   With: {', '.join(names)}")
            lines.append(f"   ID: {ev.get('id', '')}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"events": events, "count": len(events)},
        )

    def _create(self, kwargs: dict, token: str) -> ToolResult:
        """Create a new event."""
        summary = kwargs.get("summary")
        start = kwargs.get("start")
        if not summary:
            return ToolResult(success=False, error="'summary' required for 'create' action")
        if not start:
            return ToolResult(success=False, error="'start' required for 'create' action")

        calendar_id = kwargs.get("calendar_id", "primary")

        # Build event body
        event = {
            "summary": summary,
            "start": {"dateTime": self._ensure_tz(start), "timeZone": "UTC"},
        }

        end = kwargs.get("end")
        if end:
            event["end"] = {"dateTime": self._ensure_tz(end), "timeZone": "UTC"}
        else:
            # Default: 1 hour after start
            try:
                start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                end_dt = start_dt + timedelta(hours=1)
                event["end"] = {"dateTime": end_dt.isoformat(), "timeZone": "UTC"}
            except ValueError:
                event["end"] = event["start"]

        if kwargs.get("description"):
            event["description"] = kwargs["description"]
        if kwargs.get("location"):
            event["location"] = kwargs["location"]
        if kwargs.get("attendees"):
            emails = [e.strip() for e in kwargs["attendees"].split(",")]
            event["attendees"] = [{"email": e} for e in emails if e]

        data = self._api_post(
            f"{CALENDAR_API}/calendars/{calendar_id}/events",
            token,
            event,
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        return ToolResult(
            success=True,
            output=f"Event created: {summary}\n  When: {start}\n  ID: {data.get('id', '')}\n  Link: {data.get('htmlLink', '')}",
            data=data,
        )

    def _update(self, kwargs: dict, token: str) -> ToolResult:
        """Update an existing event."""
        event_id = kwargs.get("event_id")
        if not event_id:
            return ToolResult(success=False, error="'event_id' required for 'update' action")

        calendar_id = kwargs.get("calendar_id", "primary")

        # Build patch body with only provided fields
        patch = {}
        if kwargs.get("summary"):
            patch["summary"] = kwargs["summary"]
        if kwargs.get("description"):
            patch["description"] = kwargs["description"]
        if kwargs.get("location"):
            patch["location"] = kwargs["location"]
        if kwargs.get("start"):
            patch["start"] = {"dateTime": self._ensure_tz(kwargs["start"]), "timeZone": "UTC"}
        if kwargs.get("end"):
            patch["end"] = {"dateTime": self._ensure_tz(kwargs["end"]), "timeZone": "UTC"}
        if kwargs.get("attendees"):
            emails = [e.strip() for e in kwargs["attendees"].split(",")]
            patch["attendees"] = [{"email": e} for e in emails if e]

        if not patch:
            return ToolResult(success=False, error="Nothing to update. Provide at least one field.")

        data = self._api_patch(
            f"{CALENDAR_API}/calendars/{calendar_id}/events/{event_id}",
            token,
            patch,
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        return ToolResult(
            success=True,
            output=f"Event updated: {data.get('summary', event_id)}",
            data=data,
        )

    def _delete(self, kwargs: dict, token: str) -> ToolResult:
        """Delete an event."""
        event_id = kwargs.get("event_id")
        if not event_id:
            return ToolResult(success=False, error="'event_id' required for 'delete' action")

        calendar_id = kwargs.get("calendar_id", "primary")

        result = self._api_delete(
            f"{CALENDAR_API}/calendars/{calendar_id}/events/{event_id}",
            token,
        )
        if result and "error" in result:
            return ToolResult(success=False, error=result["error"])

        return ToolResult(
            success=True,
            output=f"Event deleted: {event_id}",
            data={"deleted": event_id},
        )

    def _calendars(self, kwargs: dict, token: str) -> ToolResult:
        """List available calendars."""
        data = self._api_get(f"{CALENDAR_API}/users/me/calendarList", token)
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        calendars = data.get("items", [])
        lines = ["Available calendars:", ""]
        for cal in calendars:
            primary = " [PRIMARY]" if cal.get("primary") else ""
            lines.append(f"  - {cal.get('summary', '')}{primary}")
            lines.append(f"    ID: {cal.get('id', '')}")
            if cal.get("description"):
                lines.append(f"    {cal['description'][:80]}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"calendars": calendars},
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _ensure_tz(self, dt_str: str) -> str:
        """Ensure datetime string has timezone info."""
        if "+" in dt_str or "Z" in dt_str or dt_str.endswith(("z",)):
            return dt_str
        return dt_str + "Z"  # Assume UTC if no timezone

    def _format_datetime(self, dt_str: str) -> str:
        """Format ISO datetime to human-readable."""
        if not dt_str:
            return ""
        try:
            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return dt_str
