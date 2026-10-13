"""
Prompt Skills - Lightweight skills powered by LLM prompts.

These skills are essentially prompt templates: they do minimal pre-processing,
then delegate to the LLM with a specialized prompt. Unlike orchestration skills
(which chain multiple tools in specific sequences), prompt skills add value
through expert instructions, not through code logic.

The LLM already has access to all tools via function calling. These skills
provide better prompts for specific domains where a generic LLM response
would be suboptimal.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class PromptSkill(SkillBase):
    """
    A skill defined primarily by a prompt template.

    Subclasses only need to define:
        name, description, prompt_template

    Optionally:
        pre_tool: tool to call before LLM (e.g., web_search for weather)
        pre_tool_kwargs: function(query) → dict of tool kwargs
        max_tokens: LLM response length
    """

    prompt_template: str = ""
    pre_tool: str = ""
    max_tokens: int = 800

    def pre_tool_kwargs(self, query: str) -> dict:
        """Build kwargs for the pre-tool call. Override in subclass."""
        return {}

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required")

        # Optional pre-tool execution (e.g., web search before formatting)
        tool_output = ""
        if self.pre_tool and not ctx.tools:
            return SkillResult(success=False, error="No tools available")
        if self.pre_tool and ctx.tools:
            kwargs = self.pre_tool_kwargs(query)
            if kwargs:
                result = ctx.tools.execute(self.pre_tool, **kwargs)
                if result.success:
                    tool_output = result.output

        # Build the prompt
        prompt = self.prompt_template.format(
            query=query,
            tool_output=tool_output[:4000] if tool_output else "",
        )

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"source": "prompt_skill"},
                )
        except Exception as e:
            return SkillResult(success=False, error=str(e))

        return SkillResult(success=False, error="LLM returned empty response")


# =============================================================================
# Prompt skill definitions
# =============================================================================

class WeatherSkill(PromptSkill):
    name = "weather"
    description = "Get current weather and forecast for a location"
    requires_tools = [Tools.WEB_SEARCH]
    pre_tool = Tools.WEB_SEARCH
    max_tokens = 300

    def pre_tool_kwargs(self, query: str):
        location = re.sub(
            r'\b(weather|forecast|clima|tiempo|pronóstico|in|en|for|the|what|how|is|qué|hace|de)\b',
            '', query, flags=re.IGNORECASE,
        ).strip().strip('?,!\'"') or "current location"
        return {"query": f"weather {location} today forecast", "num_results": 3}

    prompt_template = """Based on these search results, create a concise weather summary.

Search results:
{tool_output}

User asked: {query}

Format:
- Current temperature and conditions (1 line)
- Today's high/low (1 line)
- Brief forecast for next 2-3 days (2-3 lines)
- Any alerts or notable conditions

    Keep it concise and useful. If data is unclear, say what you can determine."""
