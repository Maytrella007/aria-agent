"""
Tests for ARIA Telegram Bot
=============================

Tests for message handling, user filtering, stats, and lifecycle.
Uses asyncio.run() directly to avoid pytest-asyncio version issues.
"""

import pytest
import os
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channels.telegram_bot import TelegramBot


# =============================================================================
# HELPERS
# =============================================================================

def run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture(autouse=True)
def event_loop():
    """Ensure a fresh event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def make_handler():
    """Simple echo handler."""
    def _handler(sender, text):
        return f"Echo: {text}"
    return _handler


_active_bots = []


@pytest.fixture(autouse=True)
def cleanup_bots():
    """Shutdown debouncers after each test to avoid timer warnings."""
    _active_bots.clear()
    yield
    for bot in _active_bots:
        bot._debouncer.shutdown()
    _active_bots.clear()


def make_bot(**kwargs):
    defaults = dict(
        token="fake-token-123",
        message_handler=make_handler(),
        allowed_users=[],
        log_messages=False,
    )
    defaults.update(kwargs)
    bot = TelegramBot(**defaults)
    _active_bots.append(bot)
    return bot


def make_update(text="hello", user_id=123, username="testuser", chat_id=456):
    """Create a mock Telegram Update object."""
    update = AsyncMock()
    update.message.text = text
    update.message.from_user.id = user_id
    update.message.from_user.username = username
    update.message.from_user.first_name = "Test"
    update.message.chat_id = chat_id
    update.message.reply_text = AsyncMock()
    return update


def make_context():
    """Create a mock context."""
    context = AsyncMock()
    context.bot.send_chat_action = AsyncMock()
    return context


# =============================================================================
# INITIALIZATION TESTS
# =============================================================================

class TestTelegramBotInit:
    def test_init_defaults(self):
        bot = TelegramBot(token="tok", message_handler=make_handler())
        assert bot.token == "tok"
        assert bot.allowed_users == set()
        assert bot.log_messages is True
        assert bot.is_running is False

    def test_init_with_allowed_users(self):
        bot = TelegramBot(
            token="tok",
            message_handler=make_handler(),
            allowed_users=[111, 222],
        )
        assert bot.allowed_users == {111, 222}

    def test_not_running_initially(self):
        bot = make_bot()
        assert bot.is_running is False


# =============================================================================
# STATS TESTS
# =============================================================================

class TestStats:
    def test_initial_stats(self):
        bot = make_bot()
        s = bot.stats()
        assert s["running"] is False
        assert s["uptime_seconds"] == 0
        assert s["messages_received"] == 0
        assert s["messages_sent"] == 0
        assert s["active_chats"] == 0

    def test_active_chats_tracking(self):
        bot = make_bot()
        assert len(bot.get_active_chat_ids()) == 0
        bot._active_chats.add(100)
        bot._active_chats.add(200)
        assert len(bot.get_active_chat_ids()) == 2
        assert 100 in bot.get_active_chat_ids()


# =============================================================================
# MESSAGE HANDLING TESTS
# =============================================================================

class TestMessageHandling:
    def test_handle_message_records_incoming(self, event_loop):
        """Test that _handle_message records the incoming message."""
        bot = make_bot()
        update = make_update(text="test message")
        context = make_context()
        bot._async_send = AsyncMock()
        bot._app = Mock()
        bot._app.bot = context.bot

        event_loop.run_until_complete(bot._handle_message(update, context))

        assert bot._messages_in == 1
        assert "456" in bot._active_chats

    def test_handle_empty_message_ignored(self, event_loop):
        bot = make_bot()
        update = make_update(text="")
        context = make_context()
        bot._async_send = AsyncMock()

        event_loop.run_until_complete(bot._handle_message(update, context))
        assert bot._messages_in == 0

    def test_handle_none_message_ignored(self, event_loop):
        bot = make_bot()
        update = AsyncMock()
        update.message = None
        context = make_context()

        event_loop.run_until_complete(bot._handle_message(update, context))
        assert bot._messages_in == 0

    def test_handler_error_returns_error_message(self, event_loop):
        """Test that a handler error produces an error response via debounced processing."""
        def bad_handler(sender, text):
            raise Exception("LLM is down")

        bot = make_bot(message_handler=bad_handler)
        update = make_update()
        context = make_context()
        bot._async_send = AsyncMock()
        bot._app = Mock()
        bot._app.bot = context.bot

        # _handle_message queues into debouncer; flush to trigger processing
        event_loop.run_until_complete(bot._handle_message(update, context))

        # Flush the debouncer to trigger processing immediately
        debounce_key = "telegram:123:456"
        combined = bot._debouncer.flush_now(debounce_key)
        assert combined is not None

        # Process the debounced message directly
        event_loop.run_until_complete(
            bot._process_debounced(context.bot, 456, "testuser", combined)
        )

        bot._async_send.assert_called_once()
        args = bot._async_send.call_args
        assert "Error" in args[0][1]

    def test_debouncer_combines_messages(self, event_loop):
        """Test that rapid messages are combined by the debouncer."""
        bot = make_bot()
        update1 = make_update(text="first")
        update2 = make_update(text="second")
        context = make_context()
        bot._async_send = AsyncMock()
        bot._app = Mock()
        bot._app.bot = context.bot

        event_loop.run_until_complete(bot._handle_message(update1, context))
        event_loop.run_until_complete(bot._handle_message(update2, context))

        # Flush to get combined message
        debounce_key = "telegram:123:456"
        combined = bot._debouncer.flush_now(debounce_key)
        assert combined == "first\nsecond"


# =============================================================================
# USER FILTERING TESTS
# =============================================================================

class TestUserFiltering:
    def test_allowed_user_passes(self, event_loop):
        bot = make_bot(allowed_users=[111, 222])
        update = make_update(user_id=111)
        context = make_context()
        bot._async_send = AsyncMock()
        bot._app = Mock()
        bot._app.bot = context.bot

        event_loop.run_until_complete(bot._handle_message(update, context))
        assert bot._messages_in == 1

    def test_unauthorized_user_rejected(self, event_loop):
        bot = make_bot(allowed_users=[111, 222])
        update = make_update(user_id=999)
        context = make_context()

        event_loop.run_until_complete(bot._handle_message(update, context))

        update.message.reply_text.assert_called_once()
        assert bot._messages_in == 0

    def test_empty_allowed_list_accepts_all(self, event_loop):
        bot = make_bot(allowed_users=[])
        update = make_update(user_id=999)
        context = make_context()
        bot._async_send = AsyncMock()
        bot._app = Mock()
        bot._app.bot = context.bot

        event_loop.run_until_complete(bot._handle_message(update, context))
        assert bot._messages_in == 1


# =============================================================================
# COMMAND TESTS
# =============================================================================

class TestCommands:
    def test_start_command(self, event_loop):
        bot = make_bot()
        update = make_update()
        context = make_context()

        event_loop.run_until_complete(bot._cmd_start(update, context))

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "ARIA" in msg

    def test_status_command(self, event_loop):
        bot = make_bot()
        update = make_update()
        context = make_context()
        bot._running = True
        bot._started_at = 1000000000.0

        event_loop.run_until_complete(bot._cmd_status(update, context))

        update.message.reply_text.assert_called_once()

    def test_help_command(self, event_loop):
        bot = make_bot()
        update = make_update()
        context = make_context()

        event_loop.run_until_complete(bot._cmd_help(update, context))

        update.message.reply_text.assert_called_once()
        msg = update.message.reply_text.call_args[0][0]
        assert "/start" in msg
        assert "/status" in msg


# =============================================================================
# SEND & LIFECYCLE TESTS
# =============================================================================

class TestSendAndLifecycle:
    def test_send_when_not_running_warns(self):
        bot = make_bot()
        bot.send(123, "hello")  # should not crash

    def test_stop_when_not_running(self):
        bot = make_bot()
        bot.stop()  # should not crash
        assert bot.is_running is False

    def test_double_start_warns(self):
        bot = make_bot()
        bot._running = True
        bot.start()  # should not start second thread
