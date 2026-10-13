"""
Tests for ARIA Skill System - Tier 3
======================================

Tests for: KnowledgeBase, GmailAssistant, QuickTask, CodingAgent skills.
Skill selection is 100% LLM-based (no regex triggers).
"""

import pytest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.base import SkillResult, SkillContext, SkillRegistry
from core.skills.knowledge_base import KnowledgeBaseSkill
from core.skills.gmail_assistant import GmailAssistantSkill
from core.skills.quick_task import QuickTaskSkill
from core.skills.github_ops import GitHubOpsSkill
from core.skills.research_monitor import ResearchMonitorSkill
from core.skills.inbox_triage import InboxTriageSkill
from core.skills.meeting_prep import MeetingPrepSkill
from core.skills.slack_assistant import SlackAssistantSkill
from core.skills.workspace_knowledge import WorkspaceKnowledgeSkill
from core.skills.terminal_session import TerminalSessionSkill
from core.skills.coding_agent import CodingAgentSkill


# =============================================================================
# HELPERS
# =============================================================================

def make_ctx(llm_response="Mock response", tools_response="Mock output"):
    llm = MagicMock()
    llm_resp = MagicMock()
    llm_resp.content = llm_response
    llm.chat.return_value = llm_resp

    tools = MagicMock()
    tool_result = MagicMock()
    tool_result.success = True
    tool_result.output = tools_response
    tool_result.data = {"path": "/tmp/result", "status_code": 200, "size": "1.2 MB"}
    tool_result.error = None
    tools.execute.return_value = tool_result
    tools.get.return_value = None

    memory = MagicMock()
    memory.recall.return_value = []

    return SkillContext(
        tools=tools, llm=llm, memory=memory,
        user="testuser", conversation_history=[],
    )


# =============================================================================
# KnowledgeBaseSkill
# =============================================================================

class TestKnowledgeBaseSkill:
    def test_detect_operation(self):
        s = KnowledgeBaseSkill()
        assert s._detect_operation("remember that X") == "save"
        assert s._detect_operation("note that Y") == "save"
        assert s._detect_operation("what do you know about Z") == "recall"

    def test_classify(self):
        s = KnowledgeBaseSkill()
        assert s._classify("we decided to use React") == "decision"
        assert s._classify("always use snake_case") == "pattern"
        assert s._classify("I prefer dark mode") == "convention"
        assert s._classify("the server runs on port 8080") == "context"

    def test_execute_save(self):
        s = KnowledgeBaseSkill()
        ctx = make_ctx()
        result = s.execute("remember that the API uses v2 endpoints", ctx)
        assert result.success
        assert result.data["action"] == "save"

    def test_execute_recall(self):
        s = KnowledgeBaseSkill()
        ctx = make_ctx(tools_response="API uses v2 endpoints")
        result = s.execute("what do you know about the API", ctx)
        assert result.success

    def test_without_tools(self):
        s = KnowledgeBaseSkill()
        ctx = SkillContext()
        result = s.execute("remember X", ctx)
        assert not result.success


# =============================================================================
# GmailAssistantSkill
# =============================================================================

class TestGmailAssistantSkill:
    def test_detect_operation(self):
        s = GmailAssistantSkill()
        assert s._detect_operation("search for emails from John") == "search"
        assert s._detect_operation("read the email") == "read"
        assert s._detect_operation("reply to the email") == "reply"
        assert s._detect_operation("check my inbox") == "inbox"

    def test_extract_search_query(self):
        s = GmailAssistantSkill()
        assert "from:John" in s._extract_search_query("emails from John")
        assert s._extract_search_query("unread emails") == "is:unread"

    def test_execute_inbox(self):
        s = GmailAssistantSkill()
        ctx = make_ctx(
            llm_response="You have 3 unread emails...",
            tools_response="Email 1: Subject...\nEmail 2: Subject...",
        )
        result = s.execute("check my email", ctx)
        assert result.success

    def test_without_tools(self):
        s = GmailAssistantSkill()
        ctx = SkillContext()
        result = s.execute("check email", ctx)
        assert not result.success


# =============================================================================
# QuickTaskSkill
# =============================================================================

class TestQuickTaskSkill:
    def test_detect_port_check(self):
        s = QuickTaskSkill()
        task = s._detect_task("check port 3000")
        assert task is not None
        assert "3000" in task[0]

    def test_detect_ping(self):
        s = QuickTaskSkill()
        task = s._detect_task("ping 8.8.8.8")
        assert task is not None
        assert "ping" in task[0]
        assert "8.8.8.8" in task[0]

    def test_detect_install(self):
        s = QuickTaskSkill()
        task = s._detect_task("install flask")
        assert task is not None
        assert "flask" in task[0]

    def test_dangerous_blocked(self):
        s = QuickTaskSkill()
        assert s._is_dangerous("rm -rf /")
        assert s._is_dangerous("mkfs.ext4 /dev/sda")
        assert not s._is_dangerous("ls -la")
        assert not s._is_dangerous("ping google.com")

    def test_execute(self):
        s = QuickTaskSkill()
        ctx = make_ctx(tools_response="LISTEN  8080  node")
        result = s.execute("check port 8080", ctx)
        assert result.success
        assert "8080" in result.output

    def test_without_tools(self):
        s = QuickTaskSkill()
        ctx = SkillContext()
        result = s.execute("ping google.com", ctx)
        assert not result.success


# =============================================================================
# CodingAgentSkill
# =============================================================================

class TestCodingAgentSkill:
    def test_parse_task_basic(self):
        s = CodingAgentSkill()
        task, opts = s._parse_task("build a dark mode toggle")
        assert "dark mode" in task
        assert not opts.get("agent")

    def test_parse_task_with_agent(self):
        s = CodingAgentSkill()
        task, opts = s._parse_task("using claude code build a REST API")
        assert opts["agent"] == "claude_code"
        assert "REST API" in task

    def test_parse_task_with_codex(self):
        s = CodingAgentSkill()
        task, opts = s._parse_task("with codex fix the login bug")
        assert opts["agent"] == "codex"

    def test_parse_task_with_aider(self):
        s = CodingAgentSkill()
        task, opts = s._parse_task("use aider to refactor the database module")
        assert opts["agent"] == "aider"

    def test_parse_task_with_cwd(self):
        s = CodingAgentSkill()
        task, opts = s._parse_task("build a server in ~/projects/myapp")
        assert opts.get("cwd")
        assert "projects/myapp" in opts["cwd"]

    def test_empty_task_error(self):
        s = CodingAgentSkill()
        ctx = make_ctx()
        result = s.execute("", ctx)
        assert not result.success

    def test_without_tools(self):
        s = CodingAgentSkill()
        ctx = SkillContext()
        result = s.execute("build a function", ctx)
        assert not result.success

    def test_external_agent_success(self):
        """Test running an external agent via shell_exec."""
        s = CodingAgentSkill()
        ctx = make_ctx(
            llm_response="Created file app.py with Flask server.",
            tools_response="File created: app.py\ndef create_app():\n    ..."
        )
        # Mock agent detection and auth check
        s._detect_agent = lambda ctx: "claude_code"
        s._check_auth = lambda agent_name: (True, "")
        result = s.execute("build a Flask API", ctx)
        assert result.success
        assert result.data["agent"] == "claude_code"

    def test_external_agent_timeout(self):
        """Test handling of agent timeout."""
        s = CodingAgentSkill()
        ctx = make_ctx()
        # Make shell_exec return timeout error
        tool_result = MagicMock()
        tool_result.success = False
        tool_result.error = "Command timed out after 300s"
        tool_result.output = ""
        ctx.tools.execute.return_value = tool_result
        s._detect_agent = lambda ctx: "claude_code"
        s._check_auth = lambda agent_name: (True, "")
        result = s.execute("build an entire OS", ctx)
        assert not result.success
        assert "timed out" in result.error.lower()

    def test_internal_fallback_with_orchestrator(self):
        """When no external agent is found, falls back to orchestrator."""
        s = CodingAgentSkill()
        ctx = make_ctx(tools_response="def hello(): return 'world'")
        # No external agent available
        s._detect_agent = lambda ctx: ""
        # Mock orchestrate tool availability
        orchestrate_mock = MagicMock()
        ctx.tools.get.return_value = orchestrate_mock
        result = s.execute("write a hello function", ctx)
        assert result.success

    def test_llm_fallback_no_agents(self):
        """When no agents and no orchestrator, falls back to LLM code gen."""
        s = CodingAgentSkill()
        ctx = make_ctx(llm_response="```python\ndef hello():\n    return 'world'\n```")
        s._detect_agent = lambda ctx: ""
        ctx.tools.get.return_value = None  # No orchestrate tool
        result = s.execute("write a hello function", ctx)
        assert result.success
        assert "llm_direct" in result.data.get("agent", "")

    def test_parse_task_with_opencode(self):
        s = CodingAgentSkill()
        task, opts = s._parse_task("using opencode add unit tests")
        assert opts["agent"] == "opencode"
        assert "unit tests" in task

    def test_agent_descriptions(self):
        s = CodingAgentSkill()
        assert "Claude Code" in s.AGENTS["claude_code"]["description"]
        assert "Codex" in s.AGENTS["codex"]["description"]
        assert "OpenCode" in s.AGENTS["opencode"]["description"]
        assert "Aider" in s.AGENTS["aider"]["description"]

    def test_opencode_in_priority(self):
        s = CodingAgentSkill()
        assert "opencode" in s.AGENT_PRIORITY

    def test_check_auth_with_env_var(self):
        """Auth passes when env var is set."""
        s = CodingAgentSkill()
        import os
        old = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "test-key-123"
        try:
            ok, msg = s._check_auth("claude_code")
            assert ok
        finally:
            if old is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = old

    def test_check_auth_missing(self):
        """Auth fails with helpful message when no credentials."""
        s = CodingAgentSkill()
        import os
        # Temporarily remove env vars
        saved = {}
        for key in s.AGENTS["codex"]["env_keys"]:
            saved[key] = os.environ.pop(key, None)
        # Also ensure auth path doesn't exist
        s.AGENTS["codex"]["auth_paths"] = ["/nonexistent/path/auth.json"]
        try:
            ok, msg = s._check_auth("codex")
            assert not ok
            assert "not authenticated" in msg.lower()
            assert "CODEX_API_KEY" in msg
        finally:
            for key, val in saved.items():
                if val is not None:
                    os.environ[key] = val

    def test_check_auth_unknown_agent(self):
        s = CodingAgentSkill()
        ok, msg = s._check_auth("nonexistent_agent")
        assert not ok

    def test_setup_instructions(self):
        s = CodingAgentSkill()
        instructions = s._setup_instructions()
        assert "Claude Code" in instructions
        assert "Codex" in instructions
        assert "OpenCode" in instructions
        assert "Aider" in instructions
        assert "Install" in instructions

    def test_auth_failure_blocks_execution(self):
        """If agent installed but not authenticated, returns auth error."""
        s = CodingAgentSkill()
        ctx = make_ctx()
        s._detect_agent = lambda ctx: "codex"
        s._check_auth = lambda name: (False, "Not authenticated")
        result = s.execute("build a server", ctx)
        assert not result.success
        assert result.data.get("needs_auth")

    def test_skill_metadata(self):
        s = CodingAgentSkill()
        assert s.name == "coding_agent"
        assert len(s.description) > 20


# =============================================================================
# Integration: exported skills
# =============================================================================

class TestTier3Integration:
    def test_all_exported_skills_register(self):
        from core.skills import (
            WeatherSkill, ResearchSkill, SummarizeSkill,
            DailyBriefSkill, FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill, CodingAgentSkill,
            DataAnalysisSkill, DocCreateSkill,
            KnowledgeBaseSkill, GmailAssistantSkill, QuickTaskSkill,
            ResearchMonitorSkill, InboxTriageSkill, MeetingPrepSkill,
            SlackAssistantSkill, WorkspaceKnowledgeSkill, TerminalSessionSkill,
        )
        reg = SkillRegistry()
        all_cls = [
            WeatherSkill, ResearchSkill, SummarizeSkill,
            DailyBriefSkill, FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill, CodingAgentSkill,
            DataAnalysisSkill, DocCreateSkill,
            KnowledgeBaseSkill, GmailAssistantSkill, QuickTaskSkill,
            ResearchMonitorSkill, InboxTriageSkill, MeetingPrepSkill,
            SlackAssistantSkill, WorkspaceKnowledgeSkill, TerminalSessionSkill,
        ]
        for cls in all_cls:
            reg.register(cls())
        assert len(reg) == 20

    def test_all_skills_have_descriptions(self):
        """Every skill must have a meaningful description for LLM selection."""
        from core.skills import (
            KnowledgeBaseSkill, GmailAssistantSkill, QuickTaskSkill, CodingAgentSkill,
            ResearchMonitorSkill, InboxTriageSkill, MeetingPrepSkill,
            SlackAssistantSkill, WorkspaceKnowledgeSkill, TerminalSessionSkill,
        )
        for cls in [KnowledgeBaseSkill, GmailAssistantSkill, QuickTaskSkill, CodingAgentSkill,
                    ResearchMonitorSkill, InboxTriageSkill, MeetingPrepSkill,
                    SlackAssistantSkill, WorkspaceKnowledgeSkill, TerminalSessionSkill]:
            s = cls()
            assert len(s.description) > 10, f"{s.name} needs a better description"
