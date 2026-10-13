"""
ARIA - Compress Tool
=====================

Create and extract zip and tar.gz archives.
Uses Python's built-in zipfile and tarfile modules.
"""

import logging
import os
import tarfile
import zipfile
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.compress")

# Safety limits
MAX_EXTRACT_SIZE = 500 * 1024 * 1024  # 500MB


class CompressTool(ToolBase):
    """Create and extract zip and tar.gz archives."""

    name = "compress"
    description = (
        "Archive and compression utilities. "
        "Actions: zip (create zip), unzip (extract zip), tar (create tar.gz), "
        "untar (extract tar.gz), list (list archive contents)."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: zip, unzip, tar, untar, list",
            required=True,
            enum=["zip", "unzip", "tar", "untar", "list"],
        ),
        ToolParam(
            name="path",
            type="string",
            description="Path to the archive file",
            required=True,
        ),
        ToolParam(
            name="destination",
            type="string",
            description="Output directory for extraction",
            required=False,
        ),
        ToolParam(
            name="files",
            type="string",
            description="Comma-separated list of files to add to the archive",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        path = os.path.expanduser(kwargs["path"])

        actions = {
            "zip": self._zip,
            "unzip": self._unzip,
            "tar": self._tar,
            "untar": self._untar,
            "list": self._list,
        }

        handler = actions.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(path, kwargs)

    @staticmethod
    def _check_path_traversal(name: str) -> bool:
        """Return True if the member name attempts path traversal."""
        normalized = os.path.normpath(name)
        return normalized.startswith("..") or os.path.isabs(normalized)

    @staticmethod
    def _total_size(members_sizes: list) -> int:
        return sum(members_sizes)

    def _zip(self, path: str, kwargs: dict) -> ToolResult:
        files_str = kwargs.get("files")
        if not files_str:
            return ToolResult(success=False, error="Missing 'files' to add to archive")

        file_list = [f.strip() for f in files_str.split(",") if f.strip()]
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in file_list:
                    f = os.path.expanduser(f)
                    if not os.path.exists(f):
                        return ToolResult(success=False, error=f"File not found: {f}")
                    arcname = os.path.basename(f)
                    zf.write(f, arcname)

            size = os.path.getsize(path)
            return ToolResult(
                success=True,
                output=f"Created zip archive: {path} ({len(file_list)} files, {size} bytes)",
                data={"path": path, "count": len(file_list), "size": size},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Zip error: {e}")

    def _unzip(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"Archive not found: {path}")

        dest = os.path.expanduser(kwargs.get("destination", os.path.dirname(path) or "."))
        try:
            with zipfile.ZipFile(path, "r") as zf:
                total = sum(i.file_size for i in zf.infolist())
                if total > MAX_EXTRACT_SIZE:
                    return ToolResult(
                        success=False,
                        error=f"Extracted size {total} bytes exceeds limit ({MAX_EXTRACT_SIZE} bytes)",
                    )
                for member in zf.infolist():
                    if self._check_path_traversal(member.filename):
                        return ToolResult(
                            success=False,
                            error=f"Path traversal detected in member: {member.filename}",
                        )
                os.makedirs(dest, exist_ok=True)
                zf.extractall(dest)

            return ToolResult(
                success=True,
                output=f"Extracted {path} to {dest}",
                data={"path": path, "destination": dest},
            )
        except zipfile.BadZipFile:
            return ToolResult(success=False, error=f"Invalid zip file: {path}")
        except Exception as e:
            return ToolResult(success=False, error=f"Unzip error: {e}")

    def _tar(self, path: str, kwargs: dict) -> ToolResult:
        files_str = kwargs.get("files")
        if not files_str:
            return ToolResult(success=False, error="Missing 'files' to add to archive")

        file_list = [f.strip() for f in files_str.split(",") if f.strip()]
        try:
            with tarfile.open(path, "w:gz") as tf:
                for f in file_list:
                    f = os.path.expanduser(f)
                    if not os.path.exists(f):
                        return ToolResult(success=False, error=f"File not found: {f}")
                    tf.add(f, arcname=os.path.basename(f))

            size = os.path.getsize(path)
            return ToolResult(
                success=True,
                output=f"Created tar.gz archive: {path} ({len(file_list)} files, {size} bytes)",
                data={"path": path, "count": len(file_list), "size": size},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Tar error: {e}")

    def _untar(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"Archive not found: {path}")

        dest = os.path.expanduser(kwargs.get("destination", os.path.dirname(path) or "."))
        try:
            with tarfile.open(path, "r:*") as tf:
                total = sum(m.size for m in tf.getmembers() if m.isfile())
                if total > MAX_EXTRACT_SIZE:
                    return ToolResult(
                        success=False,
                        error=f"Extracted size {total} bytes exceeds limit ({MAX_EXTRACT_SIZE} bytes)",
                    )
                for member in tf.getmembers():
                    if self._check_path_traversal(member.name):
                        return ToolResult(
                            success=False,
                            error=f"Path traversal detected in member: {member.name}",
                        )
                os.makedirs(dest, exist_ok=True)
                tf.extractall(dest, filter="data")

            return ToolResult(
                success=True,
                output=f"Extracted {path} to {dest}",
                data={"path": path, "destination": dest},
            )
        except tarfile.TarError as e:
            return ToolResult(success=False, error=f"Invalid tar file: {e}")
        except Exception as e:
            return ToolResult(success=False, error=f"Untar error: {e}")

    def _list(self, path: str, kwargs: dict) -> ToolResult:
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"Archive not found: {path}")

        try:
            entries = []
            if zipfile.is_zipfile(path):
                with zipfile.ZipFile(path, "r") as zf:
                    for info in zf.infolist():
                        entries.append({"name": info.filename, "size": info.file_size})
            else:
                with tarfile.open(path, "r:*") as tf:
                    for member in tf.getmembers():
                        entries.append({"name": member.name, "size": member.size})

            lines = [f"Archive: {path} ({len(entries)} entries)\n"]
            for e in entries:
                lines.append(f"  {e['name']}  ({e['size']} bytes)")

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={"path": path, "entries": entries, "count": len(entries)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"List error: {e}")
