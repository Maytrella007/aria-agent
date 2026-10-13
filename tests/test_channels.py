"""
Tests for ARIA Channels Module
================================

Tests for formatters, debouncer, channel_base, and channel_manager.
No real Telegram/Discord/Slack connections — everything is mocked.
"""

import os
import sys
import time
import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.channels.formatters import to_telegram_md, to_discord_md, to_slack_mrkdwn
from core.channels.debouncer import MessageDebouncer
from core.channels.channel_base import ChannelBase, ChannelMessage


# =============================================================================
# CONCRETE CHANNEL SUBCLASS (for testing ChannelBase)
# =============================================================================

class ConcreteChannel(ChannelBase):
    """Minimal concrete implementation for testing the abstract base."""

    channel_name = "test"

    def __init__(self, handler=None, **kwargs):
        super().__init__(
            message_handler=handler or (lambda sender, text: f"echo: {text}"),
            health_interval=0,  # disable background health thread
            **kwargs,
        )
        self.sent_messages = []

    def _do_start(self):
        pass

    def _do_stop(self):
        pass

    def _do_send(self, chat_id: str, text: str):
        self.sent_messages.append((chat_id, text))


# =============================================================================
# FORMATTERS — to_telegram_md
# =============================================================================

class TestToTelegramMd:
    """Tests for to_telegram_md()."""

    def test_empty_string(self):
        assert to_telegram_md("") == ""

    def test_none_passthrough(self):
        # Empty string is falsy, function returns it as-is
        assert to_telegram_md("") == ""

    def test_plain_text_unchanged(self):
        assert to_telegram_md("Hello world") == "Hello world"

    def test_heading_to_bold(self):
        assert to_telegram_md("# Title") == "*Title*"
        assert to_telegram_md("## Subtitle") == "*Subtitle*"
        assert to_telegram_md("### Deep heading") == "*Deep heading*"

    def test_bold_double_star_to_single(self):
        assert to_telegram_md("**bold text**") == "*bold text*"

    def test_bold_underscore_to_single_star(self):
        assert to_telegram_md("__bold text__") == "*bold text*"

    def test_code_block_preserved(self):
        text = "before\n```python\nprint('hi')\n```\nafter"
        result = to_telegram_md(text)
        assert "```python" in result
        assert "print('hi')" in result

    def test_links_preserved(self):
        text = "Check [ARIA](https://github.com/aria)"
        result = to_telegram_md(text)
        assert "[ARIA](https://github.com/aria)" in result

    def test_multiline_with_heading_and_bold(self):
        text = "# Header\nSome **bold** text"
        result = to_telegram_md(text)
        lines = result.split("\n")
        assert lines[0] == "*Header*"
        assert lines[1] == "Some *bold* text"


# =============================================================================
# FORMATTERS — to_discord_md
# =============================================================================

class TestToDiscordMd:
    """Tests for to_discord_md()."""

    def test_empty_string(self):
        assert to_discord_md("") == ""

    def test_plain_text_unchanged(self):
        assert to_discord_md("No formatting here") == "No formatting here"

    def test_heading_to_bold(self):
        assert to_discord_md("# Title") == "**Title**"
        assert to_discord_md("## Subtitle") == "**Subtitle**"
        assert to_discord_md("###### H6") == "**H6**"

    def test_code_block_preserved(self):
        text = "```js\nconsole.log('hi')\n```"
        result = to_discord_md(text)
        assert "```js" in result
        assert "console.log('hi')" in result

    def test_bold_passes_through(self):
        # Discord supports standard **bold** natively, no conversion needed
        text = "This is **important**"
        result = to_discord_md(text)
        assert "**important**" in result


# =============================================================================
# FORMATTERS — to_slack_mrkdwn
# =============================================================================

class TestToSlackMrkdwn:
    """Tests for to_slack_mrkdwn()."""

    def test_empty_string(self):
        assert to_slack_mrkdwn("") == ""

    def test_plain_text_unchanged(self):
        assert to_slack_mrkdwn("Hello world") == "Hello world"

    def test_bold_conversion(self):
        assert to_slack_mrkdwn("**bold**") == "*bold*"

    def test_bold_underscore_conversion(self):
        assert to_slack_mrkdwn("__bold__") == "*bold*"

    def test_heading_to_bold(self):
        assert to_slack_mrkdwn("# Title") == "*Title*"

    def test_link_conversion(self):
        text = "[Click here](https://example.com)"
        assert to_slack_mrkdwn(text) == "<https://example.com|Click here>"

    def test_strikethrough_conversion(self):
        assert to_slack_mrkdwn("~~removed~~") == "~removed~"

    def test_code_block_preserved(self):
        text = "before ```code here``` after"
        result = to_slack_mrkdwn(text)
        assert "```code here```" in result

    def test_inline_code_preserved(self):
        text = "Run `npm install` first"
        result = to_slack_mrkdwn(text)
        assert "`npm install`" in result

    def test_nested_bold_inside_text(self):
        text = "This has **multiple** bold **words** here"
        result = to_slack_mrkdwn(text)
        assert "*multiple*" in result
        assert "*words*" in result
        assert "**" not in result

    def test_code_block_contents_not_converted(self):
        """Bold markers inside code blocks should NOT be converted."""
        text = "```\n**not bold**\n```"
        result = to_slack_mrkdwn(text)
        assert "**not bold**" in result


# =============================================================================
# DEBOUNCER
# =============================================================================

class TestMessageDebouncer:
    """Tests for MessageDebouncer."""

    def test_sync_mode_returns_none_before_max(self):
        d = MessageDebouncer(window=5.0, max_batch=3)
        result = d.add("user1", "hello")
        assert result is None

    def test_sync_mode_returns_combined_at_max_batch(self):
        d = MessageDebouncer(window=5.0, max_batch=2)
        d.add("user1", "hello")
        result = d.add("user1", "world")
        assert result == "hello\nworld"

    def test_flush_now_returns_pending(self):
        d = MessageDebouncer(window=5.0, max_batch=10)
        d.add("user1", "line1")
        d.add("user1", "line2")
        result = d.flush_now("user1")
        assert result == "line1\nline2"

    def test_flush_now_returns_none_when_empty(self):
        d = MessageDebouncer()
        assert d.flush_now("nobody") is None

    def test_has_pending_true_after_add(self):
        d = MessageDebouncer(window=5.0, max_batch=10)
        d.add("user1", "msg")
        assert d.has_pending("user1") is True

    def test_has_pending_false_after_flush(self):
        d = MessageDebouncer(window=5.0, max_batch=10)
        d.add("user1", "msg")
        d.flush_now("user1")
        assert d.has_pending("user1") is False

    def test_cancel_clears_pending(self):
        d = MessageDebouncer(window=5.0, max_batch=10)
        d.add("user1", "msg1")
        d.add("user1", "msg2")
        d.cancel("user1")
        assert d.has_pending("user1") is False
        assert d.flush_now("user1") is None

    def test_shutdown_clears_all(self):
        d = MessageDebouncer(window=5.0, max_batch=10)
        d.add("user1", "a")
        d.add("user2", "b")
        d.shutdown()
        assert d.has_pending("user1") is False
        assert d.has_pending("user2") is False

    def test_multiple_users_independent(self):
        d = MessageDebouncer(window=5.0, max_batch=2)
        d.add("alice", "a1")
        d.add("bob", "b1")
        # alice hits max_batch
        result_alice = d.add("alice", "a2")
        assert result_alice == "a1\na2"
        # bob still pending
        assert d.has_pending("bob") is True
        result_bob = d.flush_now("bob")
        assert result_bob == "b1"

    def test_async_mode_returns_none_and_fires_callback(self):
        d = MessageDebouncer(window=0.1, max_batch=10)
        results = []

        def on_flush(uid, text):
            results.append((uid, text))

        d.add("user1", "hello", on_flush=on_flush)
        # Should return None in async mode
        assert d.has_pending("user1") is True
        # Wait for the timer to fire
        time.sleep(0.3)
        assert len(results) == 1
        assert results[0] == ("user1", "hello")


# =============================================================================
# CHANNEL BASE
# =============================================================================

class TestChannelMessage:
    """Tests for the ChannelMessage dataclass."""

    def test_basic_construction(self):
        msg = ChannelMessage(
            channel="telegram",
            sender="Alice",
            text="Hello ARIA",
            chat_id="12345",
        )
        assert msg.channel == "telegram"
        assert msg.sender == "Alice"
        assert msg.text == "Hello ARIA"
        assert msg.chat_id == "12345"
        assert isinstance(msg.timestamp, datetime)
        assert msg.metadata == {}

    def test_custom_metadata(self):
        msg = ChannelMessage(
            channel="slack",
            sender="Bob",
            text="test",
            chat_id="C01",
            metadata={"thread_ts": "123.456"},
        )
        assert msg.metadata["thread_ts"] == "123.456"


class TestChannelBase:
    """Tests for ChannelBase via ConcreteChannel."""

    def test_stats_returns_expected_keys(self):
        ch = ConcreteChannel()
        s = ch.stats()
        expected_keys = {
            "channel", "running", "healthy", "uptime_seconds",
            "messages_received", "messages_sent", "active_chats",
            "avg_latency_ms", "messages_today", "retry_queue_size",
            "recent_errors",
        }
        assert expected_keys == set(s.keys())

    def test_stats_initial_values(self):
        ch = ConcreteChannel()
        s = ch.stats()
        assert s["channel"] == "test"
        assert s["running"] is False
        assert s["messages_received"] == 0
        assert s["messages_sent"] == 0
        assert s["uptime_seconds"] == 0

    def test_rate_limit_false_initially(self):
        ch = ConcreteChannel(rate_limit=5, rate_window=60)
        assert ch._is_rate_limited("user1") is False

    def test_rate_limit_true_after_exceeding(self):
        ch = ConcreteChannel(rate_limit=3, rate_window=60)
        # First 3 calls register timestamps and return False
        for _ in range(3):
            ch._is_rate_limited("user1")
        # 4th call should be rate-limited
        assert ch._is_rate_limited("user1") is True

    def test_record_incoming_increments_counter(self):
        ch = ConcreteChannel(log_messages=False)
        assert ch._messages_in == 0
        ch._record_incoming("chat1", "Alice", "hello")
        assert ch._messages_in == 1
        ch._record_incoming("chat2", "Bob", "hi")
        assert ch._messages_in == 2

    def test_record_incoming_tracks_active_chats(self):
        ch = ConcreteChannel(log_messages=False)
        ch._record_incoming("chat1", "Alice", "hello")
        ch._record_incoming("chat2", "Bob", "hi")
        ch._record_incoming("chat1", "Alice", "again")
        assert len(ch._active_chats) == 2

    def test_send_increments_messages_out(self):
        ch = ConcreteChannel()
        ch._running = True
        ch.send("chat1", "hi there")
        assert ch._messages_out == 1
        assert ch.sent_messages == [("chat1", "hi there")]

    def test_send_when_not_running_does_nothing(self):
        ch = ConcreteChannel()
        ch.send("chat1", "hi")
        assert ch._messages_out == 0
        assert ch.sent_messages == []


# =============================================================================
# CHANNEL MANAGER
# =============================================================================

class TestChannelManager:
    """Tests for ChannelManager with mocked ARIA instance."""

    @pytest.fixture
    def mock_aria(self):
        aria = Mock()
        aria.telegram = None
        aria.discord = None
        aria.slack = None
        return aria

    @pytest.fixture
    def manager(self, mock_aria):
        from core.channels.channel_manager import ChannelManager
        return ChannelManager(mock_aria)

    def test_list_channels_returns_three(self, manager):
        channels = manager.list_channels()
        assert len(channels) == 3
        names = {c["name"] for c in channels}
        assert names == {"telegram", "discord", "slack"}

    @patch.dict(os.environ, {}, clear=True)
    def test_status_unconfigured_when_env_missing(self, manager):
        # With no env vars set, all channels should be unconfigured
        for ch in manager.list_channels():
            assert ch["status"] == "unconfigured"

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok123456789"}, clear=True)
    def test_reveal_token_masks_value(self, manager):
        result = manager.reveal_token("telegram")
        assert result["ok"] is True
        token_masked = result["tokens"]["TELEGRAM_BOT_TOKEN"]
        assert token_masked.endswith("6789")
        assert token_masked.startswith("*")
        assert len(token_masked) == len("tok123456789")

    def test_reveal_token_unknown_channel(self, manager):
        result = manager.reveal_token("carrier_pigeon")
        assert result["ok"] is False
        assert result["error"] == "unknown_channel"

    @patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc"}, clear=True)
    def test_reveal_token_short_token_fully_masked(self, manager):
        result = manager.reveal_token("telegram")
        assert result["tokens"]["TELEGRAM_BOT_TOKEN"] == "****"

    def test_dashboard_aggregation_no_bots(self, manager):
        dashboard = manager.get_dashboard()
        assert dashboard["total_messages_today"] == 0
        assert dashboard["total_active_chats"] == 0
        assert dashboard["channels_running"] == 0
        assert dashboard["channels_total"] == 3
        assert len(dashboard["channels"]) == 3

    def test_dashboard_aggregation_with_running_bot(self, mock_aria, manager):
        bot = Mock()
        bot.is_running = True
        bot.stats.return_value = {
            "messages_today": 42,
            "active_chats": 5,
            "healthy": True,
        }
        mock_aria.telegram = bot

        # Need env var set so status is "running" not "unconfigured"
        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "tok123"}):
            dashboard = manager.get_dashboard()

        assert dashboard["total_messages_today"] == 42
        assert dashboard["total_active_chats"] == 5
        assert dashboard["channels_running"] == 1
        assert dashboard["channels_healthy"] == 1
