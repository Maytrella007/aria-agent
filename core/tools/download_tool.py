"""
ARIA - Download Tool
=====================

Download files from URLs to local filesystem.
Completes the web cycle: search → fetch → download.
Inspired by OpenClaw's web_fetch + nodes_media tools.
"""

import logging
import os
import urllib.parse
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.download")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

DEFAULT_TIMEOUT = 120
MAX_FILE_SIZE = 100_000_000  # 100MB
DEFAULT_DIR = "data/downloads"


class DownloadTool(ToolBase):
    """Download files from URLs."""

    name = "download"
    description = (
        "Download a file from a URL and save it locally. "
        "Supports any file type: PDFs, images, archives, etc. "
        "Returns the local path where the file was saved."
    )
    parameters = [
        ToolParam(
            name="url",
            type="string",
            description="URL of the file to download",
            required=True,
        ),
        ToolParam(
            name="filename",
            type="string",
            description="Name to save the file as (optional, auto-detected from URL)",
            required=False,
        ),
        ToolParam(
            name="directory",
            type="string",
            description=f"Directory to save in (default: {DEFAULT_DIR})",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        if not REQUESTS_AVAILABLE:
            return ToolResult(success=False, error="requests library not installed")

        url = kwargs["url"]
        filename = kwargs.get("filename")
        directory = kwargs.get("directory", DEFAULT_DIR)

        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="URL must start with http:// or https://")

        # SSRF check
        try:
            from core.security import is_private_url, get_current_mode
            is_private, reason = is_private_url(url)
            if is_private:
                return ToolResult(success=False, error=f"URL blocked: {reason}")
        except ImportError:
            pass

        # Auto-detect filename from URL
        if not filename:
            parsed = urllib.parse.urlparse(url)
            path = parsed.path.rstrip("/")
            filename = os.path.basename(path) if path else "download"
            if not filename or filename == "":
                filename = "download"
            # Clean query params from filename
            if "?" in filename:
                filename = filename.split("?")[0]

        # Ensure directory exists
        os.makedirs(directory, exist_ok=True)
        filepath = os.path.join(directory, filename)

        # Don't overwrite — add number suffix
        if os.path.exists(filepath):
            base, ext = os.path.splitext(filename)
            counter = 1
            while os.path.exists(filepath):
                filepath = os.path.join(directory, f"{base}_{counter}{ext}")
                counter += 1

        try:
            response = requests.get(
                url,
                stream=True,
                timeout=DEFAULT_TIMEOUT,
                headers={"User-Agent": "ARIA/1.0"},
                allow_redirects=True,
            )
            response.raise_for_status()

            # Check content length
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_FILE_SIZE:
                return ToolResult(
                    success=False,
                    error=f"File too large: {int(content_length)} bytes (max {MAX_FILE_SIZE})",
                )

            # Download with progress tracking
            downloaded = 0
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > MAX_FILE_SIZE:
                            f.close()
                            os.remove(filepath)
                            return ToolResult(success=False, error=f"File exceeded max size ({MAX_FILE_SIZE} bytes)")

            content_type = response.headers.get("Content-Type", "unknown")

            return ToolResult(
                success=True,
                output=f"Downloaded: {filepath} ({downloaded} bytes)",
                data={
                    "path": filepath,
                    "url": url,
                    "size": downloaded,
                    "content_type": content_type,
                    "filename": os.path.basename(filepath),
                },
            )

        except requests.Timeout:
            return ToolResult(success=False, error=f"Download timed out after {DEFAULT_TIMEOUT}s")
        except requests.HTTPError as e:
            return ToolResult(success=False, error=f"HTTP error: {e}")
        except Exception as e:
            # Cleanup partial file
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except OSError:
                    pass
            return ToolResult(success=False, error=str(e))
