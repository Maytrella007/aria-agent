"""
ARIA - Tool Registry
=====================

Central registry for discovering, managing, and executing tools.
Inspired by OpenClaw's tool catalog pattern.

Usage:
    registry = ToolRegistry()
    registry.register(WebSearchTool(context))
    registry.register(WebFetchTool(context))

    # Execute by name
    result = registry.execute("web_search", query="quantum computing")

    # Get all schemas for LLM function calling
    schemas = registry.get_function_schemas()

    # List available tools
    for tool in registry.list():
        print(f"{tool.name}: {tool.description}")
"""

import logging
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolResult

logger = logging.getLogger("aria.tools")


class ToolRegistry:
    """
    Central tool registry.

    Manages tool registration, discovery, and execution.
    Provides function schemas for LLM function calling.
    """

    def __init__(self):
        self._tools: Dict[str, ToolBase] = {}

    # -------------------------------------------------------------------------
    # Registration
    # -------------------------------------------------------------------------

    def register(self, tool: ToolBase):
        """Register a tool. Overwrites if name already exists."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting tool: {tool.name}")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name}")

    def unregister(self, name: str):
        """Remove a tool from the registry."""
        if name in self._tools:
            del self._tools[name]
            logger.debug(f"Unregistered tool: {name}")

    # -------------------------------------------------------------------------
    # Discovery
    # -------------------------------------------------------------------------

    def get(self, name: str) -> Optional[ToolBase]:
        """Get a tool by name."""
        return self._tools.get(name)

    def list(self) -> List[ToolBase]:
        """List all registered tools."""
        return list(self._tools.values())

    def names(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    def execute(self, name: str, **kwargs) -> ToolResult:
        """Execute a tool by name with given arguments."""
        tool = self._tools.get(name)
        if not tool:
            return ToolResult(
                success=False,
                error=f"Tool not found: {name}",
                metadata={"tool": name},
            )
        return tool.execute(**kwargs)

    # -------------------------------------------------------------------------
    # LLM Function Calling
    # -------------------------------------------------------------------------

    def get_function_schemas(self) -> List[dict]:
        """
        Get OpenAI-compatible function schemas for all registered tools.
        Used to pass available tools to the LLM for function calling.
        """
        return [tool.to_function_schema() for tool in self._tools.values()]

    def get_tools_description(self) -> str:
        """
        Get a human-readable description of all tools.
        Useful for including in system prompts.
        """
        lines = []
        for tool in self._tools.values():
            params = ", ".join(
                f"{p.name}{'*' if p.required else ''}"
                for p in tool.parameters
            )
            lines.append(f"- {tool.name}({params}): {tool.description}")
        return "\n".join(lines)

    def summary(self) -> dict:
        """Return registry summary stats."""
        return {
            "total_tools": len(self._tools),
            "tools": {
                name: tool.description
                for name, tool in self._tools.items()
            },
        }
