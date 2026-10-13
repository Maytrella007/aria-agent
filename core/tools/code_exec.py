"""
ARIA - Code Exec Tool
======================

Execute Python code snippets in a controlled environment.
More focused than shell_exec — runs Python directly with captured output.
Useful for calculations, data processing, quick scripts.
"""

import io
import logging
import sys
import traceback
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.code_exec")

MAX_OUTPUT = 50_000  # 50KB output limit
DEFAULT_TIMEOUT = 30


class CodeExecTool(ToolBase):
    """Execute Python code and return the output."""

    name = "code_exec"
    description = (
        "Execute Python code snippets and return the output. "
        "Use for calculations, data processing, parsing, quick scripts. "
        "Has access to standard library. Print statements are captured."
    )
    parameters = [
        ToolParam(
            name="code",
            type="string",
            description="Python code to execute",
            required=True,
        ),
        ToolParam(
            name="timeout",
            type="integer",
            description="Timeout in seconds (default: 30, max: 60)",
            required=False,
            default=30,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        code = kwargs["code"]
        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 60)

        # Capture stdout and stderr
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        # Execution namespace with common imports available
        exec_globals = {
            "__builtins__": __builtins__,
            "__name__": "__aria_exec__",
        }

        result_value = None

        try:
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture

            # Use threading for timeout
            import threading

            error_holder = [None]
            result_holder = [None]

            def run_code():
                try:
                    # Try exec first (statements)
                    compiled = compile(code, "<aria>", "exec")
                    exec(compiled, exec_globals)

                    # Check if last line is an expression that has a value
                    # Try to eval the last line for a return value
                    lines = code.strip().split("\n")
                    last_line = lines[-1].strip()
                    if last_line and not any(last_line.startswith(kw) for kw in
                        ("import ", "from ", "def ", "class ", "if ", "for ", "while ",
                         "with ", "try:", "except", "finally:", "return ", "yield ",
                         "raise ", "pass", "break", "continue", "#", "print(")):
                        try:
                            val = eval(last_line, exec_globals)
                            if val is not None:
                                result_holder[0] = val
                        except Exception:
                            pass
                except Exception as e:
                    error_holder[0] = traceback.format_exc()

            thread = threading.Thread(target=run_code)
            thread.start()
            thread.join(timeout=timeout)

            if thread.is_alive():
                return ToolResult(
                    success=False,
                    error=f"Code execution timed out after {timeout}s",
                )

            stdout_out = stdout_capture.getvalue()[:MAX_OUTPUT]
            stderr_out = stderr_capture.getvalue()[:MAX_OUTPUT]
            result_value = result_holder[0]

            if error_holder[0]:
                # Execution error
                output_parts = []
                if stdout_out:
                    output_parts.append(stdout_out)
                output_parts.append(f"Error:\n{error_holder[0]}")

                return ToolResult(
                    success=False,
                    output="\n".join(output_parts),
                    error="Code execution failed",
                    data={"stdout": stdout_out, "stderr": stderr_out},
                )

            # Success
            output_parts = []
            if stdout_out:
                output_parts.append(stdout_out)
            if result_value is not None:
                output_parts.append(repr(result_value))
            if not output_parts:
                output_parts.append("(no output)")

            return ToolResult(
                success=True,
                output="\n".join(output_parts),
                data={
                    "stdout": stdout_out,
                    "stderr": stderr_out,
                    "result": repr(result_value) if result_value is not None else None,
                },
            )

        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
