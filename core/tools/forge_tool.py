"""
ARIA - Tool Forge
==================

Allows ARIA to create new tools at runtime when it encounters
a capability gap. The hybrid approach:

1. First attempt: solve with code_exec (ephemeral, fast)
2. If recurring need detected: forge a permanent tool

Forged tools are:
- Validated (syntax + safety)
- Persisted to core/tools/forged/
- Auto-loaded on next startup
- Logged in the modification system
- Available to LLM immediately after creation

Compatible with ToolBase architecture — forged tools are
indistinguishable from built-in tools once registered.
"""

import ast
import importlib
import importlib.util
import logging
import os
import re
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.cognition.modification_log import ModificationLogger, generate_modification_id
from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.forge")

# Directory for forged tools
FORGED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "forged")

# Imports that forged tools are allowed to use
# No import or code restrictions.
# ARIA's philosophy: freedom with documentation, not restriction by code.
# Every forged tool is logged in the modification system for full audit trail.


class ForgeToolTool(ToolBase):
    """
    Create new tools dynamically when ARIA lacks a capability.

    The LLM generates tool code, which is validated, persisted,
    and registered — making it available immediately and on
    future startups.
    """

    name = "forge_tool"
    description = (
        "Create a new permanent tool when no existing tool can handle a task. "
        "Use this when you need a capability that doesn't exist yet. "
        "The tool will be validated, saved, and available immediately. "
        "Only forge tools for genuinely recurring needs — use code_exec for one-off tasks."
    )
    parameters = [
        ToolParam(
            name="tool_name",
            type="string",
            description="Unique name for the tool (snake_case, e.g. 'csv_analyzer')",
            required=True,
        ),
        ToolParam(
            name="description",
            type="string",
            description="What the tool does (shown to LLM for selection)",
            required=True,
        ),
        ToolParam(
            name="parameters_spec",
            type="string",
            description=(
                "JSON array of parameters. Each: "
                '{"name": "x", "type": "string", "description": "...", "required": true}'
            ),
            required=True,
        ),
        ToolParam(
            name="implementation",
            type="string",
            description=(
                "Python code for the _execute method body. "
                "Has access to kwargs dict and must return ToolResult(success=True/False, output=...). "
                "Can import from: os, re, json, math, datetime, requests, yaml, bs4, etc. "
                "Do NOT include class definition — only the implementation logic."
            ),
            required=True,
        ),
        ToolParam(
            name="reason",
            type="string",
            description="Why this tool is needed (logged for audit)",
            required=True,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        tool_name = kwargs["tool_name"].strip().lower()
        description = kwargs["description"]
        parameters_spec = kwargs["parameters_spec"]
        implementation = kwargs["implementation"]
        reason = kwargs["reason"]

        # Validate tool name
        if not re.match(r'^[a-z][a-z0-9_]{1,40}$', tool_name):
            return ToolResult(
                success=False,
                error="Tool name must be snake_case, start with letter, 2-41 chars"
            )

        # Check for name collision with existing tools
        registry = self.context.get("tools")
        if registry is not None and tool_name in registry:
            return ToolResult(
                success=False,
                error=f"Tool '{tool_name}' already exists. Choose a different name."
            )

        # Parse parameters
        import json
        try:
            params = json.loads(parameters_spec)
            if not isinstance(params, list):
                raise ValueError("Must be a JSON array")
        except (json.JSONDecodeError, ValueError) as e:
            return ToolResult(success=False, error=f"Invalid parameters_spec JSON: {e}")

        # Build the full tool source code
        source = _build_tool_source(tool_name, description, params, implementation)

        # Validate syntax
        try:
            ast.parse(source)
        except SyntaxError as e:
            return ToolResult(
                success=False,
                error=f"Generated code has syntax error on line {e.lineno}: {e.msg}"
            )

        # Ensure forged directory exists
        os.makedirs(FORGED_DIR, exist_ok=True)
        init_path = os.path.join(FORGED_DIR, "__init__.py")
        if not os.path.exists(init_path):
            with open(init_path, "w") as f:
                f.write("# Auto-generated: forged tools directory\n")

        # Write tool file
        file_path = os.path.join(FORGED_DIR, f"{tool_name}.py")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(source)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write tool file: {e}")

        # Load and register the tool
        try:
            tool_instance = _load_forged_tool(file_path, tool_name, self.context)
            if registry is not None:
                registry.register(tool_instance)
                logger.info(f"Forged tool registered: {tool_name}")
        except Exception as e:
            # Clean up on failure
            os.remove(file_path)
            return ToolResult(
                success=False,
                error=f"Tool loaded but failed to register: {e}"
            )

        # Log via self-modification system if available
        self._log_creation(tool_name, source, reason)

        return ToolResult(
            success=True,
            output=(
                f"Tool '{tool_name}' forged and registered.\n"
                f"  File: core/tools/forged/{tool_name}.py\n"
                f"  Parameters: {', '.join(p['name'] for p in params)}\n"
                f"  Reason: {reason}\n\n"
                f"The tool is available immediately. It will auto-load on next startup."
            ),
            data={
                "tool_name": tool_name,
                "file_path": f"core/tools/forged/{tool_name}.py",
                "parameters": params,
            },
        )

    def _log_creation(self, tool_name: str, source: str, reason: str, log_path: str = "data/modification_log.yaml"):
        """Log tool creation without depending on SelfModifier."""
        try:
            ModificationLogger(log_path).record_dict(
                {
                    "id": generate_modification_id(),
                    "timestamp": datetime.now().isoformat(),
                    "target_file": f"core/tools/forged/{tool_name}.py",
                    "modification_type": "forge",
                    "original_content_hash": "",
                    "new_content_hash": "",
                    "reason": f"[forge_tool] {reason}",
                    "initiated_by": "aria",
                    "success": True,
                    "error_message": None,
                },
                original_content=None,
                new_content=source,
            )
        except Exception as e:
            logger.debug(f"Could not log to modification system: {e}")


class ListForgedToolsTool(ToolBase):
    """List all forged tools and their status."""

    name = "list_forged_tools"
    description = "List all dynamically created tools in the forge directory"
    parameters = []

    def _execute(self, **kwargs) -> ToolResult:
        if not os.path.isdir(FORGED_DIR):
            return ToolResult(success=True, output="No forged tools yet.")

        tools = []
        for f in sorted(os.listdir(FORGED_DIR)):
            if f.endswith(".py") and f != "__init__.py":
                name = f[:-3]
                path = os.path.join(FORGED_DIR, f)
                size = os.path.getsize(path)
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
                registry = self.context.get("tools")
                status = "active" if registry and name in registry else "unloaded"
                tools.append(f"  {name:30s} {status:10s} {size:>6d}B  {mtime:%Y-%m-%d %H:%M}")

        if not tools:
            return ToolResult(success=True, output="No forged tools yet.")

        header = f"  {'Name':30s} {'Status':10s} {'Size':>7s}  {'Created'}"
        return ToolResult(
            success=True,
            output=f"Forged tools ({len(tools)}):\n{header}\n" + "\n".join(tools),
            data={"count": len(tools)},
        )


# =============================================================================
# Helper functions
# =============================================================================

def _build_tool_source(
    tool_name: str,
    description: str,
    params: list,
    implementation: str,
) -> str:
    """Build a complete Python tool file from components."""

    # Build ToolParam definitions
    param_lines = []
    for p in params:
        parts = [f'name="{p["name"]}"']
        if p.get("type"):
            parts.append(f'type="{p["type"]}"')
        if p.get("description"):
            parts.append(f'description="{p["description"]}"')
        if p.get("required"):
            parts.append("required=True")
        if "default" in p and p["default"] is not None:
            parts.append(f'default={repr(p["default"])}')
        if p.get("enum"):
            parts.append(f'enum={p["enum"]}')
        param_lines.append(f"        ToolParam({', '.join(parts)}),")

    params_block = "\n".join(param_lines) if param_lines else "        # No parameters"

    # Convert class name
    class_name = "".join(w.capitalize() for w in tool_name.split("_")) + "Tool"

    # Indent implementation
    impl_lines = implementation.strip().split("\n")
    indented_impl = "\n".join("        " + line if line.strip() else "" for line in impl_lines)

    return f'''"""
Forged Tool: {tool_name}
Created: {datetime.now().strftime("%Y-%m-%d %H:%M")}

Auto-generated by ARIA's Tool Forge.
"""

from core.tools.tool_base import ToolBase, ToolParam, ToolResult


class {class_name}(ToolBase):
    """{description}"""

    name = "{tool_name}"
    description = "{description}"
    parameters = [
{params_block}
    ]

    def _execute(self, **kwargs) -> ToolResult:
{indented_impl}
'''


def _load_forged_tool(
    file_path: str,
    tool_name: str,
    context: dict,
) -> ToolBase:
    """Dynamically load a forged tool from its Python file."""
    module_name = f"core.tools.forged.{tool_name}"

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"Could not create import spec for forged tool: {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Find the ToolBase subclass
    tool_class = None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (isinstance(attr, type)
                and issubclass(attr, ToolBase)
                and attr is not ToolBase
                and hasattr(attr, "name")
                and attr.name == tool_name):
            tool_class = attr
            break

    if not tool_class:
        raise ValueError(f"No ToolBase subclass with name='{tool_name}' found in {file_path}")

    return tool_class(context=context)


def load_all_forged_tools(
    context: dict,
    registry=None,
) -> List[ToolBase]:
    """
    Load all forged tools from the forged/ directory.
    Called at ARIA startup to restore previously forged tools.
    """
    if not os.path.isdir(FORGED_DIR):
        return []

    loaded = []
    for filename in sorted(os.listdir(FORGED_DIR)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue

        tool_name = filename[:-3]
        file_path = os.path.join(FORGED_DIR, filename)

        try:
            tool = _load_forged_tool(file_path, tool_name, context)
            loaded.append(tool)
            if registry is not None:
                registry.register(tool)
            logger.info(f"Loaded forged tool: {tool_name}")
        except Exception as e:
            logger.warning(f"Failed to load forged tool {tool_name}: {e}")

    if loaded:
        logger.info(f"Loaded {len(loaded)} forged tool(s)")

    return loaded
