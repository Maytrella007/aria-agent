"""
ARIA - HTTP Request Tool
=========================

Make full HTTP requests (GET, POST, PUT, DELETE, PATCH).
Goes beyond web_fetch by supporting all methods, custom headers, body, and auth.
Useful for interacting with REST APIs.
"""

import json
import logging
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.http_request")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

DEFAULT_TIMEOUT = 30
MAX_RESPONSE_SIZE = 200_000  # 200KB


class HttpRequestTool(ToolBase):
    """Make HTTP requests to any API endpoint."""

    name = "http_request"
    description = (
        "Make HTTP requests to APIs and web services. "
        "Supports GET, POST, PUT, DELETE, PATCH with custom headers and body. "
        "Use for interacting with REST APIs, webhooks, and external services."
    )
    parameters = [
        ToolParam(
            name="url",
            type="string",
            description="The URL to request",
            required=True,
        ),
        ToolParam(
            name="method",
            type="string",
            description="HTTP method (default: GET)",
            required=False,
            default="GET",
            enum=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
        ),
        ToolParam(
            name="body",
            type="string",
            description="Request body (JSON string for POST/PUT/PATCH)",
            required=False,
        ),
        ToolParam(
            name="headers",
            type="string",
            description="Custom headers as JSON string, e.g. '{\"Authorization\": \"Bearer token\"}'",
            required=False,
        ),
        ToolParam(
            name="timeout",
            type="integer",
            description="Timeout in seconds (default: 30)",
            required=False,
            default=30,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        if not REQUESTS_AVAILABLE:
            return ToolResult(success=False, error="requests library not installed")

        url = kwargs["url"]
        method = kwargs.get("method", "GET").upper()
        body_str = kwargs.get("body")
        headers_str = kwargs.get("headers")
        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 120)

        # Validate URL
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="URL must start with http:// or https://")

        # SSRF check
        try:
            from core.security import is_private_url, get_current_mode
            is_private, reason = is_private_url(url)
            if is_private:
                return ToolResult(
                    success=False,
                    error=f"URL blocked ({get_current_mode().value} mode): {reason}",
                )
        except ImportError:
            pass

        # Parse headers
        req_headers = {"User-Agent": "ARIA/1.0"}
        if headers_str:
            try:
                custom = json.loads(headers_str)
                if isinstance(custom, dict):
                    req_headers.update(custom)
            except json.JSONDecodeError:
                return ToolResult(success=False, error="Invalid headers JSON")

        # Parse body
        body_data = None
        json_data = None
        if body_str:
            try:
                json_data = json.loads(body_str)
            except json.JSONDecodeError:
                # Send as raw text
                body_data = body_str
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "text/plain"

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=req_headers,
                json=json_data if json_data is not None else None,
                data=body_data,
                timeout=timeout,
                allow_redirects=True,
            )

            # Get response content
            content_type = response.headers.get("Content-Type", "")
            resp_text = response.text[:MAX_RESPONSE_SIZE]
            truncated = len(response.text) > MAX_RESPONSE_SIZE

            # Try to parse JSON response
            resp_data = None
            if "json" in content_type or resp_text.strip().startswith(("{", "[")):
                try:
                    resp_data = response.json()
                except Exception:
                    pass

            # Format output
            lines = [
                f"{method} {url}",
                f"Status: {response.status_code} {response.reason}",
                f"Content-Type: {content_type}",
                f"Size: {len(response.text)} bytes" + (" (truncated)" if truncated else ""),
                "",
            ]

            if resp_data:
                lines.append(json.dumps(resp_data, indent=2, ensure_ascii=False)[:MAX_RESPONSE_SIZE])
            else:
                lines.append(resp_text)

            return ToolResult(
                success=response.ok,
                output="\n".join(lines),
                data={
                    "url": url,
                    "method": method,
                    "status_code": response.status_code,
                    "reason": response.reason,
                    "content_type": content_type,
                    "response_size": len(response.text),
                    "truncated": truncated,
                    "headers": dict(response.headers),
                    "json": resp_data,
                },
                error=f"HTTP {response.status_code}" if not response.ok else None,
            )

        except requests.Timeout:
            return ToolResult(success=False, error=f"Request timed out after {timeout}s")
        except requests.ConnectionError as e:
            return ToolResult(success=False, error=f"Connection error: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
