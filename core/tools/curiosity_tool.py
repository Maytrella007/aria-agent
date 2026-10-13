"""
ARIA - Curiosity Tool
======================

LLM-callable interface to the curiosity engine.
Allows the agent to research topics on-demand when the user asks
"learn about X", "investigate Y", "I want you to research Z".

Also provides status, interest management, and exploration logs.
"""

import logging
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.curiosity")


class CuriosityTool(ToolBase):
    """Research topics on-demand and manage curiosity interests."""

    name = "curiosity"
    description = (
        "Research and learn about topics from the web. "
        "Use 'explore' to investigate a topic NOW — searches the web, reads pages, "
        "and saves knowledge for future reference. "
        "Use 'add_interest' to add a topic ARIA will keep learning about autonomously. "
        "Use 'status' to see what ARIA has been learning. "
        "Use 'log' to see today's exploration history. "
        "WHEN THE USER SAYS: 'learn about X', 'investigate X', 'research X', "
        "'I want you to know about X', 'explore X' → use action='explore' with that topic."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: explore (research now), add_interest, remove_interest, status, log",
            required=True,
            enum=["explore", "add_interest", "remove_interest", "status", "log"],
        ),
        ToolParam(
            name="topic",
            type="string",
            description="Topic to explore or add/remove as interest",
            required=False,
        ),
        ToolParam(
            name="add_to_interests",
            type="boolean",
            description="Also add topic to permanent interests (default: true)",
            required=False,
            default=True,
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._curiosity_engine = None

    def _get_engine(self):
        """Get the curiosity engine from context."""
        if self._curiosity_engine:
            return self._curiosity_engine
        self._curiosity_engine = self.context.get("curiosity")
        return self._curiosity_engine

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        engine = self._get_engine()

        if not engine:
            return ToolResult(success=False, error="Curiosity engine not available")

        if action == "explore":
            return self._explore(engine, kwargs)
        elif action == "add_interest":
            return self._add_interest(engine, kwargs)
        elif action == "remove_interest":
            return self._remove_interest(engine, kwargs)
        elif action == "status":
            return self._status(engine)
        elif action == "log":
            return self._log(engine)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _explore(self, engine, kwargs) -> ToolResult:
        topic = kwargs.get("topic")
        if not topic:
            return ToolResult(success=False, error="'topic' is required for explore")

        add_to_interests = kwargs.get("add_to_interests", True)

        result = engine.explore_now(topic, add_to_interests=add_to_interests)

        return ToolResult(
            success=True,
            output=result,
            data={"topic": topic, "added_to_interests": add_to_interests},
        )

    def _add_interest(self, engine, kwargs) -> ToolResult:
        topic = kwargs.get("topic")
        if not topic:
            return ToolResult(success=False, error="'topic' is required")

        engine.add_interest(topic)
        return ToolResult(
            success=True,
            output=f"Added '{topic}' to permanent interests. I'll keep learning about this.",
            data={"interests": engine.config.interests},
        )

    def _remove_interest(self, engine, kwargs) -> ToolResult:
        topic = kwargs.get("topic")
        if not topic:
            return ToolResult(success=False, error="'topic' is required")

        if topic in engine.config.interests:
            engine.remove_interest(topic)
            return ToolResult(
                success=True,
                output=f"Removed '{topic}' from interests.",
                data={"interests": engine.config.interests},
            )
        return ToolResult(success=False, error=f"'{topic}' not found in interests")

    def _status(self, engine) -> ToolResult:
        status = engine.get_status()
        return ToolResult(success=True, output=status)

    def _log(self, engine) -> ToolResult:
        log = engine.get_exploration_log()
        return ToolResult(success=True, output=log)
