"""
ARIA - Shell Exec Tool
=======================

Execute system commands with security validation.
Wraps existing SystemAccess with the ToolBase interface.
"""

import logging
import os
import subprocess
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.shell_exec")

DEFAULT_TIMEOUT = 60


class ShellExecTool(ToolBase):
    """Execute a system command in the shell."""

    name = "shell_exec"
    description = (
        "Execute a command in the system shell and return its output. "
        "Use for running programs, scripts, file operations, etc. "
        "Commands are validated for safety before execution."
    )
    parameters = [
        ToolParam(
            name="command",
            type="string",
            description="The shell command to execute",
            required=True,
        ),
        ToolParam(
            name="timeout",
            type="integer",
            description="Timeout in seconds (default: 60)",
            required=False,
            default=60,
        ),
        ToolParam(
            name="cwd",
            type="string",
            description="Working directory for the command",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        command = kwargs["command"]
        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 300)  # Max 5 min
        cwd = kwargs.get("cwd")

        # Security check
        try:
            from core.infra.security import is_dangerous_command, get_current_mode
            is_dangerous, reason = is_dangerous_command(command)
            if is_dangerous:
                return ToolResult(
                    success=False,
                    error=f"Command blocked ({get_current_mode().value} mode): {reason}",
                    data={"command": command, "blocked": True},
                )
        except ImportError:
            pass

        # Validate cwd
        if cwd and not os.path.isdir(cwd):
            return ToolResult(success=False, error=f"Directory not found: {cwd}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()
            success = result.returncode == 0

            # Build output
            output_parts = []
            if stdout:
                output_parts.append(stdout)
            if stderr and not success:
                output_parts.append(f"STDERR: {stderr}")

            output = "\n".join(output_parts) if output_parts else "(no output)"

            return ToolResult(
                success=success,
                output=output,
                data={
                    "command": command,
                    "return_code": result.returncode,
                    "stdout": stdout[:10000],
                    "stderr": stderr[:5000],
                },
                error=f"Exit code {result.returncode}" if not success else None,
            )

        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                error=f"Command timed out after {timeout}s",
                data={"command": command, "timeout": timeout},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                data={"command": command},
            )
