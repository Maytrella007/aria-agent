"""
ARIA - Project Knowledge Tool
==============================

Lightweight tool for saving and recalling project knowledge:
decisions, patterns, preferences, and general context.

Replaces the 1900-line CodingAgent with a clean ~100-line tool.
Storage: JSON file at data/project_knowledge.json
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.project_knowledge")

DEFAULT_FILE = "project_knowledge.json"


class ProjectKnowledgeTool(ToolBase):
    """Save and recall project knowledge: decisions, patterns, preferences."""

    name = "project_knowledge"
    description = (
        "Save and recall project knowledge. "
        "Actions: save (store a decision, pattern, or note), "
        "recall (search memories by query), "
        "summary (overview of all stored knowledge), "
        "set_preference (save a code style preference)."
    )
    parameters = [
        ToolParam(name="action", type="string", description="Action: save, recall, summary, set_preference", required=True,
                  enum=["save", "recall", "summary", "set_preference"]),
        ToolParam(name="content", type="string", description="Content to save (for save action)", required=False),
        ToolParam(name="category", type="string", description="Category: decision, pattern, bug_fix, convention, architecture, context",
                  required=False, default="context",
                  enum=["decision", "pattern", "bug_fix", "convention", "architecture", "context"]),
        ToolParam(name="query", type="string", description="Search query (for recall action)", required=False),
        ToolParam(name="key", type="string", description="Preference key (for set_preference)", required=False),
        ToolParam(name="value", type="string", description="Preference value (for set_preference)", required=False),
        ToolParam(name="limit", type="integer", description="Max results for recall (default: 10)", required=False, default=10),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        ctx = kwargs.get("context", {})
        data_dir = ctx.get("data_dir", "data")
        self._file = os.path.join(data_dir, DEFAULT_FILE)
        self._data = self._load()

    def _load(self) -> Dict[str, Any]:
        if os.path.isfile(self._file):
            try:
                with open(self._file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load knowledge: {e}")
        return {"memories": [], "preferences": {}}

    def _save(self):
        os.makedirs(os.path.dirname(self._file), exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]

        if action == "save":
            return self._do_save(kwargs)
        elif action == "recall":
            return self._do_recall(kwargs)
        elif action == "summary":
            return self._do_summary()
        elif action == "set_preference":
            return self._do_set_preference(kwargs)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _do_save(self, kwargs) -> ToolResult:
        content = kwargs.get("content")
        if not content:
            return ToolResult(success=False, error="'content' is required for save")

        category = kwargs.get("category", "context")
        entry = {
            "content": content,
            "category": category,
            "timestamp": datetime.now().isoformat(),
        }
        self._data["memories"].append(entry)
        self._save()
        return ToolResult(success=True, output=f"Saved [{category}]: {content}",
                          data={"total_memories": len(self._data["memories"])})

    def _do_recall(self, kwargs) -> ToolResult:
        query = (kwargs.get("query") or "").lower()
        limit = kwargs.get("limit", 10)
        memories = self._data.get("memories", [])

        if query:
            memories = [m for m in memories if query in m["content"].lower() or query in m.get("category", "")]

        # Sort by timestamp descending
        memories = sorted(memories, key=lambda m: m.get("timestamp", ""), reverse=True)[:limit]

        if not memories:
            return ToolResult(success=True, output="No matching knowledge found.", data={"count": 0})

        lines = []
        for m in memories:
            lines.append(f"[{m.get('category', '?')}] {m['content']}")
            lines.append(f"  ({m.get('timestamp', '?')[:16]})")

        return ToolResult(success=True, output="\n".join(lines), data={"count": len(memories)})

    def _do_summary(self) -> ToolResult:
        memories = self._data.get("memories", [])
        prefs = self._data.get("preferences", {})

        if not memories and not prefs:
            return ToolResult(success=True, output="No project knowledge stored yet.")

        # Count by category
        cats = {}
        for m in memories:
            cat = m.get("category", "context")
            cats[cat] = cats.get(cat, 0) + 1

        lines = [f"=== Project Knowledge ({len(memories)} entries) ===", ""]
        for cat, count in sorted(cats.items()):
            lines.append(f"  {cat}: {count}")

        if prefs:
            lines.append(f"\n=== Preferences ({len(prefs)}) ===")
            for k, v in prefs.items():
                lines.append(f"  {k}: {v}")

        return ToolResult(success=True, output="\n".join(lines),
                          data={"total": len(memories), "categories": cats, "preferences": prefs})

    def _do_set_preference(self, kwargs) -> ToolResult:
        key = kwargs.get("key")
        value = kwargs.get("value")
        if not key or not value:
            return ToolResult(success=False, error="'key' and 'value' are required for set_preference")

        self._data["preferences"][key] = value
        self._save()
        return ToolResult(success=True, output=f"Preference set: {key} = {value}")
