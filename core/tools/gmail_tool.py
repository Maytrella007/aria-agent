"""
ARIA - Gmail Tool
==================

Access Gmail via Google API using OAuth tokens.
Actions: search, read, send, reply, labels.

Uses raw HTTP (no SDK) with Authorization: Bearer tokens
managed by ARIA's AuthManager.
"""

import base64
import json
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.gmail")

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailTool(ToolBase):
    """Search, read, and send Gmail emails using Google OAuth."""

    name = "gmail"
    description = (
        "Access Gmail: search emails, read messages, send new emails, "
        "reply to threads, and list labels. Requires Google OAuth login. "
        "Use 'auth login google' to authenticate first."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="The Gmail action to perform",
            required=True,
            enum=["search", "read", "send", "reply", "labels"],
        ),
        ToolParam(
            name="query",
            type="string",
            description="Gmail search query (e.g. 'from:alice subject:meeting is:unread'). Used with 'search' action.",
        ),
        ToolParam(
            name="message_id",
            type="string",
            description="Message ID to read or reply to. Used with 'read' and 'reply' actions.",
        ),
        ToolParam(
            name="to",
            type="string",
            description="Recipient email address. Used with 'send' and 'reply' actions.",
        ),
        ToolParam(
            name="subject",
            type="string",
            description="Email subject. Used with 'send' action.",
        ),
        ToolParam(
            name="body",
            type="string",
            description="Email body (plain text). Used with 'send' and 'reply' actions.",
        ),
        ToolParam(
            name="max_results",
            type="integer",
            description="Max results for search (default: 10, max: 50)",
            default=10,
        ),
    ]

    def _get_token(self) -> Optional[str]:
        """Get Google OAuth token from AuthManager."""
        auth = self.context.get("auth_manager")
        if not auth:
            return None
        return auth.get_credential("google")

    def _api_get(self, url: str, token: str, params: dict = None) -> Dict[str, Any]:
        """Make authenticated GET request to Gmail API."""
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 401:
            auth = self.context.get("auth_manager")
            if auth:
                from ..auth_manager import ErrorType
                auth.report_failure("google", ErrorType.AUTH)
            return {"error": "Token expired or invalid. Run 'auth login google' to re-authenticate."}
        if resp.status_code == 403:
            return {"error": f"Permission denied. Ensure Gmail API is enabled and scopes are granted. ({resp.text[:200]})"}
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, url: str, token: str, data: dict = None, raw_body: str = None) -> Dict[str, Any]:
        """Make authenticated POST request to Gmail API."""
        import requests
        headers = {"Authorization": f"Bearer {token}"}
        if raw_body:
            headers["Content-Type"] = "message/rfc822"
            resp = requests.post(url, headers=headers, data=raw_body.encode(), timeout=30)
        else:
            resp = requests.post(url, headers=headers, json=data, timeout=30)
        if resp.status_code == 401:
            return {"error": "Token expired. Run 'auth login google'."}
        resp.raise_for_status()
        return resp.json()

    def _execute(self, **kwargs) -> ToolResult:
        token = self._get_token()
        if not token:
            return ToolResult(
                success=False,
                error="Google not authenticated. Run 'auth login google' first. "
                      "You need a Google Cloud OAuth Client ID — see 'auth providers' for setup."
            )

        action = kwargs["action"]
        dispatch = {
            "search": self._search,
            "read": self._read,
            "send": self._send,
            "reply": self._reply,
            "labels": self._labels,
        }
        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        try:
            return handler(kwargs, token)
        except Exception as e:
            logger.error(f"Gmail {action} failed: {e}")
            return ToolResult(success=False, error=str(e))

    # =========================================================================
    # Actions
    # =========================================================================

    def _search(self, kwargs: dict, token: str) -> ToolResult:
        """Search emails."""
        query = kwargs.get("query", "is:unread")
        max_results = min(kwargs.get("max_results", 10), 50)

        data = self._api_get(
            f"{GMAIL_API}/messages",
            token,
            params={"q": query, "maxResults": max_results},
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        messages = data.get("messages", [])
        if not messages:
            return ToolResult(success=True, output=f"No messages found for: {query}", data={"results": []})

        # Fetch headers for each message
        results = []
        for msg in messages[:max_results]:
            detail = self._api_get(
                f"{GMAIL_API}/messages/{msg['id']}",
                token,
                params={"format": "metadata", "metadataHeaders": "From,To,Subject,Date"},
            )
            if "error" in detail:
                continue

            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            results.append({
                "id": msg["id"],
                "thread_id": detail.get("threadId", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": detail.get("snippet", ""),
            })

        # Format output
        lines = [f"Gmail search: {query} ({len(results)} results)"]
        lines.append("")
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['subject']}")
            lines.append(f"   From: {r['from']}")
            lines.append(f"   Date: {r['date']}")
            lines.append(f"   {r['snippet'][:120]}")
            lines.append(f"   ID: {r['id']}")
            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"results": results, "count": len(results)},
        )

    def _read(self, kwargs: dict, token: str) -> ToolResult:
        """Read a specific email."""
        msg_id = kwargs.get("message_id")
        if not msg_id:
            return ToolResult(success=False, error="message_id required for 'read' action")

        data = self._api_get(
            f"{GMAIL_API}/messages/{msg_id}",
            token,
            params={"format": "full"},
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}

        # Extract body
        body = self._extract_body(data.get("payload", {}))

        lines = [
            f"From: {headers.get('From', '')}",
            f"To: {headers.get('To', '')}",
            f"Subject: {headers.get('Subject', '')}",
            f"Date: {headers.get('Date', '')}",
            f"Thread ID: {data.get('threadId', '')}",
            "",
            body or "(empty body)",
        ]

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "id": msg_id,
                "thread_id": data.get("threadId", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "body": body,
                "labels": data.get("labelIds", []),
            },
        )

    def _send(self, kwargs: dict, token: str) -> ToolResult:
        """Send a new email."""
        to = kwargs.get("to")
        subject = kwargs.get("subject", "(no subject)")
        body = kwargs.get("body", "")

        if not to:
            return ToolResult(success=False, error="'to' required for 'send' action")

        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = to
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        data = self._api_post(
            f"{GMAIL_API}/messages/send",
            token,
            data={"raw": raw},
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        return ToolResult(
            success=True,
            output=f"Email sent to {to} (subject: {subject})",
            data={"id": data.get("id", ""), "thread_id": data.get("threadId", "")},
        )

    def _reply(self, kwargs: dict, token: str) -> ToolResult:
        """Reply to an existing email thread."""
        msg_id = kwargs.get("message_id")
        body = kwargs.get("body", "")

        if not msg_id:
            return ToolResult(success=False, error="message_id required for 'reply' action")
        if not body:
            return ToolResult(success=False, error="body required for 'reply' action")

        # Get original message to extract thread info
        original = self._api_get(
            f"{GMAIL_API}/messages/{msg_id}",
            token,
            params={"format": "metadata", "metadataHeaders": "From,Subject,Message-ID"},
        )
        if "error" in original:
            return ToolResult(success=False, error=original["error"])

        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
        thread_id = original.get("threadId", "")
        reply_to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        msg = MIMEText(body, "plain", "utf-8")
        msg["To"] = reply_to
        msg["Subject"] = subject
        msg["In-Reply-To"] = headers.get("Message-ID", "")
        msg["References"] = headers.get("Message-ID", "")

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

        data = self._api_post(
            f"{GMAIL_API}/messages/send",
            token,
            data={"raw": raw, "threadId": thread_id},
        )
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        return ToolResult(
            success=True,
            output=f"Reply sent to {reply_to} (thread: {thread_id})",
            data={"id": data.get("id", ""), "thread_id": thread_id},
        )

    def _labels(self, kwargs: dict, token: str) -> ToolResult:
        """List Gmail labels."""
        data = self._api_get(f"{GMAIL_API}/labels", token)
        if "error" in data:
            return ToolResult(success=False, error=data["error"])

        labels = data.get("labels", [])
        lines = ["Gmail Labels:"]
        for label in sorted(labels, key=lambda l: l.get("name", "")):
            lines.append(f"  - {label.get('name', '')} (id: {label.get('id', '')})")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"labels": labels},
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _extract_body(self, payload: dict) -> str:
        """Extract plain text body from Gmail message payload."""
        # Direct body
        if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

        # Multipart — look for text/plain
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
                return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")

        # Nested multipart
        for part in parts:
            if part.get("parts"):
                result = self._extract_body(part)
                if result:
                    return result

        # Fallback: try text/html
        for part in parts:
            if part.get("mimeType") == "text/html" and part.get("body", {}).get("data"):
                html = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                # Basic HTML stripping
                import re
                text = re.sub(r'<[^>]+>', '', html)
                text = re.sub(r'\s+', ' ', text).strip()
                return text

        return ""
