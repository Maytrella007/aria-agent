"""
ARIA - Tool Base
=================

Abstract base class for all ARIA tools.
Inspired by OpenClaw's tool architecture, implemented natively in Python.

Each tool has:
- A name and description (for registry and LLM function calling)
- Typed parameters with validation
- Standardized result format
- Automatic schema generation for LLM function calling

Usage:
    class MyTool(ToolBase):
        name = "my_tool"
        description = "Does something useful"
        parameters = [
            ToolParam(name="query", type="string", description="Search query", required=True),
        ]

        def _execute(self, **kwargs) -> ToolResult:
            return ToolResult(success=True, output="done")
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aria.tools")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ToolParam:
    """Definition of a tool parameter."""
    name: str
    type: str = "string"  # "string", "number", "integer", "boolean", "array"
    description: str = ""
    required: bool = False
    default: Any = None
    enum: Optional[List[str]] = None


@dataclass
class ToolResult:
    """Standardized result from any tool execution."""
    success: bool
    output: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"Error: {self.error or 'Unknown error'}"


# =============================================================================
# TOOL BASE
# =============================================================================

class ToolBase(ABC):
    """
    Abstract base class for all ARIA tools.

    Subclasses must define:
        name: str           — unique tool identifier
        description: str    — what the tool does (shown to LLM)
        parameters: list    — list of ToolParam definitions

    Subclasses must implement:
        _execute(**kwargs) -> ToolResult
    """

    name: str = "unnamed_tool"
    description: str = "No description"
    parameters: List[ToolParam] = []

    def __init__(self, context: Optional[Dict[str, Any]] = None):
        """
        Args:
            context: Shared context dict (ARIA instance, config, etc.)
        """
        self.context = context or {}

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with validation, timing, and error handling."""
        start = time.time()

        # Validate parameters
        validation_error = self._validate(kwargs)
        if validation_error:
            return ToolResult(
                success=False,
                error=validation_error,
                metadata={"tool": self.name},
            )

        # Apply defaults
        for param in self.parameters:
            if param.name not in kwargs and param.default is not None:
                kwargs[param.name] = param.default

        # Execute
        try:
            result = self._execute(**kwargs)
        except Exception as e:
            logger.error(f"Tool {self.name} failed: {e}")
            result = ToolResult(
                success=False,
                error=str(e),
            )

        # Add metadata
        elapsed_ms = round((time.time() - start) * 1000, 2)
        result.metadata["tool"] = self.name
        result.metadata["elapsed_ms"] = elapsed_ms

        if result.success:
            logger.debug(f"Tool {self.name} OK in {elapsed_ms}ms")
        else:
            logger.warning(f"Tool {self.name} failed in {elapsed_ms}ms: {result.error}")

        return result

    def to_function_schema(self) -> dict:
        """
        Generate OpenAI-compatible function schema for LLM function calling.

        Returns a dict like:
        {
            "name": "web_search",
            "description": "Search the web for information",
            "parameters": {
                "type": "object",
                "properties": { ... },
                "required": [...]
            }
        }
        """
        properties = {}
        required = []

        for param in self.parameters:
            prop = {"description": param.description}

            # Map type
            if param.type == "array":
                prop["type"] = "array"
                prop["items"] = {"type": "string"}
            else:
                prop["type"] = param.type

            # Enum
            if param.enum:
                prop["enum"] = param.enum

            properties[param.name] = prop

            if param.required:
                required.append(param.name)

        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": properties,
            },
        }

        if required:
            schema["parameters"]["required"] = required

        return schema

    # -------------------------------------------------------------------------
    # Abstract
    # -------------------------------------------------------------------------

    @abstractmethod
    def _execute(self, **kwargs) -> ToolResult:
        """Implement the actual tool logic. Override in subclass."""
        pass

    # -------------------------------------------------------------------------
    # Validation
    # -------------------------------------------------------------------------

    def _validate(self, kwargs: dict) -> Optional[str]:
        """Validate input parameters. Returns error message or None."""
        for param in self.parameters:
            if param.required and param.name not in kwargs:
                return f"Missing required parameter: {param.name}"

            if param.name in kwargs and param.enum:
                if kwargs[param.name] not in param.enum:
                    return (
                        f"Invalid value for {param.name}: {kwargs[param.name]}. "
                        f"Must be one of: {param.enum}"
                    )

        return None
