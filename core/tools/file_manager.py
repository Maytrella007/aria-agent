"""
ARIA - File Manager Tool
=========================

Read, write, list, and search files.
More structured than shell_exec for file operations.
"""

import fnmatch
import logging
import os
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.file_manager")

# Safety limits
MAX_READ_SIZE = 500_000  # 500KB
MAX_WRITE_SIZE = 1_000_000  # 1MB
MAX_LIST_ENTRIES = 500


class FileManagerTool(ToolBase):
    """Read, write, list, and search files on the local filesystem."""

    name = "file_manager"
    description = (
        "Manage files on the local filesystem. "
        "Actions: read, write, append, list, search, info, mkdir, delete. "
        "Use for creating notes, reading configs, organizing files, etc."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: read, write, append, list, search, info, mkdir, delete",
            required=True,
            enum=["read", "write", "append", "list", "search", "info", "mkdir", "delete"],
        ),
        ToolParam(
            name="path",
            type="string",
            description="File or directory path",
            required=True,
        ),
        ToolParam(
            name="content",
            type="string",
            description="Content to write (for write/append actions)",
            required=False,
        ),
        ToolParam(
            name="pattern",
            type="string",
            description="Search pattern (glob for search, e.g. '*.py')",
            required=False,
            default="*",
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        path = os.path.expanduser(kwargs["path"])

        actions = {
            "read": self._read,
            "write": self._write,
            "append": self._append,
            "list": self._list,
            "search": self._search,
            "info": self._info,
            "mkdir": self._mkdir,
            "delete": self._delete,
        }

        handler = actions.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(path, kwargs)

    def _read(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        size = os.path.getsize(path)
        if size > MAX_READ_SIZE:
            return ToolResult(
                success=False,
                error=f"File too large: {size} bytes (max {MAX_READ_SIZE})",
            )

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return ToolResult(
                success=True,
                output=content,
                data={"path": path, "size": size, "lines": content.count("\n") + 1},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Read error: {e}")

    def _write(self, path: str, kwargs: dict) -> ToolResult:
        content = kwargs.get("content")
        if content is None:
            return ToolResult(success=False, error="Missing 'content' to write")

        if len(content) > MAX_WRITE_SIZE:
            return ToolResult(success=False, error=f"Content too large (max {MAX_WRITE_SIZE} bytes)")

        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                success=True,
                output=f"Written {len(content)} bytes to {path}",
                data={"path": path, "size": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Write error: {e}")

    def _append(self, path: str, kwargs: dict) -> ToolResult:
        content = kwargs.get("content")
        if content is None:
            return ToolResult(success=False, error="Missing 'content' to append")

        try:
            dir_path = os.path.dirname(path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)

            with open(path, "a", encoding="utf-8") as f:
                f.write(content)

            return ToolResult(
                success=True,
                output=f"Appended {len(content)} bytes to {path}",
                data={"path": path, "appended": len(content)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Append error: {e}")

    def _list(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.isdir(path):
            return ToolResult(success=False, error=f"Directory not found: {path}")

        try:
            entries = []
            for name in sorted(os.listdir(path))[:MAX_LIST_ENTRIES]:
                full = os.path.join(path, name)
                is_dir = os.path.isdir(full)
                size = os.path.getsize(full) if not is_dir else 0
                entries.append({
                    "name": name,
                    "type": "dir" if is_dir else "file",
                    "size": size,
                })

            lines = [f"Contents of {path} ({len(entries)} entries):\n"]
            for e in entries:
                icon = "📁" if e["type"] == "dir" else "📄"
                size_str = f" ({e['size']} bytes)" if e["type"] == "file" else ""
                lines.append(f"  {icon} {e['name']}{size_str}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"path": path, "entries": entries},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"List error: {e}")

    def _search(self, path: str, kwargs: dict) -> ToolResult:
        pattern = kwargs.get("pattern", "*")

        if not os.path.isdir(path):
            return ToolResult(success=False, error=f"Directory not found: {path}")

        matches = []
        try:
            for root, dirs, files in os.walk(path):
                for name in files:
                    if fnmatch.fnmatch(name, pattern):
                        full = os.path.join(root, name)
                        matches.append(full)
                        if len(matches) >= MAX_LIST_ENTRIES:
                            break
                if len(matches) >= MAX_LIST_ENTRIES:
                    break

            if not matches:
                return ToolResult(
                    success=True,
                    output=f"No files matching '{pattern}' in {path}",
                    data={"matches": [], "pattern": pattern},
                )

            lines = [f"Found {len(matches)} files matching '{pattern}':\n"]
            for m in matches:
                lines.append(f"  {m}")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"matches": matches, "pattern": pattern, "count": len(matches)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search error: {e}")

    def _info(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.exists(path):
            return ToolResult(success=False, error=f"Path not found: {path}")

        try:
            stat = os.stat(path)
            from datetime import datetime
            info = {
                "path": path,
                "exists": True,
                "type": "directory" if os.path.isdir(path) else "file",
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "readable": os.access(path, os.R_OK),
                "writable": os.access(path, os.W_OK),
            }

            lines = [f"File info: {path}\n"]
            for k, v in info.items():
                if k != "path":
                    lines.append(f"  {k}: {v}")

            return ToolResult(success=True, output="\n".join(lines), data=info)
        except Exception as e:
            return ToolResult(success=False, error=f"Info error: {e}")

    def _mkdir(self, path: str, kwargs: dict) -> ToolResult:
        try:
            os.makedirs(path, exist_ok=True)
            return ToolResult(success=True, output=f"Directory created: {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Mkdir error: {e}")

    def _delete(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.exists(path):
            return ToolResult(success=False, error=f"Path not found: {path}")

        # Safety: don't delete directories with this tool
        if os.path.isdir(path):
            return ToolResult(
                success=False,
                error="Cannot delete directories with file_manager. Use shell_exec for 'rm -r'.",
            )

        try:
            os.remove(path)
            return ToolResult(success=True, output=f"Deleted: {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Delete error: {e}")
