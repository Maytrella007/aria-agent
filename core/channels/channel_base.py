"""
ARIA - Channel Base
====================

Abstract base class for all communication channels.
Extracted from TelegramBot after validating the pattern works.

Includes hardening features:
- Rate limiting per user
- Outbound message queue with retries
- Health check (periodic connectivity verification)
- Metrics (messages/day, latency tracking)

Any channel (Telegram, WhatsApp, Discord, etc.) implements this interface.

Usage:
    class MyChannel(ChannelBase):
        def _do_start(self): ...
        def _do_stop(self): ...
        def _do_send(self, chat_id, text): ...
"""

import collections
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Deque, Optional, Set, Dict, Any, List, Tuple

logger = logging.getLogger("aria.channel")


# =============================================================================
# CHANNEL MESSAGE
# =============================================================================

@dataclass
class ChannelMessage:
    """Unified message from any channel."""
    channel: str            # "telegram", "whatsapp", etc.
    sender: str             # Username or display name
    text: str               # Message content
    chat_id: str            # Where to reply (chat/group/contact ID)
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)


# =============================================================================
# CHANNEL BASE
# =============================================================================

class ChannelBase(ABC):
    """
    Abstract base for all ARIA communication channels.

    Subclasses must implement:
        _do_start()  — connect/start polling
        _do_stop()   — disconnect/cleanup
        _do_send(chat_id, text) — send a message
        _do_health_check() — verify connection (optional, default True)

    The base class provides:
        start() / stop()     — lifecycle with stats tracking
        send()               — send with error handling
        send_with_retry()    — queued send with automatic retries
        stats()              — usage statistics + metrics
        message_handler      — callback to ARIA's conversation loop
        rate limiting        — per-user message throttling
        health check         — periodic connectivity verification
    """

    channel_name: str = "unknown"

    def __init__(
        self,
        message_handler: Callable[[str, str], str],
        log_messages: bool = True,
        rate_limit: int = 20,
        rate_window: int = 60,
        health_interval: int = 300,
        max_retries: int = 3,
    ):
        """
        Args:
            message_handler: Callable(sender, text) -> response
            log_messages: Log incoming/outgoing messages
            rate_limit: Max messages per user within rate_window
            rate_window: Rate limit window in seconds
            health_interval: Health check interval in seconds (0 = disabled)
            max_retries: Max retries for failed outbound messages
        """
        self.message_handler = message_handler
        self.log_messages = log_messages

        self._running = False
        self._started_at: Optional[float] = None
        self._messages_in = 0
        self._messages_out = 0
        self._active_chats: Set[str] = set()

        # Rate limiting
        self._rate_limit = rate_limit
        self._rate_window = rate_window
        self._user_timestamps: Dict[str, Deque[float]] = {}

        # Outbound retry queue
        self._max_retries = max_retries
        self._retry_queue: Deque[Tuple[str, str, int]] = collections.deque()
        self._retry_thread: Optional[threading.Thread] = None

        # Health check
        self._health_interval = health_interval
        self._health_thread: Optional[threading.Thread] = None
        self._last_health_check: float = 0.0
        self._healthy = True

        # Metrics
        self._latencies: Deque[float] = collections.deque(maxlen=100)
        self._daily_counts: Dict[str, int] = {}  # "YYYY-MM-DD" -> count
        self._errors: Deque[Tuple[float, str]] = collections.deque(maxlen=50)

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start(self):
        """Start the channel."""
        if self._running:
            logger.warning(f"{self.channel_name} already running")
            return
        self._do_start()
        self._started_at = time.time()
        self._running = True
        self._start_retry_worker()
        self._start_health_check()
        logger.info(f"{self.channel_name} channel started")

    def stop(self):
        """Stop the channel."""
        if not self._running:
            return
        self._running = False
        self._do_stop()
        logger.info(f"{self.channel_name} channel stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    # -------------------------------------------------------------------------
    # Abstract methods (implement in subclass)
    # -------------------------------------------------------------------------

    @abstractmethod
    def _do_start(self):
        """Start the channel connection (polling, websocket, etc.)."""
        pass

    @abstractmethod
    def _do_stop(self):
        """Stop the channel connection cleanly."""
        pass

    @abstractmethod
    def _do_send(self, chat_id: str, text: str):
        """Send a message to a specific chat."""
        pass

    def _do_health_check(self) -> bool:
        """Check if the channel is still connected. Override in subclass."""
        return self._running

    # -------------------------------------------------------------------------
    # Send
    # -------------------------------------------------------------------------

    def send(self, chat_id, text: str):
        """Send a message, with error handling and stats."""
        if not self._running:
            logger.warning(f"Cannot send on {self.channel_name}: not running")
            return
        try:
            self._do_send(str(chat_id), text)
            self._messages_out += 1
        except Exception as e:
            logger.error(f"{self.channel_name} send error: {e}")
            self._record_error(str(e))

    def send_with_retry(self, chat_id: str, text: str):
        """Queue a message for sending with automatic retries on failure."""
        self._retry_queue.append((str(chat_id), text, 0))

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------

    def _is_rate_limited(self, user_id: str) -> bool:
        """Check if a user has exceeded the rate limit."""
        if self._rate_limit <= 0:
            return False

        now = time.time()
        if user_id not in self._user_timestamps:
            self._user_timestamps[user_id] = collections.deque()

        timestamps = self._user_timestamps[user_id]

        # Remove expired timestamps
        while timestamps and timestamps[0] < now - self._rate_window:
            timestamps.popleft()

        if len(timestamps) >= self._rate_limit:
            return True

        timestamps.append(now)
        return False

    # -------------------------------------------------------------------------
    # Stats & Metrics
    # -------------------------------------------------------------------------

    def stats(self) -> dict:
        """Return channel statistics with metrics."""
        uptime = 0
        if self._started_at and self._running:
            uptime = int(time.time() - self._started_at)

        avg_latency = 0.0
        if self._latencies:
            avg_latency = round(sum(self._latencies) / len(self._latencies), 2)

        today = datetime.now().strftime("%Y-%m-%d")
        today_count = self._daily_counts.get(today, 0)

        return {
            "channel": self.channel_name,
            "running": self._running,
            "healthy": self._healthy,
            "uptime_seconds": uptime,
            "messages_received": self._messages_in,
            "messages_sent": self._messages_out,
            "active_chats": len(self._active_chats),
            "avg_latency_ms": avg_latency,
            "messages_today": today_count,
            "retry_queue_size": len(self._retry_queue),
            "recent_errors": len(self._errors),
        }

    def get_active_chat_ids(self) -> Set[str]:
        """Return set of active chat IDs."""
        return self._active_chats.copy()

    # -------------------------------------------------------------------------
    # Helpers for subclasses
    # -------------------------------------------------------------------------

    def _record_incoming(self, chat_id: str, sender: str, text: str):
        """Record an incoming message (call from subclass handler)."""
        self._messages_in += 1
        self._active_chats.add(str(chat_id))
        self._record_daily()
        if self.log_messages:
            logger.info(f"[{self.channel_name} IN] {sender}: {text[:100]}")

    def _process_message(self, sender: str, text: str) -> str:
        """Process a message through ARIA's handler with latency tracking."""
        start = time.time()
        try:
            response = self.message_handler(sender, text)
            latency_ms = (time.time() - start) * 1000
            self._latencies.append(latency_ms)
            return response
        except Exception as e:
            latency_ms = (time.time() - start) * 1000
            self._latencies.append(latency_ms)
            logger.error(f"Error processing message on {self.channel_name}: {e}")
            self._record_error(str(e))
            return "Error interno procesando tu mensaje. Intenta de nuevo."

    def _check_rate_limit(self, user_id: str, sender: str) -> bool:
        """Check rate limit. Returns True if message should be blocked."""
        if self._is_rate_limited(user_id):
            logger.warning(f"Rate limited: {sender} ({user_id}) on {self.channel_name}")
            return True
        return False

    # -------------------------------------------------------------------------
    # Internal: Retry worker
    # -------------------------------------------------------------------------

    def _start_retry_worker(self):
        """Start background thread for retrying failed sends."""
        self._retry_thread = threading.Thread(
            target=self._retry_loop,
            name=f"aria-{self.channel_name}-retry",
            daemon=True,
        )
        self._retry_thread.start()

    def _retry_loop(self):
        """Process retry queue in background."""
        while self._running:
            if not self._retry_queue:
                time.sleep(1)
                continue

            chat_id, text, attempt = self._retry_queue.popleft()
            try:
                self._do_send(chat_id, text)
                self._messages_out += 1
            except Exception as e:
                if attempt < self._max_retries:
                    # Exponential backoff: 2s, 4s, 8s
                    delay = 2 ** (attempt + 1)
                    logger.warning(
                        f"{self.channel_name} send retry {attempt + 1}/{self._max_retries} "
                        f"for chat {chat_id} in {delay}s: {e}"
                    )
                    time.sleep(delay)
                    self._retry_queue.append((chat_id, text, attempt + 1))
                else:
                    logger.error(
                        f"{self.channel_name} send failed after {self._max_retries} "
                        f"retries to {chat_id}: {e}"
                    )
                    self._record_error(f"Send failed to {chat_id}: {e}")

    # -------------------------------------------------------------------------
    # Internal: Health check
    # -------------------------------------------------------------------------

    def _start_health_check(self):
        """Start background health check thread."""
        if self._health_interval <= 0:
            return

        self._health_thread = threading.Thread(
            target=self._health_loop,
            name=f"aria-{self.channel_name}-health",
            daemon=True,
        )
        self._health_thread.start()

    def _health_loop(self):
        """Periodically check channel health."""
        while self._running:
            time.sleep(self._health_interval)
            if not self._running:
                break
            try:
                self._healthy = self._do_health_check()
                self._last_health_check = time.time()
                if not self._healthy:
                    logger.warning(f"{self.channel_name} health check FAILED")
                else:
                    logger.debug(f"{self.channel_name} health check OK")
            except Exception as e:
                self._healthy = False
                logger.error(f"{self.channel_name} health check error: {e}")
                self._record_error(f"Health check: {e}")

    # -------------------------------------------------------------------------
    # Internal: Metrics helpers
    # -------------------------------------------------------------------------

    def _record_daily(self):
        """Increment daily message counter."""
        today = datetime.now().strftime("%Y-%m-%d")
        self._daily_counts[today] = self._daily_counts.get(today, 0) + 1
        # Cleanup old entries (keep last 7 days)
        if len(self._daily_counts) > 7:
            keys = sorted(self._daily_counts.keys())
            for k in keys[:-7]:
                del self._daily_counts[k]

    def _record_error(self, error_msg: str):
        """Record an error for metrics."""
        self._errors.append((time.time(), error_msg))
