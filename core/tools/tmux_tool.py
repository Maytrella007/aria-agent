"""ARIA - Tmux Tool."""

import shutil
import subprocess

from .tool_base import ToolBase, ToolParam, ToolResult


class TmuxTool(ToolBase):
    name = "tmux"
    description = "Interact with tmux sessions. Actions: list_sessions, capture, send_keys, select_target."
    parameters = [
        ToolParam(name="action", type="string", description="tmux action", required=True,
                  enum=["list_sessions", "capture", "send_keys", "select_target"]),
        ToolParam(name="target", type="string", description="Session/window/pane target", required=False),
        ToolParam(name="text", type="string", description="Text to send to the target", required=False),
        ToolParam(name="lines", type="integer", description="Lines to capture", required=False, default=50),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        tmux = shutil.which("tmux")
        if not tmux:
            return ToolResult(success=False, error="tmux is not installed")
        action = kwargs["action"]
        if action == "list_sessions":
            return self._run([tmux, "list-sessions"])
        if action == "capture":
            target = kwargs.get("target")
            if not target:
                return ToolResult(success=False, error="target required")
            lines = str(min(kwargs.get("lines", 50), 500))
            return self._run([tmux, "capture-pane", "-p", "-S", f"-{lines}", "-t", target])
        if action == "send_keys":
            target = kwargs.get("target")
            text = kwargs.get("text")
            if not target or text is None:
                return ToolResult(success=False, error="target and text required")
            return self._run([tmux, "send-keys", "-t", target, text, "C-m"])
        if action == "select_target":
            target = kwargs.get("target")
            if not target:
                return ToolResult(success=False, error="target required")
            return self._run([tmux, "select-pane", "-t", target])
        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _run(self, cmd) -> ToolResult:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="tmux command timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
        output = (proc.stdout or proc.stderr or "(no output)").strip()
        if proc.returncode != 0:
            return ToolResult(success=False, error=output, data={"command": cmd, "returncode": proc.returncode})
        return ToolResult(success=True, output=output, data={"command": cmd, "returncode": proc.returncode})
