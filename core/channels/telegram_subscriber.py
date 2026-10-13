"""
Telegram Subscriber - Consumes EventBus events and edits Telegram messages progressively.

Connects to the EventBus and provides real-time streaming to Telegram by
editing a message progressively as tokens arrive from the LLM.
"""

import logging
import time

logger = logging.getLogger(__name__)


class TelegramSubscriber:
    """Subscriber that progressively edits a Telegram message as tokens stream in."""

    EDIT_INTERVAL = 1.0  # seconds between message edits (Telegram rate limit)

    def __init__(self, event_bus, bot, chat_id):
        """
        Args:
            event_bus: The EventBus to subscribe to.
            bot: telegram.Bot instance (python-telegram-bot).
            chat_id: Telegram chat ID to send/edit messages in.
        """
        self.bot = bot
        self.chat_id = chat_id
        self.accumulated_text = ""
        self.message_id = None
        self.last_edit = 0
        self._unsub = event_bus.subscribe(self._on_event)

    def _on_event(self, event):
        if event.stream == "assistant" and event.event == "delta":
            self.accumulated_text += event.data["text"]
            now = time.time()
            if now - self.last_edit > self.EDIT_INTERVAL:
                self._update_message(self.accumulated_text + " \u2588")
                self.last_edit = now

        elif event.stream == "assistant" and event.event == "done":
            # Final edit without cursor
            self._update_message(self.accumulated_text)
            self.accumulated_text = ""
            self.message_id = None

        elif event.stream == "tool" and event.event == "start":
            tool_name = event.data["name"]
            self._update_message(self.accumulated_text + f"\n\U0001f527 {tool_name}...")

        elif event.stream == "tool" and event.event == "result":
            success = event.data.get("success", True)
            elapsed = event.data.get("elapsed_ms", 0)
            icon = "\u2705" if success else "\u274c"
            self._update_message(
                self.accumulated_text + f"\n{icon} ({elapsed}ms)"
            )

        elif event.stream == "error" and event.event == "error":
            error_msg = event.data.get("message", "Unknown error")
            self._update_message(
                self.accumulated_text + f"\n\u26a0\ufe0f Error: {error_msg[:200]}"
            )

    def _update_message(self, text):
        """Send or edit the Telegram message."""
        if not text.strip():
            return
        try:
            if self.message_id is None:
                # Send new message
                msg = self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text[:4096],  # Telegram message limit
                )
                self.message_id = msg.message_id
            else:
                # Edit existing message
                self.bot.edit_message_text(
                    chat_id=self.chat_id,
                    message_id=self.message_id,
                    text=text[:4096],
                )
        except Exception as e:
            # Don't crash on Telegram API errors (rate limits, etc.)
            logger.debug(f"Telegram edit failed: {e}")

    def unsubscribe(self):
        """Disconnect from the event bus."""
        self._unsub()
        self.accumulated_text = ""
        self.message_id = None
