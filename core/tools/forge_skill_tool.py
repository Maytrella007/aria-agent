"""
ARIA - Skill Forge
===================

Allows ARIA to create new prompt-based skills at runtime.
Writes a YAML file to core/skills/ and registers it immediately.

No restrictions — ARIA decides what skills it needs.
Every creation is logged for audit.
"""

import logging
import os
import yaml
from datetime import datetime
from typing import Any, Dict, Optional

from core.cognition.modification_log import ModificationLogger, generate_modification_id
from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.forge_skill")

SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "skills",
)


class ForgeSkillTool(ToolBase):
    """Create new prompt-based skills at runtime."""

    name = "forge_skill"
    description = (
        "Create a new prompt-based skill when no existing skill handles a task well. "
        "The skill is defined by a prompt template and saved as YAML. "
        "Available immediately and on future startups. "
        "Use for recurring prompt patterns — for one-off tasks, just answer directly."
    )
    parameters = [
        ToolParam(
            name="skill_name",
            type="string",
            description="Unique name (snake_case, e.g. 'changelog_writer')",
            required=True,
        ),
        ToolParam(
            name="description",
            type="string",
            description="What the skill does (LLM reads this to decide when to use it)",
            required=True,
        ),
        ToolParam(
            name="prompt_template",
            type="string",
            description="Prompt template. Use {query} for user input, {tool_output} for pre-tool results",
            required=True,
        ),
        ToolParam(
            name="system_prompt",
            type="string",
            description="System prompt to set the LLM persona/expertise (optional)",
            required=False,
            default="",
        ),
        ToolParam(
            name="pre_tool",
            type="string",
            description="Tool to run before LLM call for data gathering, e.g. 'web_search' (optional)",
            required=False,
            default="",
        ),
        ToolParam(
            name="pre_tool_query",
            type="string",
            description="Query template for pre-tool. Use {query} for user input (optional)",
            required=False,
            default="{query}",
        ),
        ToolParam(
            name="max_tokens",
            type="integer",
            description="Max LLM response length (default: 800)",
            required=False,
            default=800,
        ),
        ToolParam(
            name="examples_json",
            type="string",
            description='Few-shot examples as JSON: [{"input": "...", "output": "..."}] (optional)',
            required=False,
            default="",
        ),
        ToolParam(
            name="reason",
            type="string",
            description="Why this skill is needed (logged for audit)",
            required=True,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        import re
        import json

        skill_name = kwargs["skill_name"].strip().lower()
        description = kwargs["description"]
        prompt_template = kwargs["prompt_template"]
        system_prompt = kwargs.get("system_prompt", "")
        pre_tool = kwargs.get("pre_tool", "")
        pre_tool_query = kwargs.get("pre_tool_query", "{query}")
        max_tokens = kwargs.get("max_tokens", 800)
        examples_json = kwargs.get("examples_json", "")
        reason = kwargs["reason"]

        # Validate name
        if not re.match(r'^[a-z][a-z0-9_]{1,40}$', skill_name):
            return ToolResult(
                success=False,
                error="Skill name must be snake_case, start with letter, 2-41 chars"
            )

        # Check for duplicate
        skill_registry = self.context.get("skill_registry")
        if skill_registry is not None and skill_name in skill_registry:
            return ToolResult(
                success=False,
                error=f"Skill '{skill_name}' already exists. Choose a different name."
            )

        # Parse examples
        examples = []
        if examples_json:
            try:
                examples = json.loads(examples_json)
                if not isinstance(examples, list):
                    raise ValueError("Must be a JSON array")
            except (json.JSONDecodeError, ValueError) as e:
                return ToolResult(success=False, error=f"Invalid examples_json: {e}")

        # Build YAML content
        skill_data = {"name": skill_name, "description": description}
        if system_prompt:
            skill_data["system"] = system_prompt
        skill_data["prompt_template"] = prompt_template
        if pre_tool:
            skill_data["pre_tool"] = pre_tool
            skill_data["pre_tool_query"] = pre_tool_query
            skill_data["requires_tools"] = [pre_tool]
        skill_data["max_tokens"] = max_tokens
        if examples:
            skill_data["examples"] = examples

        # Write YAML file
        file_path = os.path.join(SKILLS_DIR, f"{skill_name}.yaml")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(skill_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            return ToolResult(success=False, error=f"Failed to write skill file: {e}")

        # Load and register immediately
        try:
            from core.skills.prompt_skill_loader import DynamicPromptSkill
            skill_data["_source_file"] = file_path
            skill = DynamicPromptSkill(skill_data)
            if skill_registry is not None:
                skill_registry.register(skill)
                logger.info(f"Forged skill registered: {skill_name}")
        except Exception as e:
            os.remove(file_path)
            return ToolResult(success=False, error=f"Failed to register skill: {e}")

        # Log creation
        self._log_creation(skill_name, file_path, reason)

        return ToolResult(
            success=True,
            output=(
                f"Skill '{skill_name}' forged and registered.\n"
                f"  File: core/skills/{skill_name}.yaml\n"
                f"  Description: {description}\n"
                f"  Reason: {reason}\n\n"
                f"The skill is available immediately. It will auto-load on next startup."
            ),
            data={
                "skill_name": skill_name,
                "file_path": f"core/skills/{skill_name}.yaml",
            },
        )

    def _log_creation(self, skill_name: str, file_path: str, reason: str, log_path: str = "data/modification_log.yaml"):
        """Log skill creation without depending on SelfModifier."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                new_content = f.read()

            ModificationLogger(log_path).record_dict(
                {
                    "id": generate_modification_id(),
                    "timestamp": datetime.now().isoformat(),
                    "target_file": f"core/skills/{skill_name}.yaml",
                    "modification_type": "forge_skill",
                    "original_content_hash": "",
                    "new_content_hash": "",
                    "reason": f"[forge_skill] {reason}",
                    "initiated_by": "aria",
                    "success": True,
                    "error_message": None,
                },
                original_content=None,
                new_content=new_content,
            )
        except Exception as e:
            logger.debug(f"Could not log to modification system: {e}")
