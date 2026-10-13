"""
ARIA - Google Drive Tool
=========================

Access Google Drive via Google API using OAuth tokens.
Actions: search, list, read, info, download.

Uses raw HTTP (no SDK) with Authorization: Bearer tokens
managed by ARIA's AuthManager.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.drive")

DRIVE_API = "https://www.googleapis.com/drive/v3"

# Google Docs MIME types that can be exported
EXPORT_MIMES = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
    "application/vnd.google-apps.presentation": ("text/plain", ".txt"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}


class GoogleDriveTool(ToolBase):
    """Search, read, and download files from Google Drive."""

    name = "google_drive"
    description = (
        "Access Google Drive: search files, list folders, read document content, "
        "get file info, and download files. Requires Google OAuth login. "
        "Use 'auth login google' to authenticate first."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="The Drive action to perform",
            required=True,
            enum=["search", "list", "read", "info", "download"],
        ),
        ToolParam(
            name="query",
            type="string",
            description="Search query (e.g. 'name contains budget', 'mimeType=application/pdf'). Used with 'search' action.",
        ),
        ToolParam(
            name="file_id",
            type="string",
            description="File ID to read, download, or get info about.",
        ),
        ToolParam(
            name="folder_id",
            type="string",
            description="Folder ID to list contents of. Defaults to 'root'. Used with 'list' action.",
            default="root",
        ),
        ToolParam(
            name="download_path",
            type="string",
            description="Local path to save downloaded file. Used with 'download' action.",
        ),
        ToolParam(
            name="max_results",
            type="integer",
            description="Max results for search/list (default: 20, max: 100)",
            default=20,
        ),
    ]

    def _get_token(self) -> Optional[str]:
        auth = self.context.get("auth_manager")
        if not auth:
            return None
        return auth.get_credential("google")

    def _api_get(self, url: str, token: str, params: dict = None) -> Dict[str, Any]:
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 401:
            auth = self.context.get("auth_manager")
            if auth:
                from ..auth_manager import ErrorType
                auth.report_failure("google", ErrorType.AUTH)
            return {"error": "Token expired. Run 'auth login google'."}
        if resp.status_code == 403:
            return {"error": f"Permission denied. Ensure Drive API is enabled. ({resp.text[:200]})"}
        if resp.status_code == 404:
            return {"error": "File not found. Check the file ID."}
        resp.raise_for_status()
        return resp.json()

    def _api_get_raw(self, url: str, token: str, params: dict = None) -> bytes:
        """GET request returning raw bytes (for file downloads)."""
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, params=params, timeout=60, stream=True)
        resp.raise_for_status()
        return resp.content

    def _execute(self, **kwargs) -> ToolResult:
        token = self._get_token()
        if not token:
            return ToolResult(
                success=False,
                error="Google not authenticated. Run 'auth login google' first."
            )

        action = kwargs["action"]
        dispatch = {
            "search": self._search,
            "list": self._list,
            "read": self._read,
            "info": self._info,
            "download": self._download,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        try:
            return handler(kwargs, token)
        except Exception as e:
            logger.error(f"Drive {action} failed: {e}")
            return ToolResult(success=False, error=str(e))

    # =========================================================================
    # Actions
    # =========================================================================

    def _search(self, kwargs: dict, token: str) -> ToolResult:
        """Search files on Drive."""
        query = kwargs.get("query", "")
        max_results = min(kwargs.get("max_results", 20), 100)

        # Build Drive API query
        # If user gave a simple string, wrap it in name contains
        if query and "=" not in query and "contains" not in query:
            api_query = f"name contains '{query}' and trashed = false"
        elif query:
            api_query = f"{query} and trashed = false"
        else:
            api_query = "trashed = false"

        data = self._api_get(
            f"{DRIVE_API}/files",
            token,
            params={
                "q": api_query,
                "pageSize": max_results,
                "fields": "files(id,name,mimeType,modifiedTime,size,owners,webViewLink)",
                "orderBy": "modifiedTime desc",
            },
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        files = data.get("files", [])
        if not files:
            return ToolResult(success=True, output=f"No files found for: {query}", data={"results": []})

        lines = [f"Drive search: {query} ({len(files)} results)", ""]
        for i, f in enumerate(files, 1):
            size = f.get("size", "")
            size_str = f" ({self._human_size(int(size))})" if size else ""
            owner = f.get("owners", [{}])[0].get("displayName", "") if f.get("owners") else ""
            lines.append(f"{i}. {f['name']}{size_str}")
            lines.append(f"   Type: {self._friendly_mime(f.get('mimeType', ''))}")
            lines.append(f"   Modified: {f.get('modifiedTime', '')}")
            if owner:
                lines.append(f"   Owner: {owner}")
            lines.append(f"   ID: {f['id']}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"results": files, "count": len(files)},
        )

    def _list(self, kwargs: dict, token: str) -> ToolResult:
        """List files in a folder."""
        folder_id = kwargs.get("folder_id", "root")
        max_results = min(kwargs.get("max_results", 20), 100)

        data = self._api_get(
            f"{DRIVE_API}/files",
            token,
            params={
                "q": f"'{folder_id}' in parents and trashed = false",
                "pageSize": max_results,
                "fields": "files(id,name,mimeType,modifiedTime,size)",
                "orderBy": "folder,name",
            },
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        files = data.get("files", [])
        if not files:
            return ToolResult(success=True, output="Folder is empty.", data={"results": []})

        lines = [f"Contents of folder ({len(files)} items):", ""]
        for f in files:
            is_folder = f.get("mimeType") == "application/vnd.google-apps.folder"
            icon = "[DIR]" if is_folder else "[FILE]"
            size = f.get("size", "")
            size_str = f" ({self._human_size(int(size))})" if size else ""
            lines.append(f"  {icon} {f['name']}{size_str}  (id: {f['id']})")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"results": files, "count": len(files)},
        )

    def _read(self, kwargs: dict, token: str) -> ToolResult:
        """Read file content (Google Docs exported as text, others as-is)."""
        file_id = kwargs.get("file_id")
        if not file_id:
            return ToolResult(success=False, error="file_id required for 'read' action")

        # Get file metadata first
        meta = self._api_get(
            f"{DRIVE_API}/files/{file_id}",
            token,
            params={"fields": "id,name,mimeType,size"},
        )
        if "error" in meta:
            return ToolResult(success=False, error=meta["error"])

        mime = meta.get("mimeType", "")
        name = meta.get("name", "")

        # Google Docs → export as text
        if mime in EXPORT_MIMES:
            export_mime, _ = EXPORT_MIMES[mime]
            try:
                content = self._api_get_raw(
                    f"{DRIVE_API}/files/{file_id}/export",
                    token,
                    params={"mimeType": export_mime},
                )
                text = content.decode("utf-8", errors="replace")
                # Truncate if too long
                if len(text) > 50000:
                    text = text[:50000] + "\n\n[... truncated at 50000 chars]"
                return ToolResult(
                    success=True,
                    output=f"=== {name} (exported as {export_mime}) ===\n\n{text}",
                    data={"id": file_id, "name": name, "mime": mime, "content": text},
                )
            except Exception as e:
                return ToolResult(success=False, error=f"Export failed: {e}")

        # Regular text files → download content
        if mime.startswith("text/") or mime in ("application/json", "application/xml"):
            try:
                content = self._api_get_raw(
                    f"{DRIVE_API}/files/{file_id}",
                    token,
                    params={"alt": "media"},
                )
                text = content.decode("utf-8", errors="replace")
                if len(text) > 50000:
                    text = text[:50000] + "\n\n[... truncated at 50000 chars]"
                return ToolResult(
                    success=True,
                    output=f"=== {name} ===\n\n{text}",
                    data={"id": file_id, "name": name, "mime": mime, "content": text},
                )
            except Exception as e:
                return ToolResult(success=False, error=f"Read failed: {e}")

        return ToolResult(
            success=False,
            error=f"Cannot read binary file '{name}' ({mime}). Use 'download' action instead.",
        )

    def _info(self, kwargs: dict, token: str) -> ToolResult:
        """Get detailed file info."""
        file_id = kwargs.get("file_id")
        if not file_id:
            return ToolResult(success=False, error="file_id required for 'info' action")

        data = self._api_get(
            f"{DRIVE_API}/files/{file_id}",
            token,
            params={
                "fields": "id,name,mimeType,modifiedTime,createdTime,size,owners,"
                          "shared,webViewLink,parents,description",
            },
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        size = data.get("size", "")
        lines = [
            f"Name: {data.get('name', '')}",
            f"ID: {data.get('id', '')}",
            f"Type: {self._friendly_mime(data.get('mimeType', ''))}",
            f"Size: {self._human_size(int(size)) if size else 'N/A'}",
            f"Created: {data.get('createdTime', '')}",
            f"Modified: {data.get('modifiedTime', '')}",
            f"Shared: {data.get('shared', False)}",
            f"Link: {data.get('webViewLink', '')}",
        ]
        if data.get("description"):
            lines.append(f"Description: {data['description']}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=data,
        )

    def _download(self, kwargs: dict, token: str) -> ToolResult:
        """Download a file to local disk."""
        file_id = kwargs.get("file_id")
        download_path = kwargs.get("download_path")
        if not file_id:
            return ToolResult(success=False, error="file_id required for 'download' action")

        # Get metadata
        meta = self._api_get(
            f"{DRIVE_API}/files/{file_id}",
            token,
            params={"fields": "id,name,mimeType,size"},
        )
        if "error" in meta:
            return ToolResult(success=False, error=meta["error"])

        name = meta.get("name", "downloaded_file")
        mime = meta.get("mimeType", "")

        if not download_path:
            data_dir = self.context.get("data_dir", ".")
            download_path = os.path.join(data_dir, "downloads", name)

        # Ensure directory exists
        os.makedirs(os.path.dirname(download_path), exist_ok=True)

        # Google Docs → export
        if mime in EXPORT_MIMES:
            export_mime, ext = EXPORT_MIMES[mime]
            if not download_path.endswith(ext):
                download_path += ext
            content = self._api_get_raw(
                f"{DRIVE_API}/files/{file_id}/export",
                token,
                params={"mimeType": export_mime},
            )
        else:
            content = self._api_get_raw(
                f"{DRIVE_API}/files/{file_id}",
                token,
                params={"alt": "media"},
            )

        with open(download_path, "wb") as f:
            f.write(content)

        return ToolResult(
            success=True,
            output=f"Downloaded '{name}' to {download_path} ({self._human_size(len(content))})",
            data={"path": download_path, "name": name, "size": len(content)},
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _human_size(self, nbytes: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if nbytes < 1024:
                return f"{nbytes:.1f} {unit}"
            nbytes /= 1024
        return f"{nbytes:.1f} TB"

    def _friendly_mime(self, mime: str) -> str:
        friendly = {
            "application/vnd.google-apps.folder": "Folder",
            "application/vnd.google-apps.document": "Google Doc",
            "application/vnd.google-apps.spreadsheet": "Google Sheet",
            "application/vnd.google-apps.presentation": "Google Slides",
            "application/pdf": "PDF",
            "image/png": "PNG Image",
            "image/jpeg": "JPEG Image",
        }
        return friendly.get(mime, mime)
