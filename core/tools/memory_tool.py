"""
ARIA - Memory Tool
===================

Search ARIA's episodic memory via function calling.
The LLM decides when and what to search, building precise queries.
Connects to the existing ExperientialMemorySystem (ChromaDB + SQLite).
"""

import logging
from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.memory")


class MemoryTool(ToolBase):
    """Search ARIA's episodic memory."""

    name = "memory_search"
    description = (
        "Search ARIA's episodic memory for past conversations, experiences, and knowledge. "
        "Use when you need to recall something from a previous conversation, "
        "check if a topic was discussed before, or find what someone said. "
        "You can make multiple searches with different queries for better results."
    )
    parameters = [
        ToolParam(
            name="query",
            type="string",
            description="What to search for (topic, person, event, keyword)",
            required=True,
        ),
        ToolParam(
            name="limit",
            type="integer",
            description="Max memories to return (default: 5, max: 15)",
            required=False,
            default=5,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        query = kwargs["query"]
        limit = min(kwargs.get("limit", 5), 15)

        memory = self.context.get("memory")
        if not memory:
            return ToolResult(success=False, error="Memory system not available")

        if hasattr(memory, "recall_enhanced"):
            results = memory.recall_enhanced(query, limit=limit)
        else:
            results = memory.recall(query, limit=limit)

        if not results:
            return ToolResult(
                success=True,
                output=f"No memories found for: {query}",
                data={"query": query, "count": 0},
            )

        lines = [f"Found {len(results)} memories for: {query}\n"]
        memories_data = []

        for i, m in enumerate(results, 1):
            ts = ""
            if hasattr(m, "timestamp") and m.timestamp:
                ts = m.timestamp[:19]

            people = []
            if hasattr(m, "involves_people") and m.involves_people:
                people = m.involves_people[:5]
            elif hasattr(m, "involves") and m.involves:
                people = m.involves[:5]

            emotion = ""
            if hasattr(m, "emotional_tone") and m.emotional_tone:
                emotion = m.emotional_tone.value if hasattr(m.emotional_tone, "value") else str(m.emotional_tone)

            tags = []
            if hasattr(m, "tags") and m.tags:
                tags = m.tags[:5]

            content = m.content[:400]
            if len(m.content) > 400:
                content += "..."

            lines.append(f"--- Memory {i} ({ts}) ---")
            if people:
                lines.append(f"  People: {', '.join(people)}")
            if emotion:
                lines.append(f"  Emotion: {emotion}")
            if tags:
                lines.append(f"  Topics: {', '.join(tags)}")
            lines.append(f"  {content}")
            lines.append("")

            memories_data.append({
                "timestamp": ts, "people": people,
                "emotion": emotion, "tags": tags, "content": content,
            })

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"query": query, "count": len(results), "memories": memories_data},
        )
