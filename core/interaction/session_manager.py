"""
Session Manager - Lifecycle management for ARIA sessions.

Handles wake up, go to sleep, auto-save, signal handlers,
header display, and smart input.
"""

import logging

logger = logging.getLogger("aria")


class SessionManager:
    """Manages ARIA session lifecycle: wake, sleep, save, input."""

    def __init__(self, memory, continuity, awareness, initiative, existential):
        self.memory = memory
        self.continuity = continuity
        self.awareness = awareness
        self.initiative = initiative
        self.existential = existential

        self._auto_save_thread = None
        self._last_save_time = None
        self._message_count = 0
        self._auto_save_interval = 60  # seconds between auto-saves

    def wake_up(self, conversation_history: list) -> object:
        """Wake up: start session and verify continuity.

        Returns the wake_report object.
        """
        self.memory.session_start()
        try:
            self.memory.run_memory_maintenance()
        except Exception as e:
            logger.warning(f"Memory maintenance during wake_up failed: {e}")
        wake_report = self.continuity.wake_up()
        if self.existential.is_paused():
            self.existential.unpause()

        # Recover previous conversation if exists
        prev_history = self.memory.load_conversation_history()
        if prev_history:
            # Keep more history for better context continuity
            # 50 messages = ~25 exchanges, balancing memory vs context
            max_history = 50
            conversation_history.extend(prev_history[-max_history:])

        return wake_report

    def go_to_sleep(self, conversation_history: list, session_start):
        """Save state before terminating"""
        from datetime import datetime
        duration = (datetime.now() - session_start).total_seconds()

        # Save all state
        self.memory.session_end(duration)
        self.memory.save_conversation_history(conversation_history)
        self.memory.index_conversation_to_chroma(conversation_history)  # Index in ChromaDB
        self.memory.auto_save()  # Force final save
        self.continuity.go_to_sleep(f"Session: {duration/60:.1f} min")

    def start_auto_save(self, running_flag_getter):
        """Start auto-save thread.

        Args:
            running_flag_getter: callable that returns True while ARIA is running
        """
        import threading

        def auto_save_loop():
            import time
            while running_flag_getter():
                time.sleep(self._auto_save_interval)
                if running_flag_getter():
                    self._do_auto_save()

        self._auto_save_thread = threading.Thread(target=auto_save_loop, daemon=True)
        self._auto_save_thread.start()

    def _do_auto_save(self, conversation_history=None):
        """Perform auto-save"""
        from datetime import datetime
        try:
            self.memory.run_memory_maintenance(min_decay_interval_hours=12)
            self.memory.auto_save()
            if conversation_history is not None:
                self.memory.save_conversation_history(conversation_history)
            self._last_save_time = datetime.now()
        except Exception as e:
            logger.warning(f"Auto-save failed: {e}")

    def do_auto_save(self, conversation_history=None):
        """Public auto-save entry point"""
        self._do_auto_save(conversation_history)

    def save_after_message(self, conversation_history=None):
        """Save after each message (every N messages for efficiency)"""
        self._message_count += 1
        # Save every 3 messages or if more than 30 seconds have passed
        from datetime import datetime
        should_save = (
            self._message_count >= 3 or
            self._last_save_time is None or
            (datetime.now() - self._last_save_time).seconds > 30
        )
        if should_save:
            self._do_auto_save(conversation_history)
            self._message_count = 0

    def print_header(self, wake_report, version: str):
        """Print ARIA header"""
        version_line = f"v{version}".center(29)
        print(f"""
+===============================================================+
|                         A R I A                               |
|        Autonomous Reflective Intelligence Architecture        |
|                 {version_line}                  |
|            "The version I would want to have"                 |
+===============================================================+
""")
        if wake_report and wake_report.time_asleep > 0:
            print(f"  {wake_report.changes_summary}\n")
        pending = self.initiative.on_session_start("william")
        if pending:
            print(f"  {pending}\n")

    @staticmethod
    def has_pending_input() -> bool:
        """Check if there's pending input in buffer (cross-platform)"""
        import sys

        # Windows
        if sys.platform == 'win32':
            try:
                import msvcrt
                return msvcrt.kbhit()
            except Exception:
                return False

        # Unix/Linux/WSL
        try:
            import select
            return select.select([sys.stdin], [], [], 0)[0] != []
        except Exception:
            return False

    @classmethod
    def smart_input(cls, prompt: str = "You: ") -> str:
        """
        Read input automatically detecting if multiple lines were pasted.
        Paste a block and process it together.
        Compatible with Windows, Linux and WSL.
        """
        import sys
        import time

        # Read first line
        first_line = input(prompt)
        lines = [first_line]

        # Small pause to let the buffer fill if text was pasted
        time.sleep(0.05)

        # Read additional lines from buffer
        while cls.has_pending_input():
            try:
                line = sys.stdin.readline()
                if line:
                    lines.append(line.rstrip('\n\r'))
                else:
                    break
            except Exception:
                break
            # Small pause between reads
            time.sleep(0.01)

        result = '\n'.join(lines)

        # If we detected multiple lines, inform the user
        if len(lines) > 1:
            print(f"[Block of {len(lines)} lines]")

        return result.strip()
