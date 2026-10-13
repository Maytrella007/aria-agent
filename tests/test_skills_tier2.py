"""
Tests for ARIA Skill System - Tier 2
======================================

Tests for: FileOps, Schedule, GitOps,
DataAnalysis, DocCreate skills.
Skill selection is 100% LLM-based (no regex triggers).
"""

import pytest
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.base import SkillResult, SkillContext, SkillRegistry
from core.skills.file_ops import FileOpsSkill
from core.skills.schedule import ScheduleSkill
from core.skills.git_ops import GitOpsSkill
from core.skills.github_ops import GitHubOpsSkill
from core.skills.data_analysis import DataAnalysisSkill
from core.skills.doc_create import DocCreateSkill


# =============================================================================
# HELPERS
# =============================================================================

def make_ctx(llm_response="Mock response", tools_response="Mock tool output"):
    """Create a mock SkillContext with tools and LLM."""
    llm = MagicMock()
    llm_resp = MagicMock()
    llm_resp.content = llm_response
    llm.chat.return_value = llm_resp

    tools = MagicMock()
    tool_result = MagicMock()
    tool_result.success = True
    tool_result.output = tools_response
    tool_result.data = {"urls": ["https://example.com"], "title": "Example"}
    tool_result.error = None
    tools.execute.return_value = tool_result
    tools.get.return_value = None

    memory = MagicMock()
    memory.recall.return_value = []

    return SkillContext(
        tools=tools,
        llm=llm,
        memory=memory,
        user="testuser",
        conversation_history=[],
    )


def ctx_no_tools():
    return SkillContext(tools=None, llm=MagicMock())


def ctx_no_llm():
    tools = MagicMock()
    tool_result = MagicMock()
    tool_result.success = True
    tool_result.output = "tool output"
    tool_result.data = {}
    tools.execute.return_value = tool_result
    return SkillContext(tools=tools, llm=None)


# =============================================================================
# FileOpsSkill
# =============================================================================

class TestFileOpsSkill:
    def test_detect_operations(self):
        s = FileOpsSkill()
        assert s._detect_operation("find py files") == "find"
        assert s._detect_operation("compress this folder") == "compress"
        assert s._detect_operation("extract the archive") == "extract"
        assert s._detect_operation("list files here") == "list"
        assert s._detect_operation("organize my downloads") == "organize"

    def test_find_files(self):
        s = FileOpsSkill()
        ctx = make_ctx(tools_response="file1.py\nfile2.py")
        result = s.execute("find files .py in /home", ctx)
        assert result.success

    def test_list_files(self):
        s = FileOpsSkill()
        ctx = make_ctx(tools_response="file1.txt\nfile2.txt")
        result = s.execute("list files in /tmp", ctx)
        assert result.success

    def test_without_tools(self):
        s = FileOpsSkill()
        ctx = SkillContext()
        result = s.execute("find files", ctx)
        assert not result.success


# =============================================================================
# ScheduleSkill
# =============================================================================

class TestScheduleSkill:
    def test_parse_every_minutes(self):
        s = ScheduleSkill()
        assert s._parse_time_expression("every 5 minutes") == "*/5 * * * *"

    def test_parse_every_hours(self):
        s = ScheduleSkill()
        assert s._parse_time_expression("every 2 hours") == "0 */2 * * *"

    def test_parse_at_time(self):
        s = ScheduleSkill()
        expr = s._parse_time_expression("every day at 9:00")
        assert "9" in expr

    def test_parse_in_minutes(self):
        s = ScheduleSkill()
        assert s._parse_time_expression("in 30 minutes") == "+30m"

    def test_is_calendar_event(self):
        s = ScheduleSkill()
        assert s._is_calendar_event("create a calendar event for meeting")
        assert not s._is_calendar_event("remind me in 5 minutes")

    def test_execute_reminder(self):
        s = ScheduleSkill()
        ctx = make_ctx()
        ctx.tools.get.return_value = ctx.tools
        result = s.execute("remind me every 30 minutes to stretch", ctx)
        assert result.success

    def test_without_tools(self):
        s = ScheduleSkill()
        ctx = SkillContext()
        result = s.execute("remind me", ctx)
        assert not result.success


# =============================================================================
# GitOpsSkill
# =============================================================================

class TestGitOpsSkill:
    def test_parse_query_status(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("git status")
        assert op == "status"

    def test_parse_query_diff(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("what changed today")
        assert op == "diff"

    def test_parse_query_log(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("commit history")
        assert op == "log"

    def test_parse_query_commit(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("commit these changes")
        assert op == "commit"

    def test_parse_query_push(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("push to remote")
        assert op == "push"

    def test_parse_query_merge(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("merge feature-branch")
        assert op == "merge"

    def test_parse_query_stash(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("stash my changes")
        assert op == "stash"

    def test_parse_query_blame(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("blame file.py")
        assert op == "blame"

    def test_parse_query_tag(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("tag v1.0")
        assert op == "tag"

    def test_parse_query_clone(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("clone https://github.com/user/repo")
        assert op == "clone"

    def test_parse_query_overview(self):
        s = GitOpsSkill()
        op, _ = s._parse_query("git summary")
        assert op == "overview"

    def test_execute_status(self):
        s = GitOpsSkill()
        ctx = make_ctx(tools_response="On branch main\nnothing to commit")
        result = s.execute("git status", ctx)
        assert result.success

    def test_execute_log(self):
        s = GitOpsSkill()
        ctx = make_ctx(
            llm_response="Recent commits:\n- Fix bug\n- Add feature",
            tools_response="abc123 Fix bug\ndef456 Add feature"
        )
        result = s.execute("recent commits", ctx)
        assert result.success

    def test_execute_diff_clean(self):
        s = GitOpsSkill()
        ctx = make_ctx(tools_response="(no output)")
        result = s.execute("git diff", ctx)
        assert result.success
        assert "no uncommitted" in result.output.lower()

    def test_execute_commit_with_message(self):
        s = GitOpsSkill()
        ctx = make_ctx(tools_response="[main abc123] fix: update config")
        status_result = MagicMock()
        status_result.success = True
        status_result.output = "M  file.py"
        status_result.data = {"files": {"staged": ["file.py"], "modified": [], "untracked": []}}
        ctx.tools.execute.return_value = status_result
        result = s.execute('commit "fix: update config"', ctx)
        assert result.success

    def test_execute_branch_list(self):
        s = GitOpsSkill()
        ctx = make_ctx(tools_response="* main\n  feature\n  develop")
        result = s.execute("list branches", ctx)
        assert result.success

    def test_execute_stash(self):
        s = GitOpsSkill()
        ctx = make_ctx(tools_response="Saved working directory")
        result = s.execute("stash my changes", ctx)
        assert result.success

    def test_execute_overview(self):
        s = GitOpsSkill()
        ctx = make_ctx(
            llm_response="Overview: main branch, 5 commits, clean tree",
            tools_response="branch info"
        )
        result = s.execute("git overview", ctx)
        assert result.success

    def test_extract_commit_message_quoted(self):
        s = GitOpsSkill()
        msg = s._extract_commit_message('commit "fix: typo in readme"')
        assert msg == "fix: typo in readme"

    def test_extract_commit_message_prefix(self):
        s = GitOpsSkill()
        msg = s._extract_commit_message("commit message: add new feature")
        assert msg == "add new feature"

    def test_without_tools(self):
        s = GitOpsSkill()
        ctx = SkillContext()
        result = s.execute("git log", ctx)
        assert not result.success


# =============================================================================
# GitHubOpsSkill
# =============================================================================

class TestGitHubOpsSkill:
    def test_detect_pr_list(self):
        s = GitHubOpsSkill()
        assert s._detect_operation("list open prs") == "pr_list"

    def test_execute_auth_status(self):
        s = GitHubOpsSkill()
        ctx = make_ctx(tools_response="Logged into GitHub")
        result = s.execute("check github auth", ctx)
        assert result.success

    def test_clone_repo_from_phrase(self):
        s = GitHubOpsSkill()
        ctx = make_ctx(tools_response="Cloning into 'ARIA'...")
        result = s.execute("clona el repo aria de maytrella007 en github", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("git", action="clone", args="https://github.com/maytrella007/aria.git")

    def test_without_tools(self):
        s = GitHubOpsSkill()
        ctx = SkillContext()
        result = s.execute("list prs", ctx)
        assert not result.success


# =============================================================================
# DataAnalysisSkill
# =============================================================================

class TestDataAnalysisSkill:
    def test_detect_analysis(self):
        s = DataAnalysisSkill()
        assert s._detect_analysis("calculate 5 + 3") == "calc"
        assert s._detect_analysis("query database for users") == "query"
        assert s._detect_analysis("average of 10, 20, 30") == "stats"

    def test_extract_expression(self):
        s = DataAnalysisSkill()
        assert s._extract_expression("5 + 3") == "5 + 3"
        assert "100" in s._extract_expression("15% of 100")
        assert "sqrt" in s._extract_expression("sqrt of 144")

    def test_execute_calculation(self):
        s = DataAnalysisSkill()
        ctx = make_ctx(tools_response="351")
        result = s.execute("calculate 15% of 2340", ctx)
        assert result.success

    def test_without_tools(self):
        s = DataAnalysisSkill()
        ctx = SkillContext()
        result = s.execute("calculate 5+3", ctx)
        assert not result.success


# =============================================================================
# DocCreateSkill
# =============================================================================

class TestDocCreateSkill:
    def test_detect_doc_type(self):
        s = DocCreateSkill()
        assert s._detect_doc_type("create a spreadsheet") == "excel"
        assert s._detect_doc_type("create a presentation") == "powerpoint"
        assert s._detect_doc_type("create a document") == "word"
        assert s._detect_doc_type("make a report") == "word"

    def test_extract_filename(self):
        s = DocCreateSkill()
        assert s._extract_filename('create "my_report"', ".docx") == "my_report.docx"
        assert "report" in s._extract_filename("create report.xlsx", ".xlsx")

    def test_execute_word(self):
        s = DocCreateSkill()
        ctx = make_ctx(llm_response='{"title": "Report", "sections": [{"heading": "Intro", "content": "Hello"}]}')
        result = s.execute("create a document about AI", ctx)
        assert result.success

    def test_execute_without_tools(self):
        s = DocCreateSkill()
        ctx = SkillContext(llm=MagicMock())
        result = s.execute("create a doc", ctx)
        assert not result.success

    def test_execute_without_llm(self):
        s = DocCreateSkill()
        ctx = ctx_no_llm()
        result = s.execute("create a document", ctx)
        assert not result.success


# =============================================================================
# Integration: exported tier-2 subset
# =============================================================================

class TestTier2Integration:
    def test_all_tier2_skills_register(self):
        from core.skills import (
            WeatherSkill, ResearchSkill, SummarizeSkill,
            DailyBriefSkill, FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill,
            DataAnalysisSkill, DocCreateSkill, ResearchMonitorSkill,
            InboxTriageSkill, MeetingPrepSkill,
        )
        reg = SkillRegistry()
        for cls in [
            WeatherSkill, ResearchSkill, SummarizeSkill,
            DailyBriefSkill, FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill,
            DataAnalysisSkill, DocCreateSkill, ResearchMonitorSkill,
            InboxTriageSkill, MeetingPrepSkill,
        ]:
            reg.register(cls())
        assert len(reg) == 13

    def test_all_skills_have_descriptions(self):
        """Every skill must have a meaningful description for LLM selection."""
        from core.skills import (
            FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill, DataAnalysisSkill, DocCreateSkill,
            ResearchMonitorSkill, InboxTriageSkill, MeetingPrepSkill,
        )
        for cls in [FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill, DataAnalysisSkill, DocCreateSkill,
                    ResearchMonitorSkill, InboxTriageSkill, MeetingPrepSkill]:
            s = cls()
            assert len(s.description) > 10, f"{s.name} needs a better description"
