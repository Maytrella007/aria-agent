"""
Quick Task Skill - Execute system commands and quick tasks.

Translates natural language into shell commands with safety checks.
Can run common operations: check ports, manage services, disk cleanup, etc.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class QuickTaskSkill(SkillBase):
    name = "quick_task"
    description = "Execute system commands and quick automation tasks"
    requires_tools = [Tools.SHELL_EXEC]

    # Commands we refuse to run
    DANGEROUS_PATTERNS = [
        r'rm\s+-rf\s+/',
        r'mkfs\.',
        r'dd\s+if=',
        r'>\s*/dev/sd',
        r'chmod\s+-R\s+777\s+/',
        r':(){ :|:& };:',
    ]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        # Detect common task patterns
        task = self._detect_task(query)

        if task:
            command, description = task
        else:
            # Use LLM to generate command if available
            if ctx.llm:
                command, description = self._llm_generate_command(query, ctx)
            else:
                return SkillResult(
                    success=False,
                    error="Could not understand the command. Please be more specific.",
                )

        if not command:
            return SkillResult(success=False, error="Could not generate a safe command")

        # Safety check
        if self._is_dangerous(command):
            return SkillResult(
                success=False,
                error=f"Command blocked for safety: {command}",
                data={"blocked": True, "command": command},
            )

        # Execute
        result = ctx.tools.execute(Tools.SHELL_EXEC, command=command)

        if result.success:
            return SkillResult(
                success=True,
                output=f"$ {command}\n\n{result.output}",
                data={"command": command, "description": description},
            )

        return SkillResult(success=False, error=f"Command failed: {result.error}")

    def _detect_task(self, query: str):
        """Map common natural language tasks to commands."""
        q = query.lower()

        # Port check
        m = re.search(r'(?:check|who|what).+port\s+(\d+)', q)
        if m:
            port = m.group(1)
            return f"lsof -i :{port} 2>/dev/null || ss -tlnp | grep :{port}", f"Check port {port}"

        # Kill process
        m = re.search(r'(?:kill|stop|matar)\s+(?:process\s+)?(\w+)', q)
        if m:
            proc = m.group(1)
            if proc.isdigit():
                return f"kill {proc}", f"Kill PID {proc}"
            return f"pkill -f {proc}", f"Kill process {proc}"

        # Ping
        m = re.search(r'ping\s+(\S+)', q)
        if m:
            host = m.group(1)
            return f"ping -c 4 {host}", f"Ping {host}"

        # Install package
        m = re.search(r'(?:install|instalar)\s+(\w[\w.-]+)', q)
        if m:
            pkg = m.group(1)
            return f"pip install {pkg}", f"Install {pkg}"

        # Disk usage
        if any(w in q for w in ["disk usage", "disk space", "uso de disco", "espacio"]):
            return "df -h", "Check disk usage"

        # Free memory
        if any(w in q for w in ["free memory", "memoria libre", "ram"]):
            return "free -h", "Check memory"

        # Running processes
        if any(w in q for w in ["what's running", "qué está corriendo", "top processes"]):
            return "ps aux --sort=-%mem | head -15", "Top processes by memory"

        # Network
        if any(w in q for w in ["network", "connections", "conexiones"]):
            return "ss -tulnp | head -20", "Active network connections"

        # Uptime
        if "uptime" in q:
            return "uptime", "System uptime"

        return None

    def _llm_generate_command(self, query: str, ctx: SkillContext):
        """Use LLM to generate a shell command."""
        prompt = f"""Convert this request to a Linux shell command:

Request: {query}

RULES:
- Single command only (can use pipes)
- Must be safe (no destructive operations)
- No sudo unless explicitly asked
- Prefer common tools (ls, grep, find, ps, etc.)

Respond with ONLY:
COMMAND: <the command>
DESCRIPTION: <what it does>"""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
            )
            if response and response.content:
                cmd_match = re.search(r'COMMAND:\s*(.+)', response.content)
                desc_match = re.search(r'DESCRIPTION:\s*(.+)', response.content)
                if cmd_match:
                    command = cmd_match.group(1).strip().strip('`')
                    description = desc_match.group(1).strip() if desc_match else query
                    return command, description
        except Exception:
            pass

        return "", ""

    def _is_dangerous(self, command: str) -> bool:
        """Check if a command is dangerous."""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, command):
                return True
        return False
