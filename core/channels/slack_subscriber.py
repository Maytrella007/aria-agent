"""
Slack Subscriber - Consumes EventBus events and updates Slack messages progressively.

Connects to the EventBus and provides real-time streaming to Slack by
updating a message progressively as tokens arrive from the LLM.

Uses chat_update() for progressive editing with a 1.0s throttle.
"""

import logging
import time

logger = logging.getLogger(__name__)


class SlackSubscriber:
    """Subscriber that progressively updates a Slack message as tokens stream in."""

    EDIT_INTERVAL = 1.0  # seconds between message updates
    MESSAGE_LIMIT = 4000

    def __init__(self, event_bus, client, channel):
        """
        Args:
            event_bus: The EventBus to subscribe to.
            client: slack_sdk.WebClient instance.
            channel: Slack channel ID to send/update messages in.
        """
        self.client = client
        self.channel = channel
        self.accumulated_text = ""
        self.message_ts = None  # Slack message timestamp (acts as message ID)
        self.last_edit = 0
        self._unsub = event_bus.subscribe(self._on_event)

    def _on_event(self, event):
        if event.stream == "assistant" and event.event == "delta":
            self.accumulated_text += event.data["text"]
            now = time.time()
            if now - self.last_edit > self.EDIT_INTERVAL:
                display = self._truncate(self.accumulated_text + " \u2588")
                self._update_message(display)
                self.last_edit = now

        elif event.stream == "assistant" and event.event == "done":
            # Final update without cursor
            display = self._truncate(self.accumulated_text)
            self._update_message(display)
            self.accumulated_text = ""
            self.message_ts = None

        elif event.stream == "tool" and event.event == "start":
            tool_name = event.data["name"]
            display = self._truncate(
                self.accumulated_text + f"\n:wrench: {tool_name}..."
            )
            self._update_message(display)

        elif event.stream == "tool" and event.event == "result":
            success = event.data.get("success", True)
            elapsed = event.data.get("elapsed_ms", 0)
            icon = ":white_check_mark:" if success else ":x:"
            display = self._truncate(
                self.accumulated_text + f"\n{icon} ({elapsed}ms)"
            )
            self._update_message(display)

        elif event.stream == "error" and event.event == "error":
            error_msg = event.data.get("message", "Unknown error")
            display = self._truncate(
                self.accumulated_text + f"\n:warning: Error: {error_msg[:200]}"
            )
            self._update_message(display)

    def _truncate(self, text: str) -> str:
        """Truncate text to Slack's practical message limit."""
        if len(text) <= self.MESSAGE_LIMIT:
            return text
        return text[: self.MESSAGE_LIMIT - 3] + "..."

    def _update_message(self, text: str):
        """Send or update the Slack message."""
        if not text.strip():
            return
        try:
            if self.message_ts is None:
                # Post new message
                result = self.client.chat_postMessage(
                    channel=self.channel,
                    text=text,
                )
                if result.get("ok"):
                    self.message_ts = result["ts"]
            else:
                # Update existing message
                self.client.chat_update(
                    channel=self.channel,
                    ts=self.message_ts,
                    text=text,
                )
        except Exception as e:
            # Don't crash on Slack API errors (rate limits, etc.)
            logger.debug(f"Slack update failed: {e}")

    def unsubscribe(self):
        """Disconnect from the event bus."""
        self._unsub()
        self.accumulated_text = ""
        self.message_ts = None
