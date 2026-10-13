"""
ARIA - Discord Bot
====================

Connects ARIA to Discord for real-time messaging.
Runs the discord.py client in a separate thread alongside the terminal interface.
Inherits from ChannelBase for unified channel interface.

Features:
    - Message debouncing (combines rapid messages)
    - Thread-aware routing (separate context per thread)
    - Auto-reconnect with exponential backoff
    - Markdown normalization for Discord
    - Streaming via EventBus + DiscordSubscriber

Usage:
    bot = DiscordBot(token="BOT_TOKEN", message_handler=handle, event_bus=bus)
    bot.start()
"""

import asyncio
import logging
import threading
import time
from typing import Callable, Optional, List, Set

from .channel_base import ChannelBase
from .debouncer import MessageDebouncer
from .formatters import to_discord_md

logger = logging.getLogger("aria.discord")


class DiscordBot(ChannelBase):
    """
    Discord bot that bridges messages to ARIA's conversation loop.

    Args:
        token: Discord bot token from Discord Developer Portal.
        message_handler: Callable(sender: str, text: str) -> str
        allowed_guild_ids: List of guild (server) IDs. Empty = accept all.
        allowed_channel_ids: List of channel IDs. Empty = accept all in allowed guilds.
        log_messages: Whether to log messages.
        event_bus: EventBus instance for streaming support.
    """

    channel_name = "discord"

    MESSAGE_LIMIT = 2000
    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2  # seconds

    def __init__(
        self,
        token: str,
        message_handler: Callable[[str, str], str],
        allowed_guild_ids: Optional[List[int]] = None,
        allowed_channel_ids: Optional[List[int]] = None,
        log_messages: bool = True,
        event_bus=None,
    ):
        super().__init__(message_handler=message_handler, log_messages=log_messages)
        self.token = token
        self.allowed_guild_ids: Set[int] = set(allowed_guild_ids or [])
        self.allowed_channel_ids: Set[int] = set(allowed_channel_ids or [])
        self.event_bus = event_bus

        self._client = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._debouncer = MessageDebouncer(window=2.0, max_batch=5)
        self._reconnect_attempts = 0

    # -------------------------------------------------------------------------
    # ChannelBase implementation
    # -------------------------------------------------------------------------

    def _do_start(self):
        self._thread = threading.Thread(
            target=self._run_client,
            name="aria-discord-bot",
            daemon=True,
        )
        self._thread.start()

    def _do_stop(self):
        self._debouncer.shutdown()
        if self._loop and self._client:
            asyncio.run_coroutine_threadsafe(self._client.close(), self._loop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _do_send(self, chat_id: str, text: str):
        if not self._loop or not self._client:
            return
        text = to_discord_md(text)
        asyncio.run_coroutine_threadsafe(
            self._async_send(int(chat_id), text), self._loop
        )

    def _do_health_check(self) -> bool:
        return (
            self._running
            and self._client is not None
            and self._loop is not None
            and not self._client.is_closed()
        )

    # -------------------------------------------------------------------------
    # Send helpers
    # -------------------------------------------------------------------------

    async def _async_send(self, channel_id: int, text: str):
        """Send a message with chunking for Discord's 2000 char limit."""
        try:
            channel = self._client.get_channel(channel_id)
            if channel is None:
                channel = await self._client.fetch_channel(channel_id)

            if len(text) <= self.MESSAGE_LIMIT:
                await channel.send(text)
            else:
                for chunk in self._split_message(text):
                    await channel.send(chunk)

            self._messages_out += 1
        except Exception as e:
            logger.error(f"Failed to send to channel {channel_id}: {e}")

    @staticmethod
    def _split_message(text: str, limit: int = 2000) -> list:
        """Split a long message into chunks respecting Discord's limit."""
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
    def _session_key(message) -> str:
        """Build a session key that isolates threads from main channels.

        Returns:
            "discord:<channel_id>" for normal channels/DMs
            "discord:<channel_id>:thread:<thread_id>" for threads
        """
        channel_id = message.channel.id

        # discord.py Thread objects have a parent_id
        if hasattr(message.channel, 'parent_id') and message.channel.parent_id:
            return f"discord:{message.channel.parent_id}:thread:{channel_id}"

        return f"discord:{channel_id}"

    # -------------------------------------------------------------------------
    # Client loop with auto-reconnect (Mejora 5)
    # -------------------------------------------------------------------------

    def _run_client(self):
        """Run the Discord client with auto-reconnect on failure."""
        while self._running or self._reconnect_attempts == 0:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            try:
                self._loop.run_until_complete(self._start_client())
            except Exception as e:
                logger.error(f"Discord bot error: {e}")

            # Clean up loop
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

            # Auto-reconnect with backoff
            if not self._running:
                break

            self._reconnect_attempts += 1
            if self._reconnect_attempts > self.MAX_RECONNECT_ATTEMPTS:
                logger.error(
                    f"Discord: max reconnect attempts ({self.MAX_RECONNECT_ATTEMPTS}) "
                    f"exhausted, giving up"
                )
                self._running = False
                self._record_error("Max reconnect attempts exhausted")
                break

            delay = self.RECONNECT_BASE_DELAY ** self._reconnect_attempts
            delay = min(delay, 60)  # Cap at 60s
            logger.warning(
                f"Discord: reconnecting in {delay}s "
                f"(attempt {self._reconnect_attempts}/{self.MAX_RECONNECT_ATTEMPTS})"
            )
            time.sleep(delay)

    async def _start_client(self):
        """Initialize and run the discord.py client."""
        import discord

        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True

        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot connected as {self._client.user}")
            self._running = True
            self._reconnect_attempts = 0  # Reset on successful connect

        @self._client.event
        async def on_message(message):
            await self._handle_message(message)

        @self._client.event
        async def on_disconnect():
            logger.warning("Discord bot disconnected")

        await self._client.start(self.token)

    # -------------------------------------------------------------------------
    # Message handler with debouncing (Mejora 1)
    # -------------------------------------------------------------------------

    async def _handle_message(self, message):
        """Handle incoming Discord messages with debouncing."""
        if message.author == self._client.user:
            return
        if message.author.bot:
            return

        if self.allowed_guild_ids and message.guild:
            if message.guild.id not in self.allowed_guild_ids:
                return
        if self.allowed_channel_ids:
            if message.channel.id not in self.allowed_channel_ids:
                return

        text = message.content.strip()
        if not text:
            return

        is_dm = message.guild is None
        is_mentioned = self._client.user in message.mentions

        if not is_dm and not is_mentioned:
            return

        if is_mentioned:
            text = text.replace(f"<@{self._client.user.id}>", "").strip()
            text = text.replace(f"<@!{self._client.user.id}>", "").strip()

        if not text:
            return

        username = str(message.author)
        user_id = str(message.author.id)
        chat_id = str(message.channel.id)

        if self._check_rate_limit(user_id, username):
            await message.channel.send("Too many messages. Please wait a moment.")
            return

        # Handle commands immediately (no debouncing)
        if text.startswith("!"):
            self._record_incoming(chat_id, username, text)
            await self._handle_command(message, text)
            return

        self._record_incoming(chat_id, username, text)

        # Debounce: combine rapid messages from same user in same channel
        debounce_key = f"discord:{user_id}:{chat_id}"
        channel = message.channel
        loop = asyncio.get_event_loop()

        def on_flush(key: str, combined_text: str):
            """Called by debouncer when batch is ready (from timer thread)."""
            asyncio.run_coroutine_threadsafe(
                self._process_debounced(channel, username, combined_text),
                loop,
            )

        self._debouncer.add(debounce_key, text, on_flush=on_flush)

    async def _process_debounced(self, channel, username: str, text: str):
        """Process a debounced (possibly combined) message."""
        # Streaming: create subscriber if event_bus available
        subscriber = None
        if self.event_bus:
            from .discord_subscriber import DiscordSubscriber
            subscriber = DiscordSubscriber(
                self.event_bus, channel, asyncio.get_event_loop()
            )

        try:
            async with channel.typing():
                response = await asyncio.get_event_loop().run_in_executor(
                    None, self._process_message, username, text
                )
        finally:
            if subscriber:
                subscriber.unsubscribe()

        # Only send full response if streaming didn't already do it
        if response and not subscriber:
            for chunk in self._split_message(to_discord_md(response)):
                await channel.send(chunk)
            self._messages_out += 1

        if response and self.log_messages:
            logger.info(f"[discord OUT] -> {username}: {response[:100]}")

    # -------------------------------------------------------------------------
    # Commands
    # -------------------------------------------------------------------------

    async def _handle_command(self, message, text: str):
        """Handle !command messages."""
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        username = str(message.author)
        chat_id = str(message.channel.id)

        if cmd == "status":
            s = self.stats()
            uptime_min = s["uptime_seconds"] // 60
            uptime_hrs = uptime_min // 60
            uptime_min = uptime_min % 60
            await message.channel.send(
                f"**ARIA - Status**\n"
                f"Uptime: {uptime_hrs}h {uptime_min}m\n"
                f"Messages received: {s['messages_received']}\n"
                f"Messages sent: {s['messages_sent']}\n"
                f"Active channels: {s['active_chats']}"
            )

        elif cmd == "help":
            await message.channel.send(
                "**ARIA - Discord**\n\n"
                "Mention me or DM me to chat.\n"
                "I can use tools automatically to help you.\n\n"
                "**Commands:**\n"
                "`!status` - Show my status\n"
                "`!tools` - List available tools\n"
                "`!search [query]` - Web search\n"
                "`!help` - This help"
            )

        elif cmd == "tools":
            response = await asyncio.get_event_loop().run_in_executor(
                None, self._process_message, "system", "/tools"
            )
            if response:
                for chunk in self._split_message(to_discord_md(response)):
                    await message.channel.send(chunk)

        elif cmd == "search" and arg:
            self._record_incoming(chat_id, username, f"!search {arg}")
            async with message.channel.typing():
                response = await asyncio.get_event_loop().run_in_executor(
                    None, self._process_message, username, f"/search {arg}"
                )
            if response:
                for chunk in self._split_message(to_discord_md(response)):
                    await message.channel.send(chunk)

        else:
            self._record_incoming(chat_id, username, text)
            async with message.channel.typing():
                response = await asyncio.get_event_loop().run_in_executor(
                    None, self._process_message, username, text[1:]
                )
            if response:
                for chunk in self._split_message(to_discord_md(response)):
                    await message.channel.send(chunk)
