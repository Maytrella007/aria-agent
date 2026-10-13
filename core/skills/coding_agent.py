"""
Coding Agent Skill - Orchestrate external coding agents.

Inspired by OpenClaw's coding-agent skill. Delegates programming tasks
to external CLI-based coding agents (Claude Code, Codex, OpenCode, Aider)
running as subprocesses. ARIA orchestrates, monitors, and reports results.

Supported agents:
  - Claude Code  (claude -p "task")
  - OpenAI Codex CLI (codex exec --full-auto "task")
  - OpenCode (opencode run "task")
  - Aider (aider --yes --message "task")
  - Fallback: internal sub-agent with coder role

Architecture:
  User request → detect agent → verify auth → build command → shell_exec → parse result
  If not installed/authenticated → provide setup instructions
"""

import os
import re
import shutil
from typing import Optional

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class CodingAgentSkill(SkillBase):
    name = "coding_agent"
    description = (
        "Delegate programming tasks to AI coding agents (Claude Code, Codex, OpenCode, Aider). "
        "Handles code generation, bug fixes, refactoring, file creation, and test writing"
    )
    requires_tools = [Tools.SHELL_EXEC]

    # External agents: name → detection + command template + auth info
    AGENTS = {
        "claude_code": {
            "binary": "claude",
            "build_cmd": lambda task, cwd: f'claude -p "{task}"',
            "timeout": 300,
            "description": "Claude Code (Anthropic)",
            "env_keys": ["ANTHROPIC_API_KEY"],
            "auth_paths": ["~/.claude"],
            "install_cmd": "curl -fsSL https://claude.ai/install.sh | sh",
            "auth_cmd": "claude auth login",
            "install_alt": "npm install -g @anthropic-ai/claude-code",
        },
        "codex": {
            "binary": "codex",
            "build_cmd": lambda task, cwd: f'codex exec --full-auto "{task}"',
            "timeout": 300,
            "description": "OpenAI Codex CLI",
            "env_keys": ["CODEX_API_KEY", "OPENAI_API_KEY"],
            "auth_paths": ["~/.codex/auth.json"],
            "install_cmd": "npm install -g @openai/codex",
            "auth_cmd": "codex login",
            "install_alt": None,
        },
        "opencode": {
            "binary": "opencode",
            "build_cmd": lambda task, cwd: f'opencode run "{task}"',
            "timeout": 300,
            "description": "OpenCode",
            "env_keys": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
            "auth_paths": ["~/.local/share/opencode/auth.json", "~/.config/opencode"],
            "install_cmd": "curl -fsSL https://opencode.ai/install | sh",
            "auth_cmd": "opencode auth login",
            "install_alt": "go install github.com/opencode-ai/opencode@latest",
        },
        "aider": {
            "binary": "aider",
            "build_cmd": lambda task, cwd: f'aider --yes --message "{task}"',
            "timeout": 300,
            "description": "Aider",
            "env_keys": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
            "auth_paths": [],
            "install_cmd": "pip install aider-chat",
            "auth_cmd": None,
            "install_alt": "pipx install aider-chat",
        },
    }

    # Agent preference order (used when no explicit default is set)
    AGENT_PRIORITY = ["claude_code", "codex", "opencode", "aider"]

    # Path where the user's chosen "default" agent is persisted
    DEFAULT_STATE_FILE = os.path.join("data", "auth", "default_coding_agent.json")

    # ------------------------------------------------------------------
    # Default agent persistence + introspection (used by REST API & GUI)
    # ------------------------------------------------------------------

    @classmethod
    def get_default_agent(cls) -> str:
        """Return the user's chosen default coding agent, or '' if unset."""
        try:
            if os.path.exists(cls.DEFAULT_STATE_FILE):
                import json as _json
                with open(cls.DEFAULT_STATE_FILE, "r") as f:
                    data = _json.load(f)
                    return data.get("default", "")
        except Exception:
            pass
        return ""

    @classmethod
    def set_default_agent(cls, name: str) -> bool:
        """Persist the user's chosen default coding agent. Returns True on success."""
        if name not in cls.AGENTS:
            return False
        try:
            import json as _json
            os.makedirs(os.path.dirname(cls.DEFAULT_STATE_FILE), exist_ok=True)
            with open(cls.DEFAULT_STATE_FILE, "w") as f:
                _json.dump({"default": name}, f)
            return True
        except Exception:
            return False

    @classmethod
    def list_agents_state(cls) -> list:
        """
        Return state info for every known agent.
        Each entry: {name, description, installed, authenticated, env_keys,
                     binary, install_cmd, is_default}
        """
        default = cls.get_default_agent()
        instance = cls()  # only used for _check_auth helper
        out = []
        for name in cls.AGENT_PRIORITY:
            agent = cls.AGENTS[name]
            installed = bool(shutil.which(agent["binary"]))
            auth_ok, _ = instance._check_auth(name) if installed else (False, "")
            out.append({
                "name": name,
                "description": agent["description"],
                "binary": agent["binary"],
                "installed": installed,
                "authenticated": auth_ok,
                "env_keys": list(agent.get("env_keys", [])),
                "install_cmd": agent.get("install_cmd", ""),
                "install_alt": agent.get("install_alt"),
                "auth_cmd": agent.get("auth_cmd"),
                "is_default": (name == default) if default else (name == cls.AGENT_PRIORITY[0] and installed),
            })
        return out

    @classmethod
    def get_install_command(cls, name: str) -> Optional[str]:
        """Return the install command string for an agent (caller decides whether to run it)."""
        agent = cls.AGENTS.get(name)
        return agent.get("install_cmd") if agent else None

    @classmethod
    def get_uninstall_command(cls, name: str) -> Optional[str]:
        """
        Return a best-guess uninstall command for an agent.
        Returns None if no safe uninstall is known — caller must NOT delete files blindly.
        """
        # Hand-curated. Prefer the same package manager that the install_cmd uses.
        recipes = {
            "claude_code": "npm uninstall -g @anthropic-ai/claude-code",
            "codex": "npm uninstall -g @openai/codex",
            "opencode": "rm -- \"$(command -v opencode)\"",
            "aider": "pip uninstall -y aider-chat",
        }
        return recipes.get(name)

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        # Parse the coding task
        task, options = self._parse_task(query)
        if not task:
            return SkillResult(
                success=False,
                error="Please describe the coding task you want to accomplish.",
            )

        # Detect which agent is available and authenticated
        agent_name = options.get("agent") or self._detect_agent(ctx)

        if agent_name and agent_name in self.AGENTS:
            # Verify authentication before running
            auth_ok, auth_msg = self._check_auth(agent_name)
            if not auth_ok:
                # Agent installed but not authenticated — provide setup instructions
                return SkillResult(
                    success=False,
                    error=auth_msg,
                    data={"agent": agent_name, "needs_auth": True},
                )
            return self._run_external_agent(agent_name, task, options, ctx)
        else:
            # No external agent — try internal fallback
            return self._run_internal_agent(task, options, ctx)

    # -------------------------------------------------------------------------
    # Task parsing
    # -------------------------------------------------------------------------

    def _parse_task(self, query: str) -> tuple:
        """Extract the coding task and options from the query."""
        options = {}

        # Extract explicit agent preference
        agent_match = re.search(
            r'\b(?:use|with|using|con)\s+(claude(?:\s+code)?|codex|opencode|aider)\b',
            query, re.IGNORECASE,
        )
        if agent_match:
            agent_str = agent_match.group(1).lower().replace(" ", "_")
            if "claude" in agent_str:
                options["agent"] = "claude_code"
            elif "codex" in agent_str:
                options["agent"] = "codex"
            elif "opencode" in agent_str:
                options["agent"] = "opencode"
            elif "aider" in agent_str:
                options["agent"] = "aider"
            query = query[:agent_match.start()] + query[agent_match.end():]

        # Extract working directory
        cwd_match = re.search(r'\b(?:in|en)\s+(/\S+|~/\S+)', query)
        if cwd_match:
            options["cwd"] = os.path.expanduser(cwd_match.group(1))
            query = query[:cwd_match.start()] + query[cwd_match.end():]

        # Clean up the task description
        task = query.strip()
        task = re.sub(
            r'^(code|program|write|create|fix|refactor|implement|build|make)\s+',
            '', task, flags=re.IGNORECASE,
        )
        # Keep the verb if that's all there was
        if not task.strip():
            task = query.strip()

        # Remove common prefixes
        task = re.sub(r'^(a |an |the |un |una |el |la )', '', task, flags=re.IGNORECASE)

        return task.strip(), options

    # -------------------------------------------------------------------------
    # Agent detection
    # -------------------------------------------------------------------------

    def _detect_agent(self, ctx: SkillContext) -> str:
        """Detect which coding agents are installed, return the best one.

        Honors the user-chosen default agent (set via the credentials GUI)
        if it is installed; otherwise falls back to AGENT_PRIORITY order.
        """
        default = self.get_default_agent()
        if default and default in self.AGENTS:
            agent = self.AGENTS[default]
            if shutil.which(agent["binary"]):
                return default
        for agent_name in self.AGENT_PRIORITY:
            agent = self.AGENTS[agent_name]
            if shutil.which(agent["binary"]):
                return agent_name
        return ""

    def _get_available_agents(self, ctx: SkillContext) -> list:
        """List all available agents."""
        available = []
        for name in self.AGENT_PRIORITY:
            agent = self.AGENTS[name]
            if shutil.which(agent["binary"]):
                available.append((name, agent["description"]))
        return available

    # -------------------------------------------------------------------------
    # Auth verification
    # -------------------------------------------------------------------------

    def _check_auth(self, agent_name: str) -> tuple:
        """Check if an agent has valid authentication.

        Returns (ok: bool, message: str).
        """
        agent = self.AGENTS.get(agent_name)
        if not agent:
            return False, f"Unknown agent: {agent_name}"

        # Check env vars
        for key in agent.get("env_keys", []):
            if os.environ.get(key):
                return True, ""

        # Check credential files/dirs on disk
        for path_pattern in agent.get("auth_paths", []):
            path = os.path.expanduser(path_pattern)
            if os.path.exists(path):
                return True, ""

        # Not authenticated — build helpful message
        desc = agent["description"]
        auth_cmd = agent.get("auth_cmd")
        env_keys = agent.get("env_keys", [])

        lines = [f"{desc} is installed but not authenticated."]
        lines.append("")
        lines.append("Options to authenticate:")
        if env_keys:
            lines.append(f"  1. Set env var: export {env_keys[0]}=your-key")
        if auth_cmd:
            n = 2 if env_keys else 1
            lines.append(f"  {n}. Run: {auth_cmd}")

        return False, "\n".join(lines)

    def _setup_instructions(self) -> str:
        """Generate install + auth instructions for all supported agents."""
        lines = ["No coding agent found. Install one of:\n"]
        for name in self.AGENT_PRIORITY:
            agent = self.AGENTS[name]
            desc = agent["description"]
            install = agent["install_cmd"]
            auth_cmd = agent.get("auth_cmd", "")
            env_keys = agent.get("env_keys", [])

            lines.append(f"  {desc}:")
            lines.append(f"    Install: {install}")
            if agent.get("install_alt"):
                lines.append(f"    Alt:     {agent['install_alt']}")
            if env_keys:
                lines.append(f"    Auth:    export {env_keys[0]}=your-key")
            if auth_cmd:
                lines.append(f"         or: {auth_cmd}")
            lines.append("")
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # External agent execution
    # -------------------------------------------------------------------------

    def _run_external_agent(self, agent_name: str, task: str, options: dict,
                            ctx: SkillContext) -> SkillResult:
        """Run an external coding agent via shell_exec."""
        agent = self.AGENTS[agent_name]
        cwd = options.get("cwd")

        # Sanitize task for shell (escape double quotes)
        safe_task = task.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')

        # Build the command
        cmd = agent["build_cmd"](safe_task, cwd)

        # Execute via shell_exec
        exec_kwargs = {
            "command": cmd,
            "timeout": agent["timeout"],
        }
        if cwd:
            exec_kwargs["cwd"] = cwd

        result = ctx.tools.execute(Tools.SHELL_EXEC, **exec_kwargs)

        if result.success:
            output = result.output or "(no output)"

            # Format the result
            formatted = self._format_agent_output(agent_name, task, output, ctx)

            return SkillResult(
                success=True,
                output=formatted,
                data={
                    "agent": agent_name,
                    "agent_description": agent["description"],
                    "task": task,
                    "cwd": cwd,
                    "raw_output_length": len(output),
                },
            )
        else:
            # Agent failed — try to diagnose
            error_msg = result.error or result.output or "Unknown error"

            # Check if it's a timeout
            if "timed out" in error_msg.lower():
                return SkillResult(
                    success=False,
                    error=(
                        f"{agent['description']} timed out after {agent['timeout']}s. "
                        f"The task may be too complex for a single run. "
                        f"Try breaking it into smaller steps."
                    ),
                    data={"agent": agent_name, "timeout": True},
                )

            return SkillResult(
                success=False,
                error=f"{agent['description']} failed: {error_msg[:500]}",
                data={"agent": agent_name, "task": task},
            )

    def _format_agent_output(self, agent_name: str, task: str, output: str,
                             ctx: SkillContext) -> str:
        """Format the agent's output using LLM if available."""
        if not ctx.llm:
            return f"[{self.AGENTS[agent_name]['description']}]\n\n{output[:5000]}"

        prompt = f"""An AI coding agent ({self.AGENTS[agent_name]['description']}) completed this task:

Task: {task}

Agent output:
{output[:4000]}

Summarize what was done:
- List files created/modified
- Describe the key changes
- Note any warnings or issues
- Keep it concise and actionable

If the output contains code, include the most important snippets."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            if response and response.content:
                return response.content
        except Exception:
            pass

        return f"[{self.AGENTS[agent_name]['description']}]\n\n{output[:5000]}"

    # -------------------------------------------------------------------------
    # Internal agent fallback
    # -------------------------------------------------------------------------

    def _run_internal_agent(self, task: str, options: dict,
                            ctx: SkillContext) -> SkillResult:
        """Fallback: use ARIA's multi-agent orchestrator with coder role."""
        orchestrator = ctx.tools.get(Tools.ORCHESTRATE) if ctx.tools else None

        if orchestrator:
            result = ctx.tools.execute(
                Tools.ORCHESTRATE,
                action="delegate",
                task=self._build_coder_prompt(task, options),
                role="coder",
            )

            if result.success:
                return SkillResult(
                    success=True,
                    output=f"[Internal coder agent]\n\n{result.output}",
                    data={
                        "agent": "internal_coder",
                        "task": task,
                    },
                )
            else:
                return SkillResult(
                    success=False,
                    error=f"Internal coder agent failed: {result.error}",
                    data={"agent": "internal_coder"},
                )

        # Last fallback: use LLM directly for code generation
        if ctx.llm:
            return self._llm_code_generation(task, ctx)

        return SkillResult(
            success=False,
            error=self._setup_instructions(),
        )

    def _build_coder_prompt(self, task: str, options: dict) -> str:
        """Build a detailed prompt for the internal coder sub-agent."""
        cwd = options.get("cwd", os.getcwd())
        return (
            f"You are a coding agent. Complete this task:\n\n"
            f"Task: {task}\n\n"
            f"Working directory: {cwd}\n\n"
            f"Instructions:\n"
            f"1. First analyze the codebase to understand the context\n"
            f"2. Plan the implementation\n"
            f"3. Write/modify the code using file_manager\n"
            f"4. If tests exist, run them with shell_exec\n"
            f"5. Report what you did clearly\n\n"
            f"Be precise, minimal, and test your changes."
        )

    def _llm_code_generation(self, task: str, ctx: SkillContext) -> SkillResult:
        """Last resort: use LLM directly for code generation."""
        prompt = f"""Generate code for this task:

{task}

Requirements:
- Write clean, production-ready code
- Include brief comments for non-obvious logic
- If multiple files are needed, clearly separate them with filenames
- Use appropriate language based on the task context"""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=f"[LLM code generation — no agent available]\n\n{response.content}",
                    data={"agent": "llm_direct", "task": task},
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Code generation failed: {e}")

        return SkillResult(success=False, error="Could not generate code")
