"""ARIA - Slack Tool."""

import json
import os
import urllib.request

from .tool_base import ToolBase, ToolParam, ToolResult


class SlackTool(ToolBase):
    name = "slack"
    description = (
        "Interact with Slack. Actions: read_messages, send_message, react, pin. "
        "Use for channel updates, sending messages, and lightweight workspace triage."
    )
    parameters = [
        ToolParam(name="action", type="string", description="Slack action", required=True,
                  enum=["read_messages", "send_message", "react", "pin"]),
        ToolParam(name="channel", type="string", description="Slack channel ID", required=False),
        ToolParam(name="text", type="string", description="Message text", required=False),
        ToolParam(name="timestamp", type="string", description="Slack message timestamp", required=False),
        ToolParam(name="emoji", type="string", description="Emoji reaction without colons", required=False),
        ToolParam(name="limit", type="integer", description="Max messages to fetch", required=False, default=10),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        token = self.context.get("slack_token") or os.getenv("SLACK_BOT_TOKEN")
        if not token:
            return ToolResult(success=False, error="Slack token not configured")

        action = kwargs["action"]
        if action == "read_messages":
            channel = kwargs.get("channel")
            if not channel:
                return ToolResult(success=False, error="channel required")
            return self._request("conversations.history", token, {"channel": channel, "limit": kwargs.get("limit", 10)})
        if action == "send_message":
            channel = kwargs.get("channel")
            text = kwargs.get("text")
            if not channel or not text:
                return ToolResult(success=False, error="channel and text required")
            return self._request("chat.postMessage", token, {"channel": channel, "text": text})
        if action == "react":
            channel = kwargs.get("channel")
            timestamp = kwargs.get("timestamp")
            emoji = kwargs.get("emoji")
            if not channel or not timestamp or not emoji:
                return ToolResult(success=False, error="channel, timestamp, and emoji required")
            return self._request("reactions.add", token, {"channel": channel, "timestamp": timestamp, "name": emoji})
        if action == "pin":
            channel = kwargs.get("channel")
            timestamp = kwargs.get("timestamp")
            if not channel or not timestamp:
                return ToolResult(success=False, error="channel and timestamp required")
            return self._request("pins.add", token, {"channel": channel, "timestamp": timestamp})
        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _request(self, endpoint: str, token: str, payload: dict) -> ToolResult:
        req = urllib.request.Request(
            f"https://slack.com/api/{endpoint}",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception as e:
            return ToolResult(success=False, error=f"Slack request failed: {e}")

        if not data.get("ok"):
            return ToolResult(success=False, error=data.get("error", "Slack API error"), data=data)
        return ToolResult(success=True, output=json.dumps(data, ensure_ascii=False), data=data)
