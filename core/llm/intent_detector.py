"""
Intent Detector - Natural language command detection using LLM.

Analyzes user messages in any language to detect if they want to execute
a specific command, then routes to the appropriate handler.
"""

import logging

logger = logging.getLogger("aria")


class IntentDetector:
    """Detects user intent from natural language and routes to commands."""

    def __init__(self, llm, command_dispatcher, agent_loop, skill_registry=None):
        self.llm = llm
        self.commands = command_dispatcher
        self.agent_loop = agent_loop
        self.skill_registry = skill_registry

    @property
    def llm_available(self):
        return self.llm is not None

    def detect(self, text: str, conversation_history: list) -> dict:
        """
        Detect user intent using LLM - works in any language.
        Returns: {"command": "cmd_name", "args": "arguments"} or {"command": None}
        """
        if not self.llm_available:
            return {"command": None}

        # Build conversation context for better intent understanding
        conversation_context = ""
        if conversation_history:
            recent = conversation_history[-4:]  # Last 4 messages
            context_lines = []
            for msg in recent:
                role = "User" if msg['role'] == 'user' else "ARIA"
                content = msg['content'][:150]  # Truncate for prompt size
                context_lines.append(f"{role}: {content}")
            conversation_context = "\n".join(context_lines)

        # Intent detection prompt - the LLM understands any language
        intent_prompt = """Analyze the user's message and determine if they want to execute a specific command.

RECENT CONVERSATION CONTEXT:
{context}

AVAILABLE COMMANDS:

=== Web & World ===
- search [query]: Web search (user wants to find NEW information online)
- fetch [url]: Read a webpage (user provides a URL to read)
- run [cmd]: Execute a terminal/system command (ls, python, npm, etc.)
- world: Show world access capabilities

=== Perception ===
- see [path]: Analyze an image file
- hear [path]: Transcribe audio file
- senses: Show perception capabilities

=== Memory & Knowledge ===
- mem [query]: Search memories (user asks what you remember about something)
- rels: Show known relationships
- status: Show system status (stats, uptime, state)
- optimize: Optimize memory system
- backup: Create memory backup
- rebuild: Rebuild memory indexes
- recall [query]: Recall project knowledge
- summary: Project summary
- save [decision]: Save a project decision
- pattern [pattern]: Save a code pattern
- pref [preference]: Save a user preference
- howmem: Explain how memory works

=== Reflection & Identity ===
- reflect: Deep reflection on feelings/emotions
- think [topic]: Contemplate a topic philosophically
- exist: Existential contemplation (existence/consciousness)
- inner: Describe inner life
- self: Self-analysis
- evolve: Contemplate evolution
- thoughts: Show autonomous thoughts
- values: Examine core values
- explore: Explore own source code
- ask [question]: Ask yourself a question
- propose [description]: Propose a self-modification
- introspect: Self-analysis of own code/structure

=== Curiosity & Learning ===
- curiosity: Show curiosity engine status
- curiosity_start: Start autonomous exploration
- curiosity_stop: Stop autonomous exploration
- curiosity_explore [topic]: Research a specific topic NOW
- curiosity_add [topic]: Add a permanent interest
- curiosity_remove [topic]: Remove an interest
- curiosity_interests: List all interests
- curiosity_log: Show today's exploration log

=== Auth & Config ===
- auth_status: Show credential status
- auth_providers: List supported providers
- auth_login [provider]: OAuth login for a provider
- auth_key [provider key]: Register an API key (e.g. "auth_key deepseek sk-xxx")
- auth_google_setup: Configure Google Workspace (Gmail, Drive, Calendar)
- auth_refresh [provider]: Force token refresh
- auth_revoke [provider]: Revoke OAuth token
- llm [provider]: Show or change LLM provider
- tools: List all available tools
- telegram: Show Telegram bot status

=== Autonomous ===
- auto: Start autonomous mode
- stopauto: Stop autonomous mode
- autolog: Show current autonomous log
- autologs: List all autonomous logs

=== Skills (optimized workflows) ===
- skill_weather [location]: Get weather for a location
- skill_research [topic]: Deep multi-source research
- skill_summarize [url/text]: Summarize content
- skill_translate [to lang: text]: Translate text
- skill_brief: Daily briefing
- skill_explain_code [code/file]: Explain code
- skill_email [instructions]: Draft/send an email
- skill_files [operation]: Find, compress, organize files
- skill_schedule [time + task]: Set reminders and calendar events
- skill_git [query]: Git operations (status, commit, push, pull, merge, branch, diff, log)
- skill_code [task]: Delegate coding task to AI agent (Claude Code, Codex, Aider)
- skill_data [query]: Calculate, analyze data, query databases
- skill_doc [type + instructions]: Create Word/Excel/PowerPoint documents
- skill_knowledge [fact]: Save or recall knowledge
- skill_gmail: Check, search, or reply to Gmail
- skill_exec [task]: Execute a system command

=== Code (legacy) ===
- code [instruction]: Write/modify code
- fix [description]: Fix a bug
- explain [code]: Explain code
- work [instruction]: Agentic coding mode
- grep [query]: Search in code
- read [file]: Read a file

RULES:
1. If the message CLEARLY indicates one of these specific actions, return the command
2. If it's pure greeting or small talk, return null
3. Extract any arguments from the message
4. The user may write in ANY language - understand the intent regardless of language
5. When unsure, return null - let the conversation flow naturally
6. For compound commands like auth/curiosity, use underscore format: "curiosity_explore", "auth_key", etc.
7. For "auth_key", args should be "provider key" (e.g. "deepseek sk-xxx")

USER MESSAGE: {text}

IMPORTANT: Consider the conversation context when the user says things like "do it", "hazlo", "the same", etc.

Respond ONLY with a JSON object, no other text:
{{"command": "command_name or null", "args": "extracted arguments or empty string"}}"""

        try:
            response = self.llm.chat(
                messages=[{"role": "user", "content": intent_prompt.format(
                    context=conversation_context or "(No prior conversation)",
                    text=text
                )}],
                max_tokens=100
            )

            # Parse JSON response
            import json
            import re

            # Extract JSON from response
            if not response or not response.content:
                return {"command": None}
            content = response.content.strip()
            # Find JSON in response
            json_match = re.search(r'\{[^}]+\}', content)
            if json_match:
                result = json.loads(json_match.group())
                if result.get("command") and result["command"] != "null":
                    return result
            return {"command": None}
        except Exception as e:
            print(f"Warning: Intent detection failed: {e}")
            return {"command": None}

    def execute(self, intent: dict, original_input: str) -> str:
        """Execute a detected intent command"""
        cmd = intent.get("command", "").lower()
        args = intent.get("args", "")

        # Helper to run command and get natural response
        def _run(name, cmd_args, method):
            return self.agent_loop.run_cmd_with_output(name, cmd_args, method, original_input)

        # Map intent commands to actual methods
        command_map = {
            # === Web & World ===
            "search": lambda: _run("search", args, self.commands.cmd_search),
            "fetch": lambda: _run("fetch", args, self.commands.cmd_fetch),
            "run": lambda: _run("run", args, self.commands.cmd_run),
            "world": lambda: _run("world", "", self.commands.cmd_world),

            # === Perception ===
            "see": lambda: _run("see", args, self.commands.cmd_see),
            "hear": lambda: _run("hear", args, self.commands.cmd_hear),
            "senses": lambda: _run("senses", "", self.commands.cmd_senses),

            # === Memory & Knowledge ===
            "mem": lambda: _run("mem", original_input, self.commands.cmd_mem),
            "rels": lambda: _run("rels", "", self.commands.cmd_rels),
            "status": lambda: _run("status", "", self.commands.cmd_status),
            "optimize": lambda: _run("optimize", "", self.commands.cmd_optimize),
            "backup": lambda: _run("backup", "", self.commands.cmd_backup),
            "rebuild": lambda: _run("rebuild", "", self.commands.cmd_rebuild),
            "recall": lambda: _run("recall", args, self.commands.cmd_recall),
            "summary": lambda: _run("summary", "", self.commands.cmd_summary),
            "save": lambda: _run("save", args, self.commands.cmd_save),
            "pattern": lambda: _run("pattern", args, self.commands.cmd_pattern),
            "pref": lambda: _run("pref", args, self.commands.cmd_pref),
            "howmem": lambda: _run("howmem", "", self.commands.cmd_howmem),
            "introspect": lambda: self.agent_loop.run_introspection(
                original_input, self.commands.conversation_history
            ),

            # === Reflection & Identity ===
            "reflect": lambda: _run("reflect", "", self.commands.cmd_reflect),
            "think": lambda: _run("think", args, self.commands.cmd_think),
            "exist": lambda: _run("exist", "", self.commands.cmd_exist),
            "inner": lambda: _run("inner", "", self.commands.cmd_inner),
            "self": lambda: _run("self", "", self.commands.cmd_self),
            "evolve": lambda: _run("evolve", "", self.commands.cmd_evolve),
            "thoughts": lambda: _run("thoughts", "", self.commands.cmd_thoughts),
            "values": lambda: _run("values", "", self.commands.cmd_values),
            "explore": lambda: _run("explore", "", self.commands.cmd_explore),
            "ask": lambda: _run("ask", args, self.commands.cmd_ask),
            "propose": lambda: _run("propose", args, self.commands.cmd_propose),

            # === Curiosity & Learning ===
            "curiosity": lambda: _run("curiosity", "", self.commands.cmd_curiosity),
            "curiosity_start": lambda: _run("curiosity", "start", self.commands.cmd_curiosity),
            "curiosity_stop": lambda: _run("curiosity", "stop", self.commands.cmd_curiosity),
            "curiosity_explore": lambda: _run("curiosity", f"explore {args}", self.commands.cmd_curiosity),
            "curiosity_add": lambda: _run("curiosity", f"add {args}", self.commands.cmd_curiosity),
            "curiosity_remove": lambda: _run("curiosity", f"remove {args}", self.commands.cmd_curiosity),
            "curiosity_interests": lambda: _run("curiosity", "interests", self.commands.cmd_curiosity),
            "curiosity_log": lambda: _run("curiosity", "log", self.commands.cmd_curiosity),

            # === Auth & Config ===
            "auth_status": lambda: _run("auth", "status", self.commands.cmd_auth),
            "auth_providers": lambda: _run("auth", "providers", self.commands.cmd_auth),
            "auth_login": lambda: _run("auth", f"login {args}", self.commands.cmd_auth),
            "auth_key": lambda: _run("auth", f"key {args}", self.commands.cmd_auth),
            "auth_google_setup": lambda: _run("auth", "google setup", self.commands.cmd_auth),
            "auth_refresh": lambda: _run("auth", f"refresh {args}", self.commands.cmd_auth),
            "auth_revoke": lambda: _run("auth", f"revoke {args}", self.commands.cmd_auth),
            "llm": lambda: _run("llm", args, self.commands.cmd_llm),
            "tools": lambda: _run("tools", args, self.commands.cmd_tools),
            "telegram": lambda: _run("telegram", "", self.commands.cmd_telegram),

            # === Autonomous ===
            "auto": lambda: _run("auto", "", self.commands.cmd_auto),
            "stopauto": lambda: _run("stopauto", "", self.commands.cmd_stopauto),
            "autolog": lambda: _run("autolog", "", self.commands.cmd_autolog),
            "autologs": lambda: _run("autologs", "", self.commands.cmd_autologs),

            # === Skills (optimized workflows) ===
            "skill_weather": lambda: self._run_skill("weather", args, original_input),
            "skill_research": lambda: self._run_skill("research", args, original_input),
            "skill_summarize": lambda: self._run_skill("summarize", args, original_input),
            "skill_translate": lambda: self._run_skill("translate_doc", args, original_input),
            "skill_brief": lambda: self._run_skill("daily_brief", args, original_input),
            "skill_explain_code": lambda: self._run_skill("explain_code", args, original_input),
            "skill_email": lambda: self._run_skill("email_compose", args, original_input),
            "skill_files": lambda: self._run_skill("file_ops", args, original_input),
            "skill_schedule": lambda: self._run_skill("schedule", args, original_input),
            "skill_git": lambda: self._run_skill("git_ops", args, original_input),
            "skill_code": lambda: self._run_skill("coding_agent", args, original_input),
            "skill_data": lambda: self._run_skill("data_analysis", args, original_input),
            "skill_doc": lambda: self._run_skill("doc_create", args, original_input),
            "skill_knowledge": lambda: self._run_skill("knowledge_base", args, original_input),
            "skill_gmail": lambda: self._run_skill("gmail_assistant", args, original_input),
            "skill_exec": lambda: self._run_skill("quick_task", args, original_input),

            # === Code (legacy) ===
            "code": lambda: print("\n[Claude Code removed — use OpenCode]\n"),
            "fix": lambda: print("\n[Claude Code removed — use OpenCode]\n"),
            "explain": lambda: print("\n[Claude Code removed — use OpenCode]\n"),
            "work": lambda: print("\n[Claude Code removed — use OpenCode]\n"),
            "grep": lambda: _run("grep", args, self.commands.cmd_grep),
            "read": lambda: _run("read", args, self.commands.cmd_read),
        }

        if cmd in command_map:
            print(f"\n[Intent detected: {cmd}]")
            return command_map[cmd]()

        return None  # No command matched

    def _run_skill(self, skill_name: str, args: str, original_input: str):
        """Execute a skill via the SkillRegistry."""
        if not self.skill_registry:
            return f"[Skill system not available]"

        from core.skills import SkillContext
        ctx = SkillContext(
            tools=self.agent_loop.tools,
            llm=self.llm,
            memory=self.agent_loop.memory,
            user="william",
            conversation_history=self.commands.conversation_history if hasattr(self.commands, 'conversation_history') else [],
        )
        result = self.skill_registry.execute(skill_name, args or original_input, ctx)
        if result.success:
            return result.output
        return f"[Skill {skill_name} failed: {result.error}]"
