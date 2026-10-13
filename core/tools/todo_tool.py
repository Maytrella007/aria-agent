"""
ARIA - Todo Tool
=================

Manage a persistent todo list with JSON storage.
Supports add, complete, list, remove, and update actions.
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.todo")


class TodoTool(ToolBase):
    """Manage a persistent todo list stored as JSON."""

    name = "todo"
    description = (
        "Manage a todo list. "
        "Actions: add (create todo), complete (mark done), list (show todos), "
        "remove (delete todo), update (change text or status)."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: add, complete, list, remove, update",
            required=True,
            enum=["add", "complete", "list", "remove", "update"],
        ),
        ToolParam(
            name="text",
            type="string",
            description="Todo text (for add or update)",
            required=False,
        ),
        ToolParam(
            name="id",
            type="integer",
            description="Todo ID (for complete, remove, update)",
            required=False,
        ),
        ToolParam(
            name="status",
            type="string",
            description="Status to set (for update)",
            required=False,
            enum=["pending", "done", "blocked"],
        ),
    ]

    def _get_store_path(self) -> str:
        data_dir = self.context.get("data_dir", ".")
        return os.path.join(data_dir, "todos.json")

    def _load_todos(self) -> List[Dict[str, Any]]:
        path = self._get_store_path()
        if not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Corrupted todos.json, starting fresh")
            return []

    def _save_todos(self, todos: List[Dict[str, Any]]) -> None:
        path = self._get_store_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(todos, f, indent=2, ensure_ascii=False)

    def _next_id(self, todos: List[Dict[str, Any]]) -> int:
        if not todos:
            return 1
        return max(t["id"] for t in todos) + 1

    def _find_todo(self, todos: List[Dict[str, Any]], todo_id: int) -> Optional[Dict[str, Any]]:
        for t in todos:
            if t["id"] == todo_id:
                return t
        return None

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]

        actions = {
            "add": self._add,
            "complete": self._complete,
            "list": self._list,
            "remove": self._remove,
            "update": self._update,
        }

        handler = actions.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(kwargs)

    def _add(self, kwargs: dict) -> ToolResult:
        text = kwargs.get("text")
        if not text:
            return ToolResult(success=False, error="Missing 'text' for new todo")

        todos = self._load_todos()
        todo = {
            "id": self._next_id(todos),
            "text": text,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "completed_at": None,
        }
        todos.append(todo)
        self._save_todos(todos)

        return ToolResult(
            success=True,
            output=f"Added todo #{todo['id']}: {text}",
            data={"todo": todo},
        )

    def _complete(self, kwargs: dict) -> ToolResult:
        todo_id = kwargs.get("id")
        if todo_id is None:
            return ToolResult(success=False, error="Missing 'id' to complete")

        todos = self._load_todos()
        todo = self._find_todo(todos, int(todo_id))
        if not todo:
            return ToolResult(success=False, error=f"Todo #{todo_id} not found")

        todo["status"] = "done"
        todo["completed_at"] = datetime.now().isoformat()
        self._save_todos(todos)

        return ToolResult(
            success=True,
            output=f"Completed todo #{todo_id}: {todo['text']}",
            data={"todo": todo},
        )

    def _list(self, kwargs: dict) -> ToolResult:
        todos = self._load_todos()
        if not todos:
            return ToolResult(success=True, output="No todos found.", data={"todos": []})

        grouped = {"pending": [], "blocked": [], "done": []}
        for t in todos:
            status = t.get("status", "pending")
            grouped.setdefault(status, []).append(t)

        lines = [f"Todos ({len(todos)} total):\n"]
        for status in ("pending", "blocked", "done"):
            items = grouped.get(status, [])
            if not items:
                continue
            lines.append(f"  [{status.upper()}] ({len(items)})")
            for t in items:
                marker = "x" if status == "done" else (" " if status == "pending" else "!")
                lines.append(f"    [{marker}] #{t['id']}: {t['text']}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"todos": todos, "count": len(todos)},
        )

    def _remove(self, kwargs: dict) -> ToolResult:
        todo_id = kwargs.get("id")
        if todo_id is None:
            return ToolResult(success=False, error="Missing 'id' to remove")

        todos = self._load_todos()
        todo = self._find_todo(todos, int(todo_id))
        if not todo:
            return ToolResult(success=False, error=f"Todo #{todo_id} not found")

        todos = [t for t in todos if t["id"] != int(todo_id)]
        self._save_todos(todos)

        return ToolResult(
            success=True,
            output=f"Removed todo #{todo_id}: {todo['text']}",
            data={"removed": todo},
        )

    def _update(self, kwargs: dict) -> ToolResult:
        todo_id = kwargs.get("id")
        if todo_id is None:
            return ToolResult(success=False, error="Missing 'id' to update")

        text = kwargs.get("text")
        status = kwargs.get("status")
        if not text and not status:
            return ToolResult(success=False, error="Provide 'text' and/or 'status' to update")

        todos = self._load_todos()
        todo = self._find_todo(todos, int(todo_id))
        if not todo:
            return ToolResult(success=False, error=f"Todo #{todo_id} not found")

        if text:
            todo["text"] = text
        if status:
            todo["status"] = status
            if status == "done" and not todo.get("completed_at"):
                todo["completed_at"] = datetime.now().isoformat()

        self._save_todos(todos)

        return ToolResult(
            success=True,
            output=f"Updated todo #{todo_id}: {todo['text']} [{todo['status']}]",
            data={"todo": todo},
        )
