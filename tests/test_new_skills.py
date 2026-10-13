"""Tests for newly added orchestration skills."""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.base import SkillContext
from core.skills.research_monitor import ResearchMonitorSkill
from core.skills.inbox_triage import InboxTriageSkill
from core.skills.meeting_prep import MeetingPrepSkill


def make_ctx(llm_response="Mock summary"):
    llm = MagicMock()
    llm_resp = MagicMock()
    llm_resp.content = llm_response
    llm.chat.return_value = llm_resp

    tools = MagicMock()
    tool_result = MagicMock()
    tool_result.success = True
    tool_result.output = "Mock output"
    tool_result.data = {}
    tool_result.error = None
    tools.execute.return_value = tool_result

    memory = MagicMock()
    memory.recall.return_value = []

    return SkillContext(tools=tools, llm=llm, memory=memory)


class TestResearchMonitorSkill:
    def test_watch_url(self):
        s = ResearchMonitorSkill()
        ctx = make_ctx()
        result = s.execute("watch https://example.com/feed.xml", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("feed_watcher", action="add", url="https://example.com/feed.xml")

    def test_scan_updates(self):
        s = ResearchMonitorSkill()
        ctx = make_ctx("2 new updates found")
        scan_result = MagicMock(success=True, output="scan ok", data={"new_items": 2, "scanned": []}, error=None)
        ctx.tools.execute.return_value = scan_result
        result = s.execute("scan monitored sources", ctx)
        assert result.success


class TestInboxTriageSkill:
    def test_triage_with_todos(self):
        s = InboxTriageSkill()
        ctx = make_ctx("Inbox triage summary")
        gmail_result = MagicMock(success=True, output="Unread emails", data={"results": [
            {"id": "1", "subject": "Urgent review", "from": "boss@example.com", "snippet": "please review today"},
            {"id": "2", "subject": "Weekly notes", "from": "team@example.com", "snippet": "FYI"},
        ]}, error=None)
        todo_result = MagicMock(success=True, output="todo added", data={"todo": {"id": 1}}, error=None)
        ctx.tools.execute.side_effect = [gmail_result, todo_result]
        result = s.execute("triage my inbox and create follow up tasks", ctx)
        assert result.success
        assert result.data["created_todos"]


class TestMeetingPrepSkill:
    def test_prepare_meeting(self):
        s = MeetingPrepSkill()
        ctx = make_ctx("Meeting brief")
        calendar_result = MagicMock(success=True, output="events", data={"events": [
            {"summary": "ARIA sync", "start": {"dateTime": "2026-04-05T10:00:00Z"}, "attendees": [{"email": "a@example.com"}]}
        ]}, error=None)
        generic = MagicMock(success=True, output="context", data={}, error=None)
        ctx.tools.execute.side_effect = [calendar_result, generic, generic, generic]
        result = s.execute("prepare my ARIA sync", ctx)
        assert result.success
        assert "Meeting brief" in result.output
