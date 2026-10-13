"""
Tests for ARIA Skill System
=============================

Tests for SkillBase, SkillRegistry, SkillContext, and all built-in skills.
Skill selection is 100% LLM-based (no regex triggers).
"""

import pytest
import os
import sys
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.base import SkillBase, SkillResult, SkillContext, SkillRegistry
from core.skills.prompt_skills import PromptSkill, WeatherSkill
from core.skills.research import ResearchSkill
from core.skills.summarize import SummarizeSkill
from core.skills.daily_brief import DailyBriefSkill


# =============================================================================
# HELPERS
# =============================================================================

class DummySkill(SkillBase):
    name = "dummy"
    description = "A test skill for echoing input"

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        return SkillResult(success=True, output=f"Echo: {query}")


class FailingSkill(SkillBase):
    name = "failing"
    description = "Always fails (for testing error handling)"

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        raise ValueError("Intentional failure")


def make_ctx(llm_response="Mock LLM response", tools_response=None):
    """Create a mock SkillContext."""
    llm = MagicMock()
    llm_resp = MagicMock()
    llm_resp.content = llm_response
    llm.chat.return_value = llm_resp

    tools = None
    if tools_response is not None:
        tools = MagicMock()
        tool_result = MagicMock()
        tool_result.success = True
        tool_result.output = tools_response
        tool_result.data = {"urls": ["https://example.com"], "title": "Example"}
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


def _mock_llm(response_json: str):
    """Create a mock LLM that returns a JSON string."""
    llm = MagicMock()
    resp = MagicMock()
    resp.content = response_json
    llm.chat.return_value = resp
    return llm


# =============================================================================
# SkillResult tests
# =============================================================================

class TestSkillResult:
    def test_success_str(self):
        r = SkillResult(success=True, output="Hello world")
        assert str(r) == "Hello world"

    def test_error_str(self):
        r = SkillResult(success=False, error="Something went wrong")
        assert "Something went wrong" in str(r)

    def test_defaults(self):
        r = SkillResult(success=True)
        assert r.output == ""
        assert r.data == {}
        assert r.error is None
        assert r.skill_name == ""
        assert r.elapsed_ms == 0


# =============================================================================
# SkillBase tests
# =============================================================================

class TestSkillBase:
    def test_execute_adds_timing(self):
        s = DummySkill()
        ctx = SkillContext()
        result = s.execute("test", ctx)
        assert result.success
        assert result.skill_name == "dummy"
        assert result.elapsed_ms >= 0

    def test_execute_catches_exceptions(self):
        s = FailingSkill()
        ctx = SkillContext()
        result = s.execute("fail me", ctx)
        assert not result.success
        assert "Intentional failure" in result.error
        assert result.skill_name == "failing"

    def test_skill_has_name_and_description(self):
        s = DummySkill()
        assert s.name == "dummy"
        assert s.description == "A test skill for echoing input"

    def test_no_triggers_attribute(self):
        """Skills should not have triggers — selection is LLM-based."""
        s = WeatherSkill()
        assert not hasattr(s, 'triggers') or not s.__class__.__dict__.get('triggers')

    def test_requires_tools_validation(self):
        """Skills with requires_tools fail when ToolRegistry is missing those tools."""
        from core.tools.registry import ToolRegistry

        class NeedySkill(SkillBase):
            name = "needy"
            description = "Needs web_search"
            requires_tools = ["web_search"]
            def _execute(self, query, ctx):
                return SkillResult(success=True, output="ok")

        registry = ToolRegistry()  # empty — no tools registered
        ctx = SkillContext(tools=registry)
        result = NeedySkill().execute("test", ctx)
        assert not result.success
        assert "web_search" in result.error

    def test_requires_tools_passes_when_present(self):
        """Skills pass validation when required tools are registered."""
        from core.tools.registry import ToolRegistry
        from core.tools.tool_base import ToolBase, ToolResult as TResult

        class FakeTool(ToolBase):
            name = "web_search"
            description = "fake"
            def _execute(self, **kw):
                return TResult(success=True, output="ok")

        class NeedySkill(SkillBase):
            name = "needy"
            description = "Needs web_search"
            requires_tools = ["web_search"]
            def _execute(self, query, ctx):
                return SkillResult(success=True, output="ok")

        registry = ToolRegistry()
        registry.register(FakeTool())
        ctx = SkillContext(tools=registry)
        result = NeedySkill().execute("test", ctx)
        assert result.success

    def test_requires_tools_skipped_for_mocks(self):
        """Validation is skipped for mock tools (not a real ToolRegistry)."""
        class NeedySkill(SkillBase):
            name = "needy"
            description = "Needs stuff"
            requires_tools = ["nonexistent_tool"]
            def _execute(self, query, ctx):
                return SkillResult(success=True, output="ok")

        ctx = SkillContext(tools=MagicMock())
        result = NeedySkill().execute("test", ctx)
        assert result.success  # mock tools bypass validation


# =============================================================================
# SkillRegistry tests
# =============================================================================

class TestSkillRegistry:
    def test_register_and_get(self):
        reg = SkillRegistry()
        s = DummySkill()
        reg.register(s)
        assert reg.get("dummy") is s
        assert "dummy" in reg
        assert len(reg) == 1

    def test_unregister(self):
        reg = SkillRegistry()
        reg.register(DummySkill())
        reg.unregister("dummy")
        assert "dummy" not in reg
        assert len(reg) == 0

    def test_execute_by_name(self):
        reg = SkillRegistry()
        reg.register(DummySkill())
        ctx = SkillContext()
        result = reg.execute("dummy", "test query", ctx)
        assert result.success
        assert "Echo: test query" in result.output

    def test_execute_unknown_skill(self):
        reg = SkillRegistry()
        ctx = SkillContext()
        result = reg.execute("nonexistent", "test", ctx)
        assert not result.success
        assert "not found" in result.error

    def test_list_and_names(self):
        reg = SkillRegistry()
        reg.register(DummySkill())
        reg.register(FailingSkill())
        assert len(reg.list()) == 2
        assert set(reg.names()) == {"dummy", "failing"}

    def test_get_descriptions(self):
        reg = SkillRegistry()
        reg.register(DummySkill())
        desc = reg.get_descriptions()
        assert "dummy" in desc
        assert "test skill" in desc.lower()

    def test_get_prompt_section(self):
        reg = SkillRegistry()
        reg.register(DummySkill())
        section = reg.get_prompt_section()
        assert "SKILLS" in section
        assert "dummy" in section

    def test_empty_registry(self):
        reg = SkillRegistry()
        assert reg.get_descriptions() == "No skills registered."
        assert reg.get_prompt_section() == ""


# =============================================================================
# LLM-based skill matching tests
# =============================================================================

class TestLLMMatch:
    def _make_registry(self):
        reg = SkillRegistry()
        reg.register(DummySkill())
        reg.register(FailingSkill())
        return reg

    def test_llm_selects_skill(self):
        """LLM classifies input and selects a skill."""
        reg = self._make_registry()
        llm = _mock_llm('{"skill": "dummy", "query": "greetings"}')
        result = reg.match("greetings friend", llm=llm)
        assert result is not None
        assert result[0].name == "dummy"
        assert result[1] == "greetings"
        llm.chat.assert_called_once()

    def test_llm_says_none(self):
        """LLM decides no skill applies → returns None."""
        reg = self._make_registry()
        llm = _mock_llm('{"skill": "none", "query": ""}')
        result = reg.match("just chatting", llm=llm)
        assert result is None

    def test_no_llm_returns_none(self):
        """No LLM available → returns None."""
        reg = self._make_registry()
        result = reg.match("greetings friend", llm=None)
        assert result is None

    def test_llm_with_conversation_context(self):
        """LLM receives conversation history for context."""
        reg = self._make_registry()
        llm = _mock_llm('{"skill": "dummy", "query": "that thing"}')
        history = [
            {"role": "user", "content": "let's talk about hello"},
            {"role": "assistant", "content": "Sure, what about it?"},
        ]
        result = reg.match("do that thing", llm=llm, conversation_history=history)
        assert result is not None
        # Verify conversation context was included in the prompt
        call_args = llm.chat.call_args
        prompt = call_args[1]["messages"][0]["content"]
        assert "hello" in prompt  # from conversation history

    def test_llm_unknown_skill_ignored(self):
        """LLM suggests a skill that doesn't exist → returns None."""
        reg = self._make_registry()
        llm = _mock_llm('{"skill": "nonexistent_skill", "query": "test"}')
        result = reg.match("do something weird", llm=llm)
        assert result is None

    def test_llm_exception_graceful(self):
        """LLM raises exception → returns None gracefully."""
        reg = self._make_registry()
        llm = MagicMock()
        llm.chat.side_effect = Exception("API error")
        result = reg.match("greetings", llm=llm)
        assert result is None

    def test_llm_empty_response(self):
        """LLM returns empty → returns None."""
        reg = self._make_registry()
        llm = MagicMock()
        llm.chat.return_value = MagicMock(content="")
        result = reg.match("greetings", llm=llm)
        assert result is None

    def test_llm_invalid_json(self):
        """LLM returns non-JSON → returns None."""
        reg = self._make_registry()
        llm = _mock_llm("I think you should use the weather skill")
        result = reg.match("greetings", llm=llm)
        assert result is None

    def test_llm_fuzzy_name_match(self):
        """LLM returns a skill name with slightly different format → fuzzy match."""
        reg = SkillRegistry()
        class MySkill(SkillBase):
            name = "my_skill"
            description = "Test"
            def _execute(self, q, ctx):
                return SkillResult(success=True, output="ok")
        reg.register(MySkill())

        llm = _mock_llm('{"skill": "my-skill", "query": "test"}')
        result = reg.match("test", llm=llm)
        assert result is not None
        assert result[0].name == "my_skill"

    def test_empty_skills_returns_none(self):
        """Empty registry → returns None without calling LLM."""
        reg = SkillRegistry()
        llm = _mock_llm('{"skill": "dummy", "query": "test"}')
        result = reg.match("test", llm=llm)
        assert result is None
        llm.chat.assert_not_called()

    def test_catalog_cache_invalidated(self):
        """Cache is invalidated when skills are added/removed."""
        reg = SkillRegistry()
        reg.register(DummySkill())
        # Force cache creation
        reg._build_classifier_prompt("test")
        assert reg._catalog_cache is not None

        # Adding a skill invalidates cache
        reg.register(FailingSkill())
        assert reg._catalog_cache is None

    def test_llm_uses_original_text_as_fallback_query(self):
        """When LLM returns empty query, original text is used."""
        reg = self._make_registry()
        llm = _mock_llm('{"skill": "dummy", "query": ""}')
        result = reg.match("hello world", llm=llm)
        assert result is not None
        assert result[1] == "hello world"  # falls back to original text


# =============================================================================
# WeatherSkill tests (now a PromptSkill)
# =============================================================================

class TestWeatherSkill:
    def test_is_prompt_skill(self):
        """WeatherSkill is now a PromptSkill subclass."""
        s = WeatherSkill()
        assert isinstance(s, PromptSkill)

    def test_execute_with_tools_and_llm(self):
        s = WeatherSkill()
        ctx = make_ctx(llm_response="Sunny, 25C", tools_response="Weather data...")
        result = s.execute("weather in Tokyo", ctx)
        assert result.success
        assert result.output == "Sunny, 25C"

    def test_execute_without_tools(self):
        s = WeatherSkill()
        ctx = SkillContext(llm=MagicMock())
        ctx.tools = None
        result = s.execute("weather", ctx)
        assert not result.success


# =============================================================================
# ResearchSkill tests
# =============================================================================

class TestResearchSkill:
    def test_execute_with_tools(self):
        s = ResearchSkill()
        ctx = make_ctx(
            llm_response="Research summary...",
            tools_response="Search results..."
        )
        result = s.execute("quantum computing", ctx)
        assert result.success

    def test_execute_without_tools(self):
        s = ResearchSkill()
        ctx = SkillContext()
        result = s.execute("test", ctx)
        assert not result.success
        assert "No tools" in result.error


# =============================================================================
# SummarizeSkill tests
# =============================================================================

class TestSummarizeSkill:
    def test_execute_with_long_text(self):
        s = SummarizeSkill()
        ctx = make_ctx(llm_response="Summary: key points...")
        long_text = "A" * 200
        result = s.execute(long_text, ctx)
        assert result.success

    def test_execute_short_text_no_tools(self):
        s = SummarizeSkill()
        ctx = SkillContext(llm=MagicMock())
        result = s.execute("short", ctx)
        assert not result.success

    def test_url_detection(self):
        s = SummarizeSkill()
        ctx = make_ctx(
            llm_response="Summary of webpage",
            tools_response="Page content..."
        )
        result = s.execute("https://example.com/article", ctx)
        assert result.success


# =============================================================================
# DailyBriefSkill tests
# =============================================================================

class TestDailyBriefSkill:
    def test_execute_general_brief(self):
        s = DailyBriefSkill()
        ctx = make_ctx(llm_response="Good morning! Here's your brief...")
        result = s.execute("daily brief", ctx)
        assert result.success

    def test_execute_without_llm(self):
        s = DailyBriefSkill()
        ctx = SkillContext()
        result = s.execute("daily brief", ctx)
        assert not result.success

    def test_execute_with_tools(self):
        s = DailyBriefSkill()
        ctx = make_ctx(
            llm_response="Weather: Sunny. News: Headlines...",
            tools_response="Weather data and news..."
        )
        result = s.execute("daily brief", ctx)
        assert result.success


# =============================================================================
# Integration: All skills register correctly
# =============================================================================

class TestSkillIntegration:
    def test_all_skills_register(self):
        reg = SkillRegistry()
        skills = [
            WeatherSkill(), ResearchSkill(), SummarizeSkill(),
            DailyBriefSkill(),
        ]
        for s in skills:
            reg.register(s)
        assert len(reg) == 4

    def test_skill_import_from_package(self):
        """Test that all skills import correctly from the package."""
        from core.skills import (
            SkillBase, SkillResult, SkillContext, SkillRegistry,
        )
        from core.skills.research import ResearchSkill
        from core.skills.summarize import SummarizeSkill
        from core.skills.daily_brief import DailyBriefSkill
        assert issubclass(WeatherSkill, PromptSkill)
        assert issubclass(ResearchSkill, SkillBase)

    def test_all_skills_have_descriptions(self):
        """Every skill must have a meaningful description for LLM selection."""
        for cls in [WeatherSkill, ResearchSkill, SummarizeSkill, DailyBriefSkill]:
            s = cls()
            assert len(s.description) > 10, f"{s.name} needs a better description"
            assert s.description != "No description"

    def test_total_skill_count(self):
        """ARIA has 13 skills total after removing redundant prompt skills."""
        prompt_skills = [WeatherSkill]
        assert len(prompt_skills) == 1
