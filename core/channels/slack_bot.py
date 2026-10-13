"""
ARIA - Slack Bot
=================

Connects ARIA to Slack for real-time messaging.
Uses slack-bolt with Socket Mode (no public endpoint needed).
Inherits from ChannelBase for unified channel interface.

Features:
    - Message debouncing (combines rapid messages)
    - Thread-aware routing (separate context per thread)
    - Auto-reconnect via Socket Mode (built-in) + logging
    - Markdown normalization (mrkdwn format)
    - Streaming via EventBus + SlackSubscriber
    - Username cache with TTL

Usage:
    bot = SlackBot(
        bot_token="xoxb-...",
        app_token="xapp-...",
        message_handler=handle,
        event_bus=bus,
    )
    bot.start()

Requires:
    pip install slack-bolt
"""

import logging
import threading
import time
from typing import Callable, Optional, List, Set, Dict, Tuple

from .channel_base import ChannelBase
from .debouncer import MessageDebouncer
from .formatters import to_slack_mrkdwn

logger = logging.getLogger("aria.slack")


class SlackBot(ChannelBase):
    """
    Slack bot that bridges messages to ARIA's conversation loop.

    Uses Socket Mode so no public URL is needed — just an app-level token.

    Args:
        bot_token: Slack Bot User OAuth Token (xoxb-...).
        app_token: Slack App-Level Token (xapp-...) for Socket Mode.
        message_handler: Callable(sender: str, text: str) -> str
        allowed_channel_ids: List of channel IDs. Empty = accept all.
        log_messages: Whether to log messages.
        event_bus: EventBus instance for streaming support.
    """

    channel_name = "slack"

    MESSAGE_LIMIT = 4000
    USERNAME_CACHE_TTL = 3600  # 1 hour

    def __init__(
        self,
        bot_token: str,
        app_token: str,
        message_handler: Callable[[str, str], str],
        allowed_channel_ids: Optional[List[str]] = None,
        log_messages: bool = True,
        event_bus=None,
    ):
        super().__init__(message_handler=message_handler, log_messages=log_messages)
        self.bot_token = bot_token
        self.app_token = app_token
        self.allowed_channel_ids: Set[str] = set(allowed_channel_ids or [])
        self.event_bus = event_bus

        self._app = None
        self._handler = None
        self._thread: Optional[threading.Thread] = None
        self._bot_user_id: Optional[str] = None
        self._debouncer = MessageDebouncer(window=2.0, max_batch=5)

        # Username cache: user_id -> (display_name, timestamp)
        self._username_cache: Dict[str, Tuple[str, float]] = {}
        self._cache_lock = threading.Lock()

    # -------------------------------------------------------------------------
    # ChannelBase implementation
    # -------------------------------------------------------------------------

    def _do_start(self):
        self._thread = threading.Thread(
            target=self._run_socket_mode,
            name="aria-slack-bot",
            daemon=True,
        )
        self._thread.start()

    def _do_stop(self):
        self._debouncer.shutdown()
        if self._handler:
            try:
                self._handler.close()
            except Exception as e:
                logger.debug(f"Slack handler close: {e}")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _do_send(self, chat_id: str, text: str):
        if not self._app:
            return
        text = to_slack_mrkdwn(text)
        try:
            if len(text) <= self.MESSAGE_LIMIT:
                self._app.client.chat_postMessage(channel=chat_id, text=text)
            else:
                for chunk in self._split_message(text):
                    self._app.client.chat_postMessage(channel=chat_id, text=chunk)
            self._messages_out += 1
        except Exception as e:
            logger.error(f"Slack send error to {chat_id}: {e}")

    def _do_health_check(self) -> bool:
        if not self._app:
            return False
        try:
            result = self._app.client.auth_test()
            return result.get("ok", False)
        except Exception:
            return False

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _split_message(text: str, limit: int = 4000) -> list:
        chunks = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            split_at = text.rfind("\n", 0, limit)
            if split_at == -1:
                split_at = limit
            chunks.append(text[:split_at])
            text = text[split_at:].lstrip("\n")
        return chunks

    # -------------------------------------------------------------------------
    # Thread-aware session key (Mejora 4)
    # -------------------------------------------------------------------------

    @staticmethod
    def _session_key(event: dict) -> str:
        """Build session key from Slack event, isolating threads.

        Returns:
            "slack:<channel>" for top-level messages
            "slack:<channel>:thread:<thread_ts>" for threaded replies
        """
        channel = event.get("channel", "unknown")
        thread_ts = event.get("thread_ts")

        if thread_ts:
            return f"slack:{channel}:thread:{thread_ts}"
        return f"slack:{channel}"

    # -------------------------------------------------------------------------
    # Username cache (Mejora 3)
    # -------------------------------------------------------------------------

    def _resolve_username(self, user_id: str) -> str:
        """Resolve a Slack user ID to a display name with caching."""
        now = time.time()

        with self._cache_lock:
            if user_id in self._username_cache:
                name, cached_at = self._username_cache[user_id]
                if now - cached_at < self.USERNAME_CACHE_TTL:
                    return name
                # Expired, will re-fetch below

        if not self._app:
            return user_id

        try:
            result = self._app.client.users_info(user=user_id)
            if result.get("ok"):
                user = result["user"]
                name = (
                    user.get("real_name")
                    or user.get("profile", {}).get("display_name")
                    or user.get("name")
                    or user_id
                )
                with self._cache_lock:
                    self._username_cache[user_id] = (name, now)
                return name
        except Exception:
            pass

        return user_id

    # -------------------------------------------------------------------------
    # Socket Mode loop with reconnect logging (Mejora 5)
    # -------------------------------------------------------------------------

    def _run_socket_mode(self):
        """Run Slack bolt app with Socket Mode.

        Socket Mode's SocketModeHandler handles reconnection internally.
        We add logging and error tracking on top.
        """
        reconnect_count = 0
        max_reconnects = 5

        while self._running or reconnect_count == 0:
            try:
                from slack_bolt import App
                from slack_bolt.adapter.socket_mode import SocketModeHandler

                self._app = App(token=self.bot_token)

                # Get bot user ID for mention detection
                try:
                    auth = self._app.client.auth_test()
                    self._bot_user_id = auth.get("user_id")
                    logger.info(f"Slack bot connected as {auth.get('user', 'unknown')}")
                except Exception as e:
                    logger.warning(f"Could not get bot user ID: {e}")

                self._register_handlers()

                self._running = True
                reconnect_count = 0  # Reset on successful setup
                self._handler = SocketModeHandler(self._app, self.app_token)
                self._handler.start()  # Blocks until close()
                break  # Normal exit via close()

            except Exception as e:
                logger.error(f"Slack bot error: {e}")
                self._record_error(str(e))

                if not self._running:
                    break

                reconnect_count += 1
                if reconnect_count > max_reconnects:
                    logger.error(
                        f"Slack: max reconnect attempts ({max_reconnects}) exhausted"
                    )
                    self._running = False
                    break

                delay = min(2 ** reconnect_count, 60)
                logger.warning(
                    f"Slack: reconnecting in {delay}s "
                    f"(attempt {reconnect_count}/{max_reconnects})"
                )
                time.sleep(delay)

        self._running = False

    def _register_handlers(self):
        """Register all Slack event and command handlers."""

        @self._app.event("message")
        def handle_message(event, say):
            self._handle_message_event(event, say)

        @self._app.event("app_mention")
        def handle_mention(event, say):
            self._handle_message_event(event, say, is_mention=True)

        @self._app.command("/aria-status")
        def handle_status(ack, respond):
            ack()
            s = self.stats()
            uptime_min = s["uptime_seconds"] // 60
            uptime_hrs = uptime_min // 60
            uptime_min = uptime_min % 60
            respond(
                f"*ARIA - Status*\n"
                f"Uptime: {uptime_hrs}h {uptime_min}m\n"
                f"Messages received: {s['messages_received']}\n"
                f"Messages sent: {s['messages_sent']}\n"
                f"Active channels: {s['active_chats']}"
            )

        @self._app.command("/aria-help")
        def handle_help(ack, respond):
            ack()
            respond(
                "*ARIA - Slack*\n\n"
                "Mention me or DM me to chat.\n"
                "I can use tools automatically to help you.\n\n"
                "*Commands:*\n"
                "`/aria-status` - Show my status\n"
                "`/aria-help` - This help"
            )

    # -------------------------------------------------------------------------
    # Message handler with debouncing (Mejora 1)
    # -------------------------------------------------------------------------

    def _handle_message_event(self, event: dict, say, is_mention: bool = False):
        """Handle incoming Slack message with debouncing."""
        if event.get("bot_id") or event.get("subtype"):
            return

        text = event.get("text", "").strip()
        if not text:
            return

        channel = event.get("channel", "")
        user_id = event.get("user", "unknown")

        if self.allowed_channel_ids and channel not in self.allowed_channel_ids:
            return

        channel_type = event.get("channel_type", "")
        is_dm = channel_type in ("im", "mpim")

        if not is_dm and not is_mention:
            if self._bot_user_id and f"<@{self._bot_user_id}>" not in text:
                return

        if self._bot_user_id:
            text = text.replace(f"<@{self._bot_user_id}>", "").strip()

        if not text:
            return

        username = self._resolve_username(user_id)

        if self._check_rate_limit(user_id, username):
            say("Too many messages. Please wait a moment.")
            return

        self._record_incoming(channel, username, text)

        # Debounce: combine rapid messages from same user in same channel
        debounce_key = f"slack:{user_id}:{channel}"
        thread_ts = event.get("thread_ts")

        def on_flush(key: str, combined_text: str):
            """Called by debouncer when batch is ready."""
            self._process_debounced(
                channel, username, combined_text, say, thread_ts
            )

        self._debouncer.add(debounce_key, text, on_flush=on_flush)

    def _process_debounced(
        self, channel: str, username: str, text: str, say, thread_ts=None
    ):
        """Process a debounced (possibly combined) message with streaming."""
        # Streaming: create subscriber if event_bus available
        subscriber = None
        if self.event_bus and self._app:
            from .slack_subscriber import SlackSubscriber
            subscriber = SlackSubscriber(
                self.event_bus, self._app.client, channel
            )

        try:
            response = self._process_message(username, text)
        finally:
            if subscriber:
                subscriber.unsubscribe()

        # Only send full response if streaming didn't already do it
        if response and not subscriber:
            for chunk in self._split_message(to_slack_mrkdwn(response)):
                if thread_ts:
                    self._app.client.chat_postMessage(
                        channel=channel, text=chunk, thread_ts=thread_ts
                    )
                else:
                    say(chunk)
            self._messages_out += 1

        if response and self.log_messages:
            logger.info(f"[slack OUT] -> {username}: {response[:100]}")
