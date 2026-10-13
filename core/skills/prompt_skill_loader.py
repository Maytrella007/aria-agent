"""
Prompt Skill Loader - Load skills from YAML files.

Enables prompt-based skills compatible with the pattern used by
modern AI agents (Claude Code, Custom GPTs, OpenClaw, etc.):
skills defined by instruction files rather than Python code.

Each YAML file in the skills directory becomes a registered skill.
Hot-reload supported via reload().

File format:
    name: translate
    description: "Translate text between languages"
    prompt_template: |
      Translate the following to {target_language}: {query}
    # Optional fields:
    pre_tool: web_search
    pre_tool_query: "{query} translation"
    max_tokens: 1000
    system: "You are a professional translator."
    examples:
      - input: "translate hello to Spanish"
        output: "hola"
"""

import logging
import os
import yaml
from typing import Dict, List, Optional

from .base import SkillBase, SkillResult, SkillContext, SkillRegistry

logger = logging.getLogger("aria.skills.loader")


class DynamicPromptSkill(SkillBase):
    """
    A skill created dynamically from a YAML definition.

    Compatible with the prompt-based skill pattern used by other agents:
    the skill's behavior is defined entirely by its prompt template,
    with optional pre-tool execution for data gathering.
    """

    def __init__(self, config: dict):
        self.name = config["name"]
        self.description = config.get("description", "")
        self.prompt_template = config.get("prompt_template", "{query}")
        self.system_prompt = config.get("system", "")
        self.pre_tool = config.get("pre_tool", "")
        self.pre_tool_query = config.get("pre_tool_query", "{query}")
        self.max_tokens = config.get("max_tokens", 800)
        self.requires_tools = config.get("requires_tools", [])
        self.examples = config.get("examples", [])
        self._source_file = config.get("_source_file", "")

        # If pre_tool is set, add it to requires_tools
        if self.pre_tool and self.pre_tool not in self.requires_tools:
            self.requires_tools.append(self.pre_tool)

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for prompt skill")

        # Optional pre-tool execution
        tool_output = ""
        if self.pre_tool and ctx.tools:
            try:
                tool_query = self.pre_tool_query.format(query=query)
                result = ctx.tools.execute(self.pre_tool, query=tool_query)
                if result.success:
                    tool_output = result.output[:4000]
            except Exception as e:
                logger.debug(f"Pre-tool {self.pre_tool} failed: {e}")

        # Build prompt from template
        try:
            prompt = self.prompt_template.format(
                query=query,
                tool_output=tool_output,
            )
        except KeyError:
            # Template has extra placeholders — pass query as-is
            prompt = self.prompt_template.replace("{query}", query)
            prompt = prompt.replace("{tool_output}", tool_output)

        # Build messages
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        # Add examples as few-shot if present
        for ex in self.examples:
            if ex.get("input"):
                messages.append({"role": "user", "content": ex["input"]})
            if ex.get("output"):
                messages.append({"role": "assistant", "content": ex["output"]})

        messages.append({"role": "user", "content": prompt})

        try:
            response = ctx.llm.chat(
                messages=messages,
                max_tokens=self.max_tokens,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"source": "prompt_skill", "skill_file": self._source_file},
                )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

        return SkillResult(success=False, error="LLM returned empty response")

    def __repr__(self):
        return f"DynamicPromptSkill({self.name!r})"


def load_prompt_skills(
    skills_dir: str,
    registry: Optional[SkillRegistry] = None,
) -> List[DynamicPromptSkill]:
    """
    Load all YAML skill definitions from a directory.

    Args:
        skills_dir: Path to directory containing .yaml/.yml skill files
        registry: If provided, register loaded skills directly

    Returns:
        List of DynamicPromptSkill instances
    """
    if not os.path.isdir(skills_dir):
        logger.debug(f"Skills directory not found: {skills_dir}")
        return []

    loaded = []
    for filename in sorted(os.listdir(skills_dir)):
        if not filename.endswith((".yaml", ".yml")):
            continue

        filepath = os.path.join(skills_dir, filename)
        try:
            skill = _load_skill_file(filepath)
            if skill:
                loaded.append(skill)
                if registry:
                    registry.register(skill)
                logger.info(f"Loaded prompt skill: {skill.name} ({filename})")
        except Exception as e:
            logger.warning(f"Failed to load skill from {filename}: {e}")

    if loaded:
        logger.info(f"Loaded {len(loaded)} prompt skill(s) from {skills_dir}")

    return loaded


def _load_skill_file(filepath: str) -> Optional[DynamicPromptSkill]:
    """Load a single skill YAML file."""
    with open(filepath, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not config or not isinstance(config, dict):
        logger.warning(f"Empty or invalid skill file: {filepath}")
        return None

    if "name" not in config:
        # Use filename without extension as name
        config["name"] = os.path.splitext(os.path.basename(filepath))[0]

    if "description" not in config:
        logger.warning(f"Skill {config['name']} has no description — will be hard for LLM to select")

    config["_source_file"] = filepath
    return DynamicPromptSkill(config)


def reload_prompt_skills(
    skills_dir: str,
    registry: SkillRegistry,
    previous: Optional[List[DynamicPromptSkill]] = None,
) -> List[DynamicPromptSkill]:
    """
    Reload prompt skills, unregistering old ones first.

    Args:
        skills_dir: Path to skills directory
        registry: SkillRegistry to update
        previous: Previously loaded skills to unregister

    Returns:
        Newly loaded skills
    """
    # Unregister old dynamic skills
    if previous:
        for skill in previous:
            registry.unregister(skill.name)
        logger.info(f"Unregistered {len(previous)} old prompt skill(s)")

    return load_prompt_skills(skills_dir, registry)
