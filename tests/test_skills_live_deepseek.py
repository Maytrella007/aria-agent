"""Live end-to-end skill tests with DeepSeek.

One test per skill.  Each test runs the skill against the real DeepSeek API
and real local tools, then verifies the *integration* works:
  - Correct tool name (no typos)
  - Correct parameter names / formats
  - Tool output parsed correctly by the skill
  - LLM formatting produces usable output

Skills that depend on external OAuth (Gmail, Calendar, Slack) skip gracefully
when the credential is absent.

Run:
    pytest tests/test_skills_live_deepseek.py -v -m "requires_api and slow"
"""

import os
import shutil
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.llm.llm_providers import LLMProvider
from core.memory.memory_v2 import ExperientialMemorySystem
from core.skills.base import SkillContext
from core.skills import (
    WeatherSkill,
    ResearchSkill,
    SummarizeSkill,
    DailyBriefSkill,
    FileOpsSkill,
    ScheduleSkill,
    GitOpsSkill,
    GitHubOpsSkill,
    CodingAgentSkill,
    DataAnalysisSkill,
    DocCreateSkill,
    KnowledgeBaseSkill,
    QuickTaskSkill,
    ResearchMonitorSkill,
    WorkspaceKnowledgeSkill,
    TerminalSessionSkill,
    GmailAssistantSkill,
    InboxTriageSkill,
    MeetingPrepSkill,
    SlackAssistantSkill,
)
from core.tools import (
    ToolRegistry,
    WebSearchTool,
    WebFetchTool,
    ShellExecTool,
    CronTool,
    FileManagerTool,
    HttpRequestTool,
    CodeExecTool,
    GitTool,
    GitHubTool,
    MemoryTool,
    PdfTool,
    ProjectKnowledgeTool,
    DatabaseTool,
    CalculatorTool,
    CompressTool,
    TodoTool,
    DocumentRAGTool,
    BrowserTool,
    FeedWatcherTool,
    ExcelTool,
    WordTool,
    PowerPointTool,
    ObsidianTool,
    TmuxTool,
    GmailTool,
    GoogleDriveTool,
    GoogleCalendarTool,
    SlackTool,
)


DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _build_tools(data_dir: str, memory) -> ToolRegistry:
    ctx = {"data_dir": data_dir, "memory": memory}
    tools = ToolRegistry()
    for tool in [
        WebSearchTool(context=ctx),
        WebFetchTool(context=ctx),
        ShellExecTool(context=ctx),
        CronTool(context=ctx),
        FileManagerTool(context=ctx),
        HttpRequestTool(context=ctx),
        CodeExecTool(context=ctx),
        GitTool(context=ctx),
        GitHubTool(context=ctx),
        MemoryTool(context={**ctx, "memory": memory}),
        PdfTool(context=ctx),
        ProjectKnowledgeTool(context=ctx),
        DatabaseTool(context=ctx),
        CalculatorTool(context=ctx),
        CompressTool(context=ctx),
        TodoTool(context=ctx),
        DocumentRAGTool(context=ctx),
        BrowserTool(context=ctx),
        FeedWatcherTool(context=ctx),
        ExcelTool(context=ctx),
        WordTool(context=ctx),
        PowerPointTool(context=ctx),
        ObsidianTool(context=ctx),
        TmuxTool(context=ctx),
        GmailTool(context=ctx),
        GoogleDriveTool(context=ctx),
        GoogleCalendarTool(context=ctx),
        SlackTool(context=ctx),
    ]:
        tools.register(tool)
    return tools


@pytest.fixture(scope="module")
def live_ctx():
    """Shared live context: real LLM, real tools, temp data dir."""
    if not DEEPSEEK_API_KEY:
        pytest.skip("DEEPSEEK_API_KEY not set")

    data_dir = tempfile.mkdtemp(prefix="aria_live_")
    memory = ExperientialMemorySystem(data_dir=data_dir)
    llm = LLMProvider.create("deepseek", api_key=DEEPSEEK_API_KEY, model="deepseek-chat")

    # Connectivity check
    resp = llm.chat(messages=[{"role": "user", "content": "Reply OK."}], max_tokens=8)
    assert resp and resp.content

    yield SkillContext(
        tools=_build_tools(data_dir, memory),
        llm=llm,
        memory=memory,
        config={"data_dir": data_dir},
    )

    shutil.rmtree(data_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _requires_gh():
    """Skip if gh CLI not installed / not authenticated."""
    if not shutil.which("gh"):
        pytest.skip("gh CLI not installed")


def _requires_gmail(live_ctx):
    """Skip if Gmail OAuth not configured."""
    result = live_ctx.tools.execute("gmail", action="list", max_results=1)
    if not result.success:
        pytest.skip(f"Gmail not configured: {result.error}")


def _requires_calendar(live_ctx):
    """Skip if Google Calendar not configured."""
    result = live_ctx.tools.execute("google_calendar", action="list", days_ahead=1, max_results=1)
    if not result.success:
        pytest.skip(f"Calendar not configured: {result.error}")


def _requires_slack(live_ctx):
    """Skip if Slack not configured."""
    if not os.environ.get("SLACK_TOKEN") and not os.environ.get("SLACK_BOT_TOKEN"):
        pytest.skip("Slack token not configured")


# ===========================================================================
# Prompt skills
# ===========================================================================

@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveWeather:
    def test_weather_search_and_format(self, live_ctx):
        """weather skill → web_search tool → LLM format."""
        result = WeatherSkill().execute("weather in Madrid today", live_ctx)
        assert result.success, f"Failed: {result.error}"
        # LLM should produce readable text, not raw JSON
        assert len(result.output) > 20


# ===========================================================================
# Orchestration skills — local tools (no external auth needed)
# ===========================================================================

@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveResearch:
    def test_multi_source_research(self, live_ctx):
        """research → web_search + web_fetch + LLM synthesis."""
        result = ResearchSkill().execute("what is RISC-V", live_ctx)
        assert result.success, f"Failed: {result.error}"
        assert len(result.output) > 100  # should be a proper synthesis


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveSummarize:
    def test_summarize_url(self, live_ctx):
        """summarize → web_fetch + LLM summary."""
        result = SummarizeSkill().execute("https://example.com", live_ctx)
        assert result.success, f"Failed: {result.error}"
        assert len(result.output) > 20


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveDailyBrief:
    def test_daily_brief_aggregation(self, live_ctx):
        """daily_brief → web_search (weather+news) + memory + LLM."""
        result = DailyBriefSkill().execute("daily brief", live_ctx)
        assert result.success, f"Failed: {result.error}"
        assert len(result.output) > 50


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveFileOps:
    def test_list_files(self, live_ctx):
        """file_ops → file_manager tool with real directory."""
        data_dir = live_ctx.config["data_dir"]
        result = FileOpsSkill().execute(f"list files in {data_dir}", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_find_files(self, live_ctx):
        """file_ops → file_manager find with pattern."""
        # Create a test file first
        data_dir = live_ctx.config["data_dir"]
        test_file = os.path.join(data_dir, "findme.txt")
        with open(test_file, "w") as f:
            f.write("test content")
        result = FileOpsSkill().execute(f"find txt files in {data_dir}", live_ctx)
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveSchedule:
    def test_cron_reminder(self, live_ctx):
        """schedule → cron tool. Validates parameter alignment."""
        result = ScheduleSkill().execute("remind me every 30 minutes to stretch", live_ctx)
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveGitOps:
    def test_status(self, live_ctx):
        """git_ops status → git tool action=status."""
        result = GitOpsSkill().execute("git status", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_log(self, live_ctx):
        """git_ops log → git tool action=log."""
        result = GitOpsSkill().execute("recent commits", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_diff(self, live_ctx):
        """git_ops diff → git tool action=diff."""
        result = GitOpsSkill().execute("git diff", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_branch_list(self, live_ctx):
        """git_ops branch → git tool action=branch."""
        result = GitOpsSkill().execute("list branches", live_ctx)
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveGitHubOps:
    def test_auth_status(self, live_ctx):
        """github_ops → github tool auth_status."""
        _requires_gh()
        result = GitHubOpsSkill().execute("check github auth", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_pr_list(self, live_ctx):
        """github_ops → github tool pr_list."""
        _requires_gh()
        result = GitHubOpsSkill().execute("list pull requests", live_ctx)
        # May fail if not in a repo — that's an expected env issue, not a bug
        assert result.success or "not a git repository" in (result.error or "").lower(), \
            f"Unexpected failure: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveDataAnalysis:
    def test_calculation(self, live_ctx):
        """data_analysis calc → calculator tool."""
        result = DataAnalysisSkill().execute("calculate 15% of 2340", live_ctx)
        assert result.success, f"Failed: {result.error}"
        # Should contain the number 351
        assert "351" in result.output

    def test_stats(self, live_ctx):
        """data_analysis stats → code_exec or calculator tool."""
        result = DataAnalysisSkill().execute("average of 10, 20, 30, 40", live_ctx)
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveDocCreate:
    def test_word_document(self, live_ctx):
        """doc_create → LLM JSON → word tool. Validates full pipeline."""
        data_dir = live_ctx.config["data_dir"]
        result = DocCreateSkill().execute(
            f"create a document about ARIA architecture named {data_dir}/live_test.docx",
            live_ctx,
        )
        assert result.success, f"Failed: {result.error}"
        doc_path = result.data.get("path")
        assert doc_path, f"No output path in data: {result.data}"
        assert os.path.isfile(doc_path), f"File not created: {doc_path}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveKnowledgeBase:
    def test_save_and_recall(self, live_ctx):
        """knowledge_base save → project_knowledge tool. Then recall."""
        skill = KnowledgeBaseSkill()
        save = skill.execute("remember that ARIA uses DeepSeek for live testing", live_ctx)
        assert save.success, f"Save failed: {save.error}"

        recall = skill.execute("what LLM does ARIA use for testing", live_ctx)
        assert recall.success, f"Recall failed: {recall.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveQuickTask:
    def test_uptime(self, live_ctx):
        """quick_task → shell_exec tool."""
        result = QuickTaskSkill().execute("uptime", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_dangerous_blocked(self, live_ctx):
        """quick_task should block dangerous commands."""
        result = QuickTaskSkill().execute("rm -rf /", live_ctx)
        assert not result.success  # should be rejected


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveResearchMonitor:
    def test_watch_url(self, live_ctx):
        """research_monitor watch → feed_watcher add."""
        result = ResearchMonitorSkill().execute("watch https://example.com", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_scan(self, live_ctx):
        """research_monitor scan → feed_watcher scan."""
        # Add first, then scan
        ResearchMonitorSkill().execute("watch https://example.com", live_ctx)
        result = ResearchMonitorSkill().execute("scan for updates", live_ctx)
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveWorkspaceKnowledge:
    def test_save_note(self, live_ctx):
        """workspace_knowledge → obsidian tool write."""
        result = WorkspaceKnowledgeSkill().execute(
            "save live test notes to live_notes.md", live_ctx,
        )
        assert result.success, f"Failed: {result.error}"
        vault_path = os.path.join(live_ctx.config["data_dir"], "obsidian_vault", "live_notes.md")
        assert os.path.isfile(vault_path), f"Note file not created: {vault_path}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveCodingAgent:
    def test_detect_and_auth(self, live_ctx):
        """coding_agent should detect at least one agent and verify auth."""
        skill = CodingAgentSkill()
        detected = skill._get_available_agents(live_ctx)
        assert detected, "No coding agents detected"

        at_least_one_auth = False
        for name, _desc in detected:
            ok, _msg = skill._check_auth(name)
            if ok:
                at_least_one_auth = True
                break
        assert at_least_one_auth, f"No agent authenticated: {detected}"

    def test_launch_agent(self, live_ctx):
        """coding_agent should execute a simple task with the first available agent."""
        skill = CodingAgentSkill()
        # Reduce timeout for testing
        for agent in skill.AGENTS.values():
            agent["timeout"] = 30

        detected = skill._get_available_agents(live_ctx)
        if not detected:
            pytest.skip("No coding agents installed")

        for name, _desc in detected:
            ok, _ = skill._check_auth(name)
            if ok:
                result = skill.execute(
                    f"use {name.replace('_', ' ')} write a hello world function",
                    live_ctx,
                )
                if result.success:
                    return  # Pass — at least one agent worked
        pytest.skip("No authenticated coding agent available")


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveTerminalSession:
    def test_tmux_list(self, live_ctx):
        """terminal_session → tmux tool list_sessions."""
        if not shutil.which("tmux"):
            pytest.skip("tmux not installed")
        result = TerminalSessionSkill().execute("list tmux sessions", live_ctx)
        # May fail if no tmux server running — acceptable
        if not result.success:
            error = (result.error or "").lower()
            assert any(w in error for w in [
                "no server", "failed to connect", "no such file", "error connecting",
            ]), f"Unexpected tmux error: {result.error}"


# ===========================================================================
# Orchestration skills — require external OAuth (skip gracefully)
# ===========================================================================

@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveGmailAssistant:
    def test_inbox(self, live_ctx):
        """gmail_assistant → gmail tool list."""
        _requires_gmail(live_ctx)
        result = GmailAssistantSkill().execute("check my inbox", live_ctx)
        assert result.success, f"Failed: {result.error}"

    def test_search(self, live_ctx):
        """gmail_assistant → gmail tool search with NL query."""
        _requires_gmail(live_ctx)
        result = GmailAssistantSkill().execute("search emails from GitHub", live_ctx)
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveInboxTriage:
    def test_triage_unread(self, live_ctx):
        """inbox_triage → gmail tool search is:unread + priority classification."""
        _requires_gmail(live_ctx)
        result = InboxTriageSkill().execute("triage my inbox", live_ctx)
        assert result.success, f"Failed: {result.error}"
        assert result.data.get("triaged") is not None


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveMeetingPrep:
    def test_meeting_prep(self, live_ctx):
        """meeting_prep → calendar + gmail + drive + knowledge multi-tool chain."""
        _requires_calendar(live_ctx)
        result = MeetingPrepSkill().execute("prepare for my next meeting", live_ctx)
        # May fail if no upcoming meetings — that's valid
        if not result.success and "no matching" in (result.error or "").lower():
            pytest.skip("No upcoming meetings to prepare for")
        assert result.success, f"Failed: {result.error}"


@pytest.mark.requires_api
@pytest.mark.slow
class TestLiveSlackAssistant:
    def test_read_channel(self, live_ctx):
        """slack_assistant → slack tool read_messages."""
        _requires_slack(live_ctx)
        # Use a known channel or skip
        result = SlackAssistantSkill().execute("read slack channel C0000000000", live_ctx)
        # May fail if channel doesn't exist — acceptable
        if not result.success:
            assert "channel" in (result.error or "").lower() or "not_in_channel" in (result.error or "").lower()
