"""
Tests for ARIA Function Calling (Phase 3)
==========================================

Tests for tool call format helpers and LLM provider integration.
"""

import pytest
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.llm_providers import (
    ToolCall,
    LLMResponse,
    _openai_format_tools,
    _openai_parse_tool_calls,
    _anthropic_format_tools,
)


# =============================================================================
# SAMPLE DATA
# =============================================================================

SAMPLE_TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "shell_exec",
        "description": "Execute a command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run"},
            },
            "required": ["command"],
        },
    },
]


# =============================================================================
# TOOL CALL DATACLASS
# =============================================================================

class TestToolCall:
    def test_basic(self):
        tc = ToolCall(id="123", name="web_search", args={"query": "test"})
        assert tc.id == "123"
        assert tc.name == "web_search"
        assert tc.args == {"query": "test"}

    def test_empty_args(self):
        tc = ToolCall(id="x", name="foo", args={})
        assert tc.args == {}


# =============================================================================
# LLM RESPONSE WITH TOOL CALLS
# =============================================================================

class TestLLMResponseToolCalls:
    def test_no_tool_calls(self):
        r = LLMResponse(content="hello", model="m", provider="p")
        assert r.tool_calls is None

    def test_with_tool_calls(self):
        calls = [ToolCall(id="1", name="web_search", args={"query": "test"})]
        r = LLMResponse(content="", model="m", provider="p", tool_calls=calls)
        assert len(r.tool_calls) == 1
        assert r.tool_calls[0].name == "web_search"

    def test_multiple_tool_calls(self):
        calls = [
            ToolCall(id="1", name="web_search", args={"query": "a"}),
            ToolCall(id="2", name="shell_exec", args={"command": "ls"}),
        ]
        r = LLMResponse(content="", model="m", provider="p", tool_calls=calls)
        assert len(r.tool_calls) == 2


# =============================================================================
# OPENAI FORMAT
# =============================================================================

class TestOpenAIFormat:
    def test_format_tools(self):
        result = _openai_format_tools(SAMPLE_TOOLS)
        assert len(result) == 2
        assert result[0]["type"] == "function"
        assert result[0]["function"]["name"] == "web_search"
        assert "parameters" in result[0]["function"]

    def test_format_preserves_properties(self):
        result = _openai_format_tools(SAMPLE_TOOLS)
        props = result[0]["function"]["parameters"]["properties"]
        assert "query" in props

    def test_parse_no_tool_calls(self):
        class MockMsg:
            tool_calls = None
            content = "hello"
        assert _openai_parse_tool_calls(MockMsg()) is None

    def test_parse_with_tool_calls(self):
        class MockFunction:
            name = "web_search"
            arguments = '{"query": "test"}'

        class MockToolCall:
            id = "call_123"
            function = MockFunction()

        class MockMsg:
            tool_calls = [MockToolCall()]
            content = None

        result = _openai_parse_tool_calls(MockMsg())
        assert result is not None
        assert len(result) == 1
        assert result[0].name == "web_search"
        assert result[0].args == {"query": "test"}
        assert result[0].id == "call_123"

    def test_parse_bad_json_args(self):
        class MockFunction:
            name = "test"
            arguments = "not json"

        class MockToolCall:
            id = "x"
            function = MockFunction()

        class MockMsg:
            tool_calls = [MockToolCall()]

        result = _openai_parse_tool_calls(MockMsg())
        assert result is not None
        assert result[0].args == {}

    def test_parse_dict_args(self):
        """Some providers return args as dict, not string."""
        class MockFunction:
            name = "test"
            arguments = {"key": "value"}

        class MockToolCall:
            id = "x"
            function = MockFunction()

        class MockMsg:
            tool_calls = [MockToolCall()]

        result = _openai_parse_tool_calls(MockMsg())
        assert result[0].args == {"key": "value"}


# =============================================================================
# ANTHROPIC FORMAT
# =============================================================================

class TestAnthropicFormat:
    def test_format_tools(self):
        result = _anthropic_format_tools(SAMPLE_TOOLS)
        assert len(result) == 2
        assert result[0]["name"] == "web_search"
        assert "input_schema" in result[0]
        assert "type" not in result[0]  # No "type: function" wrapper

    def test_format_preserves_schema(self):
        result = _anthropic_format_tools(SAMPLE_TOOLS)
        schema = result[0]["input_schema"]
        assert schema["type"] == "object"
        assert "query" in schema["properties"]


# =============================================================================
# INTEGRATION: TOOL SCHEMAS FROM REGISTRY
# =============================================================================

class TestRegistrySchemas:
    def test_schemas_are_valid_for_openai(self):
        from core.tools import ToolRegistry, WebSearchTool, ShellExecTool
        reg = ToolRegistry()
        reg.register(WebSearchTool())
        reg.register(ShellExecTool())

        schemas = reg.get_function_schemas()
        openai_tools = _openai_format_tools(schemas)

        assert len(openai_tools) == 2
        for t in openai_tools:
            assert t["type"] == "function"
            assert "name" in t["function"]
            assert "parameters" in t["function"]

    def test_schemas_are_valid_for_anthropic(self):
        from core.tools import ToolRegistry, WebSearchTool, ShellExecTool
        reg = ToolRegistry()
        reg.register(WebSearchTool())
        reg.register(ShellExecTool())

        schemas = reg.get_function_schemas()
        anthropic_tools = _anthropic_format_tools(schemas)

        assert len(anthropic_tools) == 2
        for t in anthropic_tools:
            assert "name" in t
            assert "input_schema" in t
