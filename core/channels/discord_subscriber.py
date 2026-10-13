"""
Discord Subscriber - Consumes EventBus events and edits Discord messages progressively.

Connects to the EventBus and provides real-time streaming to Discord by
editing a message progressively as tokens arrive from the LLM.

Discord rate limit: 5 edits per 5 seconds per message → 1.2s throttle.
Message limit: 2000 characters.
"""

import logging
import time

logger = logging.getLogger(__name__)


class DiscordSubscriber:
    """Subscriber that progressively edits a Discord message as tokens stream in."""

    EDIT_INTERVAL = 1.2  # seconds between edits (Discord: 5 edits per 5s)
    MESSAGE_LIMIT = 2000

    def __init__(self, event_bus, channel, loop):
        """
        Args:
            event_bus: The EventBus to subscribe to.
            channel: discord.TextChannel or similar to send/edit messages in.
            loop: asyncio event loop (Discord client's loop) for scheduling coroutines.
        """
        self.channel = channel
        self.loop = loop
        self.accumulated_text = ""
        self.message = None  # discord.Message object
        self.last_edit = 0
        self._unsub = event_bus.subscribe(self._on_event)

    def _on_event(self, event):
        if event.stream == "assistant" and event.event == "delta":
            self.accumulated_text += event.data["text"]
            now = time.time()
            if now - self.last_edit > self.EDIT_INTERVAL:
                display = self._truncate(self.accumulated_text + " \u2588")
                self._schedule(self._update_message(display))
                self.last_edit = now

        elif event.stream == "assistant" and event.event == "done":
            # Final edit without cursor
            display = self._truncate(self.accumulated_text)
            self._schedule(self._update_message(display))
            self.accumulated_text = ""
            self.message = None

        elif event.stream == "tool" and event.event == "start":
            tool_name = event.data["name"]
            display = self._truncate(
                self.accumulated_text + f"\n\U0001f527 {tool_name}..."
            )
            self._schedule(self._update_message(display))

        elif event.stream == "tool" and event.event == "result":
            success = event.data.get("success", True)
            elapsed = event.data.get("elapsed_ms", 0)
            icon = "\u2705" if success else "\u274c"
            display = self._truncate(
                self.accumulated_text + f"\n{icon} ({elapsed}ms)"
            )
            self._schedule(self._update_message(display))

        elif event.stream == "error" and event.event == "error":
            error_msg = event.data.get("message", "Unknown error")
            display = self._truncate(
                self.accumulated_text + f"\n\u26a0\ufe0f Error: {error_msg[:200]}"
            )
            self._schedule(self._update_message(display))

    def _truncate(self, text: str) -> str:
        """Truncate text to Discord's message limit."""
        if len(text) <= self.MESSAGE_LIMIT:
            return text
        return text[: self.MESSAGE_LIMIT - 3] + "..."

    def _schedule(self, coro):
        """Schedule a coroutine on the Discord client's event loop."""
        try:
            import asyncio
            asyncio.run_coroutine_threadsafe(coro, self.loop)
        except Exception as e:
            logger.debug(f"Discord schedule failed: {e}")

    async def _update_message(self, text: str):
        """Send or edit the Discord message."""
        if not text.strip():
            return
        try:
            if self.message is None:
                self.message = await self.channel.send(text)
            else:
                await self.message.edit(content=text)
        except Exception as e:
            logger.debug(f"Discord edit failed: {e}")

    def unsubscribe(self):
        """Disconnect from the event bus."""
        self._unsub()
        self.accumulated_text = ""
        self.message = None
