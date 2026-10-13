"""
ARIA - Skill Base
==================

Abstract base class for all ARIA skills.

Skills are high-level workflows that combine multiple tools + LLM prompts
into efficient, pre-packaged operations. Unlike raw tool calls (which the LLM
discovers at runtime), skills know the optimal workflow upfront.

    Tools:  Low-level primitives (web_search, shell_exec, calculator)
    Skills: High-level workflows (research, daily_brief, summarize)

Architecture:
    SkillBase     — abstract class each skill implements
    SkillResult   — standardized output
    SkillContext   — shared context (tools, llm, memory, etc.)
    SkillRegistry — register, match, list skills

Usage:
    from core.tools.tool_names import Tools

    class WeatherSkill(SkillBase):
        name = "weather"
        description = "Get current weather and forecast for a location"
        requires_tools = [Tools.WEB_SEARCH]

        def _execute(self, query, ctx):
            result = ctx.tools.execute(Tools.WEB_SEARCH, query=f"weather {query}")
            return SkillResult(success=True, output=result.output)
"""

import json
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("aria.skills")


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SkillResult:
    """Standardized result from a skill execution."""
    success: bool
    output: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    skill_name: str = ""
    elapsed_ms: float = 0

    def __str__(self) -> str:
        if self.success:
            return self.output
        return f"Skill error: {self.error or 'Unknown error'}"


@dataclass
class SkillContext:
    """Shared context passed to every skill execution.

    Provides access to ARIA's subsystems without tight coupling.
    """
    tools: Any = None          # ToolRegistry
    llm: Any = None            # LLMProvider
    memory: Any = None         # ExperientialMemorySystem
    facts: Any = None          # FactStore (if available)
    config: Dict = field(default_factory=dict)
    user: str = ""             # Current user name
    conversation_history: List = field(default_factory=list)


# =============================================================================
# SKILL BASE
# =============================================================================

class SkillBase(ABC):
    """
    Abstract base class for all ARIA skills.

    Subclasses must define:
        name: str                — unique skill identifier
        description: str         — what the skill does (used by LLM to select)

    Subclasses may define:
        requires_tools: list     — tool names this skill needs (validated at execute)

    Subclasses must implement:
        _execute(query, ctx) -> SkillResult

    Skill selection is 100% LLM-based: the LLM reads all skill descriptions
    and decides which one (if any) best handles the user's request.
    No regex triggers — semantic understanding only.
    """

    name: str = "unnamed_skill"
    description: str = "No description"
    requires_tools: List[str] = []

    def execute(self, query: str, ctx: SkillContext) -> SkillResult:
        """Execute the skill with timing and error handling."""
        start = time.time()

        # Validate required tools are available (only against real ToolRegistry)
        if self.requires_tools and ctx.tools is not None:
            from core.tools.registry import ToolRegistry
            if isinstance(ctx.tools, ToolRegistry):
                missing = [t for t in self.requires_tools if t not in ctx.tools]
                if missing:
                    return SkillResult(
                        success=False,
                        error=f"Missing required tools: {', '.join(missing)}",
                        skill_name=self.name,
                    )

        try:
            result = self._execute(query, ctx)
        except Exception as e:
            logger.error(f"Skill {self.name} failed: {e}")
            result = SkillResult(
                success=False,
                error=str(e),
            )

        elapsed_ms = round((time.time() - start) * 1000, 2)
        result.skill_name = self.name
        result.elapsed_ms = elapsed_ms

        if result.success:
            logger.debug(f"Skill {self.name} OK in {elapsed_ms}ms")
        else:
            logger.warning(f"Skill {self.name} failed in {elapsed_ms}ms: {result.error}")

        return result

    @abstractmethod
    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        """Implement the skill workflow. Override in subclass."""
        pass


# =============================================================================
# SKILL REGISTRY
# =============================================================================

class SkillRegistry:
    """
    Central registry for all skills.

    Skill selection is 100% LLM-based (like OpenClaw): the LLM reads all
    skill descriptions and decides which one best handles the user's request.
    No regex triggers — pure semantic understanding.
    """

    # Skill catalog prompt — built once, cached until skills change
    _catalog_cache: Optional[str] = None

    def __init__(self):
        self._skills: Dict[str, SkillBase] = {}

    def register(self, skill: SkillBase):
        """Register a skill."""
        self._skills[skill.name] = skill
        self._catalog_cache = None  # invalidate
        logger.debug(f"Skill registered: {skill.name}")

    def unregister(self, name: str):
        """Remove a skill."""
        self._skills.pop(name, None)
        self._catalog_cache = None

    def get(self, name: str) -> Optional[SkillBase]:
        """Get a skill by name."""
        return self._skills.get(name)

    # -------------------------------------------------------------------------
    # LLM-based skill selection
    # -------------------------------------------------------------------------

    def match(self, text: str, llm=None,
              conversation_history: Optional[List] = None) -> Optional[Tuple[SkillBase, str]]:
        """Select the best skill for user input using LLM classification.

        The LLM sees all skill names + descriptions and decides:
        - Which skill (if any) best handles this request
        - What query/arguments to extract for that skill

        Returns (skill, extracted_query) or None if no skill applies.
        Requires LLM — returns None without one.
        """
        if not llm or not self._skills:
            return None

        prompt = self._build_classifier_prompt(text, conversation_history)

        try:
            response = llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=80,
            )
            if not response or not response.content:
                return None

            return self._parse_response(response.content, text)

        except Exception as e:
            logger.warning(f"Skill classification failed: {e}")
            return None

    def _build_classifier_prompt(self, text: str,
                                 conversation_history: Optional[List] = None) -> str:
        """Build the skill classification prompt."""
        # Cache the skill catalog (invalidated on register/unregister)
        if self._catalog_cache is None:
            lines = []
            for skill in self._skills.values():
                lines.append(f"- {skill.name}: {skill.description}")
            self._catalog_cache = "\n".join(lines)

        context = ""
        if conversation_history:
            recent = conversation_history[-3:]
            context_lines = []
            for msg in recent:
                role = "User" if msg['role'] == 'user' else "ARIA"
                context_lines.append(f"{role}: {msg['content'][:100]}")
            context = "\nRecent conversation:\n" + "\n".join(context_lines)

        return f"""Classify the user's message into one of these skills, or "none" if it's regular conversation.

User message: "{text}"
{context}

Available skills:
{self._catalog_cache}

RULES:
- If exactly one skill clearly applies → select it
- If multiple could apply → choose the most specific one
- If none clearly apply (greeting, small talk, general question) → "none"
- The user may write in ANY language — understand the intent regardless
- Extract the relevant query/arguments for the chosen skill

Respond with ONLY a JSON object, no other text:
{{"skill": "skill_name or none", "query": "extracted query for the skill"}}"""

    def _parse_response(self, content: str,
                        original_text: str) -> Optional[Tuple[SkillBase, str]]:
        """Parse the LLM's JSON response into a (skill, query) tuple."""
        content = content.strip()

        # Extract JSON
        json_match = re.search(r'\{[^}]+\}', content)
        if not json_match:
            return None

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None

        skill_name = data.get("skill", "none")
        if not skill_name or skill_name == "none":
            return None

        skill = self._skills.get(skill_name)
        if not skill:
            # Fuzzy match (LLM might use slightly different name)
            for name, s in self._skills.items():
                if name.replace("_", "") == skill_name.replace("_", "").replace("-", ""):
                    skill = s
                    break
            if not skill:
                logger.debug(f"LLM suggested unknown skill: {skill_name}")
                return None

        query = data.get("query", "").strip() or original_text
        logger.info(f"Skill selected: {skill.name} (query: {query[:50]})")
        return (skill, query)

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    def execute(self, name: str, query: str, ctx: SkillContext) -> SkillResult:
        """Execute a skill by name."""
        skill = self._skills.get(name)
        if not skill:
            return SkillResult(
                success=False,
                error=f"Skill '{name}' not found",
            )
        return skill.execute(query, ctx)

    # -------------------------------------------------------------------------
    # Introspection
    # -------------------------------------------------------------------------

    def list(self) -> List[SkillBase]:
        """Return all registered skills."""
        return list(self._skills.values())

    def names(self) -> List[str]:
        """Return all skill names."""
        return list(self._skills.keys())

    def __len__(self):
        return len(self._skills)

    def __contains__(self, name: str):
        return name in self._skills

    def get_descriptions(self) -> str:
        """Generate a formatted description of all skills for display."""
        if not self._skills:
            return "No skills registered."

        lines = ["Available skills:"]
        for skill in self._skills.values():
            lines.append(f"  {skill.name:20s} {skill.description}")
        return "\n".join(lines)

    def get_prompt_section(self) -> str:
        """Generate skill descriptions for the LLM system prompt."""
        if not self._skills:
            return ""

        lines = [
            "=== SKILLS (pre-built workflows — faster than raw tool calls) ===",
            "Before replying, scan the skill list below.",
            "If exactly one skill clearly applies to the user's request, use it.",
            "If multiple could apply, choose the most specific one.",
            "If none clearly apply, do not use any skill.",
            "",
        ]
        for skill in self._skills.values():
            lines.append(f"- {skill.name}: {skill.description}")

        return "\n".join(lines)
