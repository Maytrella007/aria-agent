"""
Message Debouncer - Combines rapid messages from the same user.

Inspired by OpenClaw's inbound debouncer pattern: when a user sends multiple
messages quickly (e.g., splitting a thought across 3 messages in 2 seconds),
they are combined into a single message before being passed to the LLM.

This prevents ARIA from generating 3 separate responses and confusing the
conversation flow.

Usage:
    debouncer = MessageDebouncer(window=2.0)

    # In message handler:
    combined = debouncer.add(user_id, text)
    if combined is None:
        return  # Still accumulating, don't process yet
    # combined contains all messages joined with newlines
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

logger = logging.getLogger("aria.debouncer")


@dataclass
class _PendingBatch:
    """Accumulating messages from a single user."""
    user_id: str
    texts: List[str] = field(default_factory=list)
    first_ts: float = 0.0
    timer: Optional[threading.Timer] = None


class MessageDebouncer:
    """
    Batches rapid messages from the same user within a time window.

    Thread-safe. When the window expires, the accumulated texts are joined
    with newlines and delivered via the flush callback.

    Args:
        window: Seconds to wait for more messages before flushing (default: 2.0).
        max_batch: Maximum messages to batch before force-flushing (default: 5).
    """

    def __init__(self, window: float = 2.0, max_batch: int = 5):
        self.window = window
        self.max_batch = max_batch
        self._pending: Dict[str, _PendingBatch] = {}
        self._lock = threading.Lock()
        self._flush_callbacks: Dict[str, Callable[[str, str], None]] = {}

    def add(
        self,
        user_id: str,
        text: str,
        on_flush: Optional[Callable[[str, str], None]] = None,
    ) -> Optional[str]:
        """
        Add a message to the debounce buffer.

        Args:
            user_id: Unique user identifier (per channel+user).
            text: The message text.
            on_flush: Callback(user_id, combined_text) called when batch is ready.
                      If None, uses synchronous mode (returns combined text immediately
                      when batch is full, or None if still accumulating).

        Returns:
            - In async mode (on_flush provided): Always None. Callback fires later.
            - In sync mode (no on_flush): Combined text when max_batch reached,
              otherwise None (caller should wait or use async mode).
        """
        with self._lock:
            if user_id not in self._pending:
                self._pending[user_id] = _PendingBatch(
                    user_id=user_id,
                    texts=[],
                    first_ts=time.time(),
                )

            batch = self._pending[user_id]
            batch.texts.append(text)

            if on_flush:
                self._flush_callbacks[user_id] = on_flush

            # Force flush if max batch reached
            if len(batch.texts) >= self.max_batch:
                return self._flush_locked(user_id)

            # Cancel existing timer and start a new one
            if batch.timer:
                batch.timer.cancel()

            if on_flush:
                # Async mode: set timer to flush later
                batch.timer = threading.Timer(
                    self.window, self._flush_by_timer, args=[user_id]
                )
                batch.timer.daemon = True
                batch.timer.start()
                return None
            else:
                # Sync mode: caller must poll or use async mode
                # Return None to indicate "still waiting"
                return None

    def flush_now(self, user_id: str) -> Optional[str]:
        """Force-flush a user's pending messages. Returns combined text or None."""
        with self._lock:
            return self._flush_locked(user_id)

    def has_pending(self, user_id: str) -> bool:
        """Check if a user has pending messages."""
        with self._lock:
            return user_id in self._pending and len(self._pending[user_id].texts) > 0

    def _flush_by_timer(self, user_id: str):
        """Called by timer thread when debounce window expires."""
        with self._lock:
            combined = self._flush_locked(user_id)

        if combined:
            cb = self._flush_callbacks.pop(user_id, None)
            if cb:
                try:
                    cb(user_id, combined)
                except Exception as e:
                    logger.error(f"Debounce flush callback error for {user_id}: {e}")

    def _flush_locked(self, user_id: str) -> Optional[str]:
        """Flush pending messages (must hold self._lock). Returns combined text."""
        batch = self._pending.pop(user_id, None)
        if not batch or not batch.texts:
            return None

        if batch.timer:
            batch.timer.cancel()

        combined = "\n".join(batch.texts)
        logger.debug(
            f"Debounced {len(batch.texts)} messages from {user_id} "
            f"({time.time() - batch.first_ts:.1f}s window)"
        )
        return combined

    def cancel(self, user_id: str):
        """Cancel pending debounce for a user."""
        with self._lock:
            batch = self._pending.pop(user_id, None)
            if batch and batch.timer:
                batch.timer.cancel()
            self._flush_callbacks.pop(user_id, None)

    def shutdown(self):
        """Cancel all pending timers."""
        with self._lock:
            for uid, batch in self._pending.items():
                if batch.timer:
                    batch.timer.cancel()
            self._pending.clear()
            self._flush_callbacks.clear()
