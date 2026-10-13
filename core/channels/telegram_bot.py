"""
ARIA - Telegram Bot
====================

Connects ARIA to Telegram for real-time messaging.
Runs polling in a separate thread alongside the terminal interface.
Inherits from ChannelBase for unified channel interface.

Usage:
    def handle(sender, text):
        return "ARIA's response"

    bot = TelegramBot(token="BOT_TOKEN", message_handler=handle)
    bot.start()
    # ... ARIA runs ...
    bot.stop()
"""

import asyncio
import logging
import threading
import time
from typing import Callable, Optional, List, Set

from .channel_base import ChannelBase
from .debouncer import MessageDebouncer
from .formatters import to_telegram_md

logger = logging.getLogger("aria.telegram")


class TelegramBot(ChannelBase):
    """
    Telegram bot that bridges messages to ARIA's conversation loop.

    Args:
        token: Telegram bot token from @BotFather
        message_handler: Callable(sender: str, text: str) -> str
        allowed_users: List of Telegram user IDs. Empty = accept all.
        log_messages: Whether to log messages.
    """

    channel_name = "telegram"

    MAX_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2

    def __init__(
        self,
        token: str,
        message_handler: Callable[[str, str], str],
        allowed_users: Optional[List[int]] = None,
        log_messages: bool = True,
        event_bus=None,
    ):
        super().__init__(message_handler=message_handler, log_messages=log_messages)
        self.token = token
        self.allowed_users: Set[int] = set(allowed_users or [])
        self.event_bus = event_bus

        self._app = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._debouncer = MessageDebouncer(window=1.5, max_batch=5)
        self._reconnect_attempts = 0

    # -------------------------------------------------------------------------
    # ChannelBase implementation
    # -------------------------------------------------------------------------

    def _do_start(self):
        """Start polling in a background thread."""
        self._thread = threading.Thread(
            target=self._run_polling,
            name="aria-telegram-bot",
            daemon=True,
        )
        self._thread.start()

    def _do_stop(self):
        """Stop polling gracefully."""
        self._debouncer.shutdown()
        if self._loop and self._app:
            asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def _do_send(self, chat_id: str, text: str):
        """Send a message via Telegram."""
        if not self._loop or not self._app:
            return
        text = to_telegram_md(text)
        asyncio.run_coroutine_threadsafe(
            self._async_send(int(chat_id), text), self._loop
        )

    def _do_health_check(self) -> bool:
        """Check if Telegram bot is still connected."""
        return self._running and self._app is not None and self._loop is not None

    # -------------------------------------------------------------------------
    # Telegram-specific send
    # -------------------------------------------------------------------------

    async def _async_send(self, chat_id: int, text: str):
        """Async send with markdown fallback and message splitting."""
        try:
            bot = self._app.bot
            if len(text) <= 4096:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode="Markdown",
                )
            else:
                for i in range(0, len(text), 4096):
                    chunk = text[i:i + 4096]
                    await bot.send_message(chat_id=chat_id, text=chunk)
            self._messages_out += 1
        except Exception:
            # Retry without markdown if parse fails
            try:
                await self._app.bot.send_message(chat_id=chat_id, text=text)
                self._messages_out += 1
            except Exception as e2:
                logger.error(f"Failed to send to {chat_id}: {e2}")

    async def _async_send_streaming(self, chat_id: int, text_generator):
        """Send a streaming response by editing a message progressively.

        Inspired by OpenClaw's edit-based streaming:
        - Send initial message with indicator
        - Edit every ~1 second with accumulated text
        - Final edit removes indicator

        Args:
            chat_id: Telegram chat ID
            text_generator: Generator yielding (text_delta, is_done) tuples
        """
        import time as _time

        bot = self._app.bot
        accumulated = ""
        msg = None
        last_edit = 0
        EDIT_INTERVAL = 1.0  # Edit at most once per second (Telegram rate limit)

        try:
            for delta, is_done in text_generator:
                accumulated += delta

                now = _time.time()

                if msg is None and accumulated:
                    # Send initial message
                    try:
                        msg = await bot.send_message(
                            chat_id=chat_id,
                            text=accumulated + " ▍",
                        )
                        last_edit = now
                    except Exception as e:
                        logger.error(f"Streaming initial send failed: {e}")
                        break

                elif msg and not is_done and (now - last_edit) >= EDIT_INTERVAL:
                    # Progressive edit
                    display = accumulated[:4090] + " ▍"
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=msg.message_id,
                            text=display,
                        )
                        last_edit = now
                    except Exception:
                        pass  # Edit failures are non-critical

                if is_done:
                    break

            # Final edit — clean text without indicator
            if msg and accumulated:
                try:
                    final = accumulated[:4096]
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg.message_id,
                        text=final,
                        parse_mode="Markdown",
                    )
                except Exception:
                    try:
                        await bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=msg.message_id,
                            text=accumulated[:4096],
                        )
                    except Exception:
                        pass

            self._messages_out += 1

        except Exception as e:
            logger.error(f"Streaming send failed: {e}")
            # Fallback: send whatever we have
            if accumulated and not msg:
                await self._async_send(chat_id, accumulated)

    # -------------------------------------------------------------------------
    # Polling loop
    # -------------------------------------------------------------------------

    def _run_polling(self):
        """Run the bot polling loop with auto-reconnect on failure."""
        while self._running or self._reconnect_attempts == 0:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            try:
                self._loop.run_until_complete(self._start_polling())
            except Exception as e:
                logger.error(f"Telegram bot error: {e}")

            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None

            if not self._running:
                break

            self._reconnect_attempts += 1
            if self._reconnect_attempts > self.MAX_RECONNECT_ATTEMPTS:
                logger.error(
                    f"Telegram: max reconnect attempts "
                    f"({self.MAX_RECONNECT_ATTEMPTS}) exhausted"
                )
                self._running = False
                self._record_error("Max reconnect attempts exhausted")
                break

            delay = min(self.RECONNECT_BASE_DELAY ** self._reconnect_attempts, 60)
            logger.warning(
                f"Telegram: reconnecting in {delay}s "
                f"(attempt {self._reconnect_attempts}/{self.MAX_RECONNECT_ATTEMPTS})"
            )
            time.sleep(delay)

    async def _start_polling(self):
        """Initialize and start the telegram application."""
        from telegram.ext import (
            ApplicationBuilder,
            CommandHandler,
            MessageHandler,
            filters,
        )

        self._app = (
            ApplicationBuilder()
            .token(self.token)
            .build()
        )

        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("tools", self._cmd_tools))
        self._app.add_handler(CommandHandler("search", self._cmd_passthrough))
        self._app.add_handler(CommandHandler("calc", self._cmd_passthrough))
        self._app.add_handler(CommandHandler("todo", self._cmd_passthrough))
        self._app.add_handler(CommandHandler("sysinfo", self._cmd_passthrough))
        self._app.add_handler(
            MessageHandler(
                filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
                self._handle_message,
            )
        )

        self._running = True
        self._reconnect_attempts = 0  # Reset on successful connect

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        while self._running:
            await asyncio.sleep(0.5)

        await self._shutdown()

    async def _shutdown(self):
        """Shutdown gracefully."""
        try:
            if self._app and self._app.updater.running:
                await self._app.updater.stop()
            if self._app and self._app.running:
                await self._app.stop()
                await self._app.shutdown()
        except Exception as e:
            logger.debug(f"Shutdown cleanup: {e}")

    # -------------------------------------------------------------------------
    # Message handlers
    # -------------------------------------------------------------------------

    async def _handle_message(self, update, context):
        """Handle incoming text messages with debouncing."""
        if not update.message or not update.message.text:
            return

        user = update.message.from_user
        chat_id = update.message.chat_id
        text = update.message.text.strip()
        username = user.username or user.first_name or str(user.id)

        if self.allowed_users and user.id not in self.allowed_users:
            await update.message.reply_text(
                "No estás autorizado para hablar con ARIA."
            )
            logger.warning(f"Unauthorized user: {username} ({user.id})")
            return

        if not text:
            return

        # Rate limiting
        if self._check_rate_limit(str(user.id), username):
            await update.message.reply_text(
                "Demasiados mensajes. Espera un momento."
            )
            return

        self._record_incoming(str(chat_id), username, text)

        # Debounce: combine rapid messages from same user
        debounce_key = f"telegram:{user.id}:{chat_id}"
        loop = asyncio.get_event_loop()
        bot = context.bot

        def on_flush(key: str, combined_text: str):
            asyncio.run_coroutine_threadsafe(
                self._process_debounced(bot, chat_id, username, combined_text),
                loop,
            )

        self._debouncer.add(debounce_key, text, on_flush=on_flush)

    async def _process_debounced(self, bot, chat_id: int, username: str, text: str):
        """Process a debounced (possibly combined) message with streaming."""
        await bot.send_chat_action(chat_id=chat_id, action="typing")

        # Streaming: create subscriber if event_bus available
        subscriber = None
        if self.event_bus:
            from .telegram_subscriber import TelegramSubscriber
            subscriber = TelegramSubscriber(self.event_bus, bot, chat_id)

        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, self._process_message, username, text
            )
        finally:
            if subscriber:
                subscriber.unsubscribe()

        # Only send full response if streaming didn't already do it
        if response and not subscriber:
            await self._async_send(chat_id, response)

        if response and self.log_messages:
            logger.info(f"[telegram OUT] -> {username}: {response[:100]}")

    async def _cmd_start(self, update, context):
        """Handle /start command."""
        user = update.message.from_user
        username = user.first_name or user.username or "there"
        self._active_chats.add(str(update.message.chat_id))

        await update.message.reply_text(
            f"Hola {username}, soy ARIA.\n"
            f"Puedes escribirme directamente y te responderé.\n\n"
            f"Comandos:\n"
            f"/status - Mi estado actual\n"
            f"/help - Ayuda"
        )

    async def _cmd_status(self, update, context):
        """Handle /status command."""
        s = self.stats()
        uptime_min = s["uptime_seconds"] // 60
        uptime_hrs = uptime_min // 60
        uptime_min = uptime_min % 60

        await update.message.reply_text(
            f"*ARIA - Estado*\n"
            f"Uptime: {uptime_hrs}h {uptime_min}m\n"
            f"Mensajes recibidos: {s['messages_received']}\n"
            f"Mensajes enviados: {s['messages_sent']}\n"
            f"Chats activos: {s['active_chats']}",
            parse_mode="Markdown",
        )

    async def _cmd_help(self, update, context):
        """Handle /help command."""
        await update.message.reply_text(
            "*ARIA - Telegram*\n\n"
            "Escríbeme cualquier cosa y te responderé.\n"
            "Puedo usar herramientas automáticamente para ayudarte.\n\n"
            "*Comandos:*\n"
            "/start - Iniciar conversación\n"
            "/status - Ver mi estado\n"
            "/tools - Lista de herramientas\n"
            "/search [query] - Buscar en la web\n"
            "/calc [expr] - Calcular expresión\n"
            "/todo [add/done] - Lista de tareas\n"
            "/sysinfo - Info del sistema\n"
            "/help - Esta ayuda",
            parse_mode="Markdown",
        )

    async def _cmd_tools(self, update, context):
        """Handle /tools command — list available tools."""
        response = await asyncio.get_event_loop().run_in_executor(
            None, self._process_message, "system", "/tools"
        )
        if response:
            await self._async_send(update.message.chat_id, response)

    async def _cmd_passthrough(self, update, context):
        """Pass /command args directly to ARIA's handler as '/command args'."""
        if not update.message or not update.message.text:
            return

        user = update.message.from_user
        chat_id = update.message.chat_id
        text = update.message.text.strip()
        username = user.username or user.first_name or str(user.id)

        if self.allowed_users and user.id not in self.allowed_users:
            await update.message.reply_text("No estás autorizado.")
            return

        if self._check_rate_limit(str(user.id), username):
            await update.message.reply_text("Demasiados mensajes. Espera un momento.")
            return

        self._record_incoming(str(chat_id), username, text)
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")

        response = await asyncio.get_event_loop().run_in_executor(
            None, self._process_message, username, text
        )
        if response:
            await self._async_send(chat_id, response)
