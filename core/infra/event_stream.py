"""
Event Bus system for ARIA streaming infrastructure.

Provides a thread-safe publish/subscribe event bus with bounded history,
supporting sync callbacks, queue-based consumers, and asyncio consumers.
"""

import asyncio
import logging
import queue
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MAX_HISTORY_PER_RUN = 500
MAX_RUN_IDS = 50


@dataclass
class StreamEvent:
    stream: str        # "assistant" | "tool" | "lifecycle" | "error"
    event: str         # "delta" | "start" | "end" | "result" | "thinking"
    data: dict         # payload
    run_id: str        # execution ID
    seq: int           # auto-increment per run_id
    timestamp: float   # time.time()

    def to_dict(self) -> dict:
        return asdict(self)


class EventBus:
    """Thread-safe event bus with bounded history and multiple subscriber types."""

    def __init__(self):
        self._subscribers: list[Callable[[StreamEvent], None]] = []
        self._seq_counters: dict[str, int] = {}
        self._history: dict[str, list[StreamEvent]] = {}
        self._lock = threading.Lock()

    def emit(self, stream: str, event: str, data: dict, run_id: str = "default") -> StreamEvent:
        """Create and dispatch a StreamEvent with auto-incremented seq."""
        with self._lock:
            # Auto-increment seq for this run_id
            seq = self._seq_counters.get(run_id, 0)
            self._seq_counters[run_id] = seq + 1

            ev = StreamEvent(
                stream=stream,
                event=event,
                data=data,
                run_id=run_id,
                seq=seq,
                timestamp=time.time(),
            )

            # Store in history (bounded)
            if run_id not in self._history:
                # Evict oldest run_id if at capacity
                if len(self._history) >= MAX_RUN_IDS:
                    oldest_key = next(iter(self._history))
                    del self._history[oldest_key]
                    self._seq_counters.pop(oldest_key, None)
                self._history[run_id] = []

            run_history = self._history[run_id]
            run_history.append(ev)
            if len(run_history) > MAX_HISTORY_PER_RUN:
                self._history[run_id] = run_history[-MAX_HISTORY_PER_RUN:]

            # Snapshot subscribers to call outside the lock
            subscribers = list(self._subscribers)

        # Call subscribers outside the lock to avoid deadlocks
        for cb in subscribers:
            try:
                cb(ev)
            except Exception:
                logger.exception("EventBus subscriber raised an exception")

        return ev

    def subscribe(self, callback: Callable[[StreamEvent], None]) -> Callable:
        """Register a callback. Returns an unsubscribe function."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe():
            with self._lock:
                try:
                    self._subscribers.remove(callback)
                except ValueError:
                    pass

        return unsubscribe

    def subscribe_queue(self, maxsize: int = 100) -> tuple[queue.Queue, Callable]:
        """Create a thread-safe Queue subscriber. Returns (queue, unsubscribe_fn)."""
        q: queue.Queue[StreamEvent] = queue.Queue(maxsize=maxsize)

        def _put(ev: StreamEvent):
            try:
                q.put_nowait(ev)
            except queue.Full:
                logger.warning("EventBus queue subscriber full, dropping event seq=%d", ev.seq)

        unsub = self.subscribe(_put)
        return q, unsub

    def subscribe_async(self, maxsize: int = 100) -> tuple[asyncio.Queue, Callable]:
        """Create an asyncio.Queue subscriber. Returns (queue, unsubscribe_fn).

        Uses loop.call_soon_threadsafe to safely enqueue from sync context.
        """
        loop = asyncio.get_event_loop()
        aq: asyncio.Queue[StreamEvent] = asyncio.Queue(maxsize=maxsize)

        def _put(ev: StreamEvent):
            try:
                loop.call_soon_threadsafe(aq.put_nowait, ev)
            except Exception:
                logger.warning("EventBus async queue put failed for event seq=%d", ev.seq)

        unsub = self.subscribe(_put)
        return aq, unsub

    def history(self, run_id: str, since_seq: int = 0) -> list[StreamEvent]:
        """Return events for run_id with seq > since_seq."""
        with self._lock:
            run_history = self._history.get(run_id, [])
            return [ev for ev in run_history if ev.seq > since_seq]

    def clear_run(self, run_id: str):
        """Clean up history and seq counter for a finished run."""
        with self._lock:
            self._history.pop(run_id, None)
            self._seq_counters.pop(run_id, None)
