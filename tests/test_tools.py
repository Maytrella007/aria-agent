"""
Tests for ARIA Tool System
============================

Tests for ToolBase, ToolRegistry, and built-in tools.
"""

import pytest
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools import (
    ToolBase,
    ToolParam,
    ToolResult,
    ToolRegistry,
    WebSearchTool,
    WebFetchTool,
    ShellExecTool,
)


# =============================================================================
# HELPERS
# =============================================================================

class EchoTool(ToolBase):
    """Simple tool for testing."""
    name = "echo"
    description = "Echoes input back"
    parameters = [
        ToolParam(name="text", type="string", description="Text to echo", required=True),
        ToolParam(name="prefix", type="string", description="Optional prefix", default=""),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        text = kwargs["text"]
        prefix = kwargs.get("prefix", "")
        output = f"{prefix}{text}" if prefix else text
        return ToolResult(success=True, output=output, data={"text": text})


class FailTool(ToolBase):
    """Tool that always raises."""
    name = "fail"
    description = "Always fails"
    parameters = []

    def _execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("Intentional failure")


class EnumTool(ToolBase):
    """Tool with enum parameter."""
    name = "enum_tool"
    description = "Has enum param"
    parameters = [
        ToolParam(
            name="mode",
            type="string",
            description="Mode",
            required=True,
            enum=["fast", "slow"],
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, output=kwargs["mode"])


# =============================================================================
# TOOL RESULT TESTS
# =============================================================================

class TestToolResult:
    def test_success_str(self):
        r = ToolResult(success=True, output="hello")
        assert str(r) == "hello"

    def test_error_str(self):
        r = ToolResult(success=False, error="boom")
        assert "boom" in str(r)

    def test_default_values(self):
        r = ToolResult(success=True)
        assert r.output == ""
        assert r.data == {}
        assert r.error is None
        assert r.metadata == {}


# =============================================================================
# TOOL BASE TESTS
# =============================================================================

class TestToolBase:
    def test_execute_success(self):
        tool = EchoTool()
        result = tool.execute(text="hello")
        assert result.success is True
        assert result.output == "hello"
        assert result.data["text"] == "hello"
        assert "elapsed_ms" in result.metadata
        assert result.metadata["tool"] == "echo"

    def test_execute_with_optional(self):
        tool = EchoTool()
        result = tool.execute(text="world", prefix="Hello ")
        assert result.output == "Hello world"

    def test_execute_default_applied(self):
        tool = EchoTool()
        result = tool.execute(text="test")
        assert result.success is True

    def test_missing_required_param(self):
        tool = EchoTool()
        result = tool.execute()
        assert result.success is False
        assert "Missing required" in result.error

    def test_invalid_enum_value(self):
        tool = EnumTool()
        result = tool.execute(mode="invalid")
        assert result.success is False
        assert "Invalid value" in result.error

    def test_valid_enum_value(self):
        tool = EnumTool()
        result = tool.execute(mode="fast")
        assert result.success is True
        assert result.output == "fast"

    def test_exception_handling(self):
        tool = FailTool()
        result = tool.execute()
        assert result.success is False
        assert "Intentional failure" in result.error
        assert "elapsed_ms" in result.metadata

    def test_timing_metadata(self):
        tool = EchoTool()
        result = tool.execute(text="timing")
        assert result.metadata["elapsed_ms"] >= 0


# =============================================================================
# FUNCTION SCHEMA TESTS
# =============================================================================

class TestFunctionSchema:
    def test_basic_schema(self):
        tool = EchoTool()
        schema = tool.to_function_schema()

        assert schema["name"] == "echo"
        assert schema["description"] == "Echoes input back"
        assert "properties" in schema["parameters"]
        assert "text" in schema["parameters"]["properties"]
        assert "required" in schema["parameters"]
        assert "text" in schema["parameters"]["required"]

    def test_enum_in_schema(self):
        tool = EnumTool()
        schema = tool.to_function_schema()
        mode_prop = schema["parameters"]["properties"]["mode"]
        assert mode_prop["enum"] == ["fast", "slow"]

    def test_optional_not_in_required(self):
        tool = EchoTool()
        schema = tool.to_function_schema()
        assert "prefix" not in schema["parameters"].get("required", [])

    def test_no_required_when_all_optional(self):
        tool = FailTool()
        schema = tool.to_function_schema()
        assert "required" not in schema["parameters"]


# =============================================================================
# REGISTRY TESTS
# =============================================================================

class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        tool = EchoTool()
        reg.register(tool)
        assert reg.get("echo") is tool

    def test_get_unknown(self):
        reg = ToolRegistry()
        assert reg.get("nope") is None

    def test_list(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(FailTool())
        assert len(reg.list()) == 2

    def test_names(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(EnumTool())
        assert set(reg.names()) == {"echo", "enum_tool"}

    def test_contains(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        assert "echo" in reg
        assert "nope" not in reg

    def test_len(self):
        reg = ToolRegistry()
        assert len(reg) == 0
        reg.register(EchoTool())
        assert len(reg) == 1

    def test_execute(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        result = reg.execute("echo", text="hello")
        assert result.success is True
        assert result.output == "hello"

    def test_execute_unknown(self):
        reg = ToolRegistry()
        result = reg.execute("nope", x=1)
        assert result.success is False
        assert "not found" in result.error

    def test_unregister(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.unregister("echo")
        assert "echo" not in reg

    def test_get_function_schemas(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        reg.register(EnumTool())
        schemas = reg.get_function_schemas()
        assert len(schemas) == 2
        names = {s["name"] for s in schemas}
        assert names == {"echo", "enum_tool"}

    def test_get_tools_description(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        desc = reg.get_tools_description()
        assert "echo" in desc
        assert "text*" in desc  # Required param marked with *

    def test_summary(self):
        reg = ToolRegistry()
        reg.register(EchoTool())
        s = reg.summary()
        assert s["total_tools"] == 1
        assert "echo" in s["tools"]


# =============================================================================
# WEB SEARCH TOOL TESTS
# =============================================================================

class TestWebSearchTool:
    def test_init(self):
        tool = WebSearchTool()
        assert tool.name == "web_search"
        assert any(p.name == "query" and p.required for p in tool.parameters)

    def test_missing_query(self):
        tool = WebSearchTool()
        result = tool.execute()
        assert result.success is False

    @patch.object(WebSearchTool, '_search_ddgs', return_value=None)
    def test_no_world_context(self, mock_ddgs):
        tool = WebSearchTool()
        result = tool.execute(query="test")
        assert result.success is False
        assert "not available" in result.error or "No search backend" in result.error

    def test_schema(self):
        tool = WebSearchTool()
        schema = tool.to_function_schema()
        assert schema["name"] == "web_search"
        assert "query" in schema["parameters"]["properties"]

    def test_with_ddgs_results(self):
        mock_results = [
            {"title": "Result 1", "url": "http://example.com", "snippet": "A snippet"},
        ]
        with patch.object(WebSearchTool, '_search_ddgs', return_value=mock_results):
            tool = WebSearchTool()
            result = tool.execute(query="test query")
            assert result.success is True
            assert "Result 1" in result.output
            assert result.data["count"] == 1

    def test_empty_results(self):
        with patch.object(WebSearchTool, '_search_ddgs', return_value=[]):
            tool = WebSearchTool()
            result = tool.execute(query="nothing")
            assert result.success is True
            assert "No results" in result.output


# =============================================================================
# WEB FETCH TOOL TESTS
# =============================================================================

class TestWebFetchTool:
    def setup_method(self):
        """Clear web_fetch cache between tests."""
        from core.tools.web_fetch import _cache
        _cache.clear()

    def test_init(self):
        tool = WebFetchTool()
        assert tool.name == "web_fetch"

    def test_invalid_url(self):
        tool = WebFetchTool()
        result = tool.execute(url="not-a-url")
        assert result.success is False
        assert "http" in result.error.lower()

    @patch.object(WebFetchTool, '_do_fetch', return_value=(None, 0, "No fetch backend available"))
    def test_no_world_context(self, mock_fetch):
        tool = WebFetchTool()
        result = tool.execute(url="https://example.com")
        assert result.success is False

    def test_schema(self):
        tool = WebFetchTool()
        schema = tool.to_function_schema()
        assert "url" in schema["parameters"]["properties"]

    @patch('core.tools.web_fetch._looks_js_dependent', return_value=False)
    def test_with_mock_requests(self, mock_js_check):
        html = "<html><title>Test Page</title><body>Hello World</body></html>"
        with patch.object(WebFetchTool, '_do_fetch', return_value=(html, 200, None)):
            tool = WebFetchTool()
            result = tool.execute(url="https://example.com")
            assert result.success is True
            assert "Test Page" in result.output
            assert result.data["title"] == "Test Page"

    def test_failed_fetch(self):
        with patch.object(WebFetchTool, '_do_fetch', return_value=(None, 404, "Not Found")):
            tool = WebFetchTool()
            result = tool.execute(url="https://example.com/404")
            assert result.success is False


# =============================================================================
# SHELL EXEC TOOL TESTS
# =============================================================================

class TestShellExecTool:
    def test_init(self):
        tool = ShellExecTool()
        assert tool.name == "shell_exec"

    def test_echo_command(self):
        tool = ShellExecTool()
        result = tool.execute(command="echo hello")
        assert result.success is True
        assert "hello" in result.output

    def test_failed_command(self):
        tool = ShellExecTool()
        result = tool.execute(command="false")
        assert result.success is False
        assert result.data["return_code"] != 0

    def test_invalid_cwd(self):
        tool = ShellExecTool()
        result = tool.execute(command="ls", cwd="/nonexistent/path")
        assert result.success is False
        assert "not found" in result.error.lower()

    def test_schema(self):
        tool = ShellExecTool()
        schema = tool.to_function_schema()
        assert "command" in schema["parameters"]["properties"]
        assert "command" in schema["parameters"]["required"]

    def test_timeout_cap(self):
        """Timeout should be capped at 300s."""
        tool = ShellExecTool()
        # This shouldn't crash even with high timeout
        result = tool.execute(command="echo fast", timeout=9999)
        assert result.success is True
