"""Tests for SlackAssistantSkill, WorkspaceKnowledgeSkill, and TerminalSessionSkill."""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.base import SkillContext
from core.skills.slack_assistant import SlackAssistantSkill
from core.skills.workspace_knowledge import WorkspaceKnowledgeSkill
from core.skills.terminal_session import TerminalSessionSkill


def make_ctx(llm_response="Mock summary", output="Mock output"):
    llm = MagicMock()
    llm_resp = MagicMock()
    llm_resp.content = llm_response
    llm.chat.return_value = llm_resp

    tools = MagicMock()
    result = MagicMock()
    result.success = True
    result.output = output
    result.data = {}
    result.error = None
    tools.execute.return_value = result
    return SkillContext(tools=tools, llm=llm)


class TestSlackAssistantSkill:
    def test_send_message(self):
        s = SlackAssistantSkill()
        ctx = make_ctx()
        result = s.execute("send deployment done to C12345", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("slack", action="send_message", channel="C12345", text="deployment done to C12345")

    def test_summarize_channel(self):
        s = SlackAssistantSkill()
        ctx = make_ctx("Channel summary")
        result = s.execute("summarize C12345", ctx)
        assert result.success


class TestWorkspaceKnowledgeSkill:
    def test_save_note(self):
        s = WorkspaceKnowledgeSkill()
        ctx = make_ctx()
        result = s.execute("save architecture notes to design.md", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("obsidian", action="write", path="design.md", content="architecture notes to design.md")

    def test_search_notes(self):
        s = WorkspaceKnowledgeSkill()
        ctx = make_ctx()
        result = s.execute("search obsidian for onboarding", ctx)
        assert result.success


class TestTerminalSessionSkill:
    def test_list_sessions(self):
        s = TerminalSessionSkill()
        ctx = make_ctx()
        result = s.execute("list tmux sessions", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("tmux", action="list_sessions")

    def test_capture_target(self):
        s = TerminalSessionSkill()
        ctx = make_ctx()
        result = s.execute("capture api:0.1", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("tmux", action="capture", target="api:0.1", lines=50)
