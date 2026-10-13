"""
Terminal Subscriber - Reproduces ARIA's current terminal print() behavior via EventBus.

Subscribes to the EventBus and prints streaming tokens, tool status, and lifecycle
events to the terminal exactly as the old direct-print code did.
"""


class TerminalSubscriber:
    """Subscriber that reproduces the current terminal print() behavior."""

    def __init__(self, event_bus):
        self._started = False
        self._unsub = event_bus.subscribe(self._on_event)

    def _on_event(self, event):
        if event.stream == "assistant" and event.event == "delta":
            if not self._started:
                print("\nARIA: ", end="", flush=True)
                self._started = True
            print(event.data["text"], end="", flush=True)

        elif event.stream == "assistant" and event.event == "done":
            if self._started:
                print()  # newline after streaming
            self._started = False

        elif event.stream == "tool" and event.event == "start":
            round_num = event.data.get("round", "")
            max_rounds = event.data.get("max_rounds", "")
            name = event.data["name"]
            if round_num:
                print(f"  [{round_num}/{max_rounds}] {name}...")
            else:
                print(f"  [{name}]...")

        elif event.stream == "tool" and event.event == "result":
            success = event.data.get("success", True)
            if success:
                preview = event.data.get("preview", "(ok)")
                print(f"    \u2713 {preview}")
            else:
                error = event.data.get("error", "unknown error")
                print(f"    \u2717 {error}")

    def unsubscribe(self):
        self._unsub()
