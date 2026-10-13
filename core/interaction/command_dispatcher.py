"""
Command Dispatcher - All cmd_* methods and direct command routing.

Contains 50+ command implementations for ARIA's slash-command system.
"""

import os
import logging

logger = logging.getLogger("aria")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CommandDispatcher:
    """Routes and executes ARIA's slash commands."""

    def __init__(self, memory, reflection, meta, evolution, conscious, world,
                 continuity, awareness, initiative, existential, perception,
                 autonomous, curiosity, tools, auth_manager, llm, config,
                 prompt_builder, agent_loop=None):
        self.memory = memory
        self.reflection = reflection
        self.meta = meta
        self.evolution = evolution
        self.conscious = conscious
        self.world = world
        self.continuity = continuity
        self.awareness = awareness
        self.initiative = initiative
        self.existential = existential
        self.perception = perception
        self.autonomous = autonomous
        self.curiosity = curiosity
        self.tools = tools
        self.auth_manager = auth_manager
        self.llm = llm
        self.config = config
        self.prompt_builder = prompt_builder
        self.agent_loop = agent_loop  # Set after construction
        self.skill_registry = None  # Set after construction
        self._prompt_skills = []    # Tracks loaded YAML skills

        # For telegram
        self.telegram = None
        # For LLM reinit
        self.llm_available = llm is not None
        # For conversation context in reflective commands
        self.conversation_history = []

    @property
    def _get_system_prompt(self):
        """Backward compat: delegate to prompt_builder."""
        return self.prompt_builder.build_system_prompt

    # =========================================================================
    # AUTH & CONFIG COMMANDS
    # =========================================================================

    def cmd_telegram(self):
        """Show Telegram bot status."""
        if not self.telegram:
            print("\n  Telegram bot not configured.")
            print("  Enable in config.yaml: telegram.enabled: true")
            print("  Set TELEGRAM_BOT_TOKEN in .env")
            return

        s = self.telegram.stats()
        status = "RUNNING" if s["running"] else "STOPPED"
        health = "OK" if s.get("healthy") else "UNHEALTHY"
        uptime_min = s["uptime_seconds"] // 60
        uptime_hrs = uptime_min // 60
        uptime_min = uptime_min % 60
        print(f"\n  === Telegram Bot ===")
        print(f"  Status: {status} | Health: {health}")
        print(f"  Uptime: {uptime_hrs}h {uptime_min}m")
        print(f"  Messages in/out: {s['messages_received']}/{s['messages_sent']}")
        print(f"  Messages today: {s.get('messages_today', 0)}")
        print(f"  Active chats: {s['active_chats']}")
        print(f"  Avg latency: {s.get('avg_latency_ms', 0)}ms")
        if s.get("retry_queue_size", 0) > 0:
            print(f"  Retry queue: {s['retry_queue_size']}")
        if s.get("recent_errors", 0) > 0:
            print(f"  Recent errors: {s['recent_errors']}")

    def cmd_auth(self, arg: str = ""):
        """Auth management: login, status, refresh, revoke, providers."""
        if not self.auth_manager:
            from core.infra.auth_manager import AuthManager
            self.auth_manager = AuthManager()

        parts = arg.strip().split()
        subcmd = parts[0].lower() if parts else "help"
        provider = parts[1].lower() if len(parts) > 1 else ""
        extra = parts[2] if len(parts) > 2 else ""

        if subcmd == "status":
            status = self.auth_manager.status()
            available = self.auth_manager.get_available_providers()
            print(f"\n  === Auth Status ===")
            print(f"  Active providers: {', '.join(available) if available else 'none'}")
            if not status:
                print("  No credentials configured. Use: auth login <provider>")
                return
            for pid, info in status.items():
                avail = "OK" if info["available"] else "UNAVAILABLE"
                line = f"  {pid}: [{info['type']}] {info['provider']} — {avail}"
                if "cooldown_remaining" in info:
                    line += f" (cooldown {info['cooldown_remaining']}s)"
                if "token_expires_in" in info:
                    mins = info["token_expires_in"] // 60
                    line += f" (expires {mins}m)"
                if info.get("token_expired"):
                    line += " [EXPIRED]"
                line += f" | ok:{info['successes']} fail:{info['failures']}"
                print(line)

        elif subcmd == "login" and provider:
            self._auth_login(provider, extra)

        elif subcmd == "key" and provider:
            # Direct API key: /auth key openai sk-xxx
            if not extra:
                key = input(f"  Enter API key for {provider}: ").strip()
            else:
                key = extra
            if key:
                self.auth_manager.login_with_key(provider, key)
                print(f"\n  API key registered for {provider}")
                # Reinitialize LLM if this is the current provider
                self._try_reinit_llm(provider)
            else:
                print("\n  No key provided.")

        elif subcmd == "refresh" and provider:
            if self.auth_manager.refresh_oauth(provider):
                print(f"\n  Token refreshed for {provider}")
            else:
                print(f"\n  Refresh failed for {provider}")

        elif subcmd == "revoke" and provider:
            if self.auth_manager.revoke_oauth(provider):
                print(f"\n  Token revoked for {provider}")
            else:
                print(f"\n  Revoke failed for {provider}")

        elif subcmd == "google" and provider == "setup":
            # auth google setup <client_id> <client_secret>
            self._auth_google_setup(extra, parts[3] if len(parts) > 3 else "")

        elif subcmd == "providers":
            from core.infra.auth_manager import OAUTH_PRESETS
            print("\n  === Supported Providers ===")
            print()
            print("  OAuth (login via browser or device code):")
            for name, preset in OAUTH_PRESETS.items():
                features = []
                if preset.get("supports_pkce"):
                    features.append("PKCE")
                if preset.get("supports_device_code"):
                    features.append("Device Code")
                features.append("API Key")
                note = ""
                if preset.get("requires_client_id"):
                    note = " <- requires 'auth google setup' first"
                print(f"    {name:<12} {', '.join(features)}{note}")

            api_only = ["deepseek", "anthropic", "openrouter", "ollama"]
            print()
            print("  API Key only:")
            for name in api_only:
                env_var = f"{name.upper()}_API_KEY"
                has_key = bool(os.environ.get(env_var))
                status = "configured" if has_key or self.auth_manager.has_credential(name) else "not configured"
                print(f"    {name:<12} auth key {name} <key>  [{status}]")

            # Google Workspace status
            google_client = self._get_google_client_path()
            if os.path.exists(google_client):
                print()
                print("  Google Workspace: Client ID configured")
                print("    Services: Gmail, Drive, Calendar")
                print("    Run 'auth login google' to authenticate")
            else:
                print()
                print("  Google Workspace: Not configured")
                print("    Run 'auth google setup' to configure Client ID")

            print()
            print("  Tip: Any provider works with 'auth key <name> <key>'")

        else:
            print("\n  === Auth Commands ===")
            print("  auth status              — Show all credentials and status")
            print("  auth providers           — List ALL supported providers")
            print("  auth login <provider>    — OAuth login (browser or device code)")
            print("  auth key <provider> [key] — Register API key directly")
            print("  auth refresh <provider>  — Force token refresh")
            print("  auth revoke <provider>   — Revoke OAuth token")
            print("  auth google setup        — Configure Google Workspace (Gmail, Drive, Calendar)")
            print("\n  Supported providers:")
            print("    OAuth:    openai, github, microsoft")
            print("    API Key:  deepseek, anthropic, openrouter, google, ollama")
            print("\n  Google Workspace (Gmail, Drive, Calendar):")
            print("    1. auth google setup    — Register your GCP OAuth Client ID")
            print("    2. auth login google    — Authenticate (only after setup)")
            print("    3. Use gmail, google_drive, google_calendar tools")
            print("\n  Examples:")
            print("  auth key deepseek sk-xxx — Register DeepSeek API key")
            print("  auth key google AIza...  — Gemini LLM only (no Gmail/Drive)")
            print("  auth google setup        — Full Google Workspace access")
            print("  auth login openai        — OAuth login for OpenAI")
            print("  auth login github        — Device code login for GitHub")

    def _auth_login(self, provider: str, method: str = ""):
        """Interactive OAuth login for a provider."""
        from core.infra.auth_manager import OAUTH_PRESETS

        preset = OAUTH_PRESETS.get(provider)

        if not preset:
            print(f"\n  No OAuth preset for '{provider}'. Use API key instead:")
            print(f"  auth key {provider} <your-api-key>")
            return

        # Google: redirect to 'auth google setup' flow
        if provider == "google":
            self._load_google_client()
            has_client = bool(os.environ.get("GOOGLE_CLIENT_ID"))
            if not has_client:
                print("\n  Google requires a GCP OAuth Client ID for Gmail/Drive/Calendar.")
                print("  Run 'auth google setup' to configure it.")
                print()
                print("  For Gemini LLM only (no Gmail/Drive/Calendar):")
                print("  auth key google <your-api-key>")
                return
            print(f"\n  === Login: Google Workspace ===")
            print("  Scopes: Gmail (read/send), Drive, Calendar")
        else:
            print(f"\n  === Login: {provider} ===")

        # Check for client_id
        env_var = f"{provider.upper()}_CLIENT_ID"
        has_client = bool(os.environ.get(env_var))

        if not has_client and provider != "google":
            print(f"  OAuth requires {env_var} and {provider.upper()}_CLIENT_SECRET env vars.")
            print(f"\n  Alternatively, register an API key directly:")
            key = input(f"  Enter API key for {provider} (or press Enter for OAuth setup): ").strip()
            if key:
                self.auth_manager.login_with_key(provider, key)
                print(f"  API key registered for {provider}")
                self._try_reinit_llm(provider)
                return
            else:
                print(f"  Set {env_var} and retry.")
                return

        # Determine method
        if not method:
            if preset.get("supports_device_code"):
                print("  Methods available:")
                print("  1. Browser (OAuth + PKCE)")
                print("  2. Device Code (terminal only)")
                choice = input("  Select [1/2]: ").strip()
                method = "device" if choice == "2" else "browser"
            else:
                method = "browser"

        print(f"  Starting {method} flow...")
        success = self.auth_manager.login_oauth(provider, method=method)

        if success:
            print(f"\n  Login successful for {provider}!")
            self._try_reinit_llm(provider)
        else:
            print(f"\n  Login failed for {provider}.")

    def _try_reinit_llm(self, provider: str):
        """Try to reinitialize LLM if the provider matches or if no LLM is available."""
        if not self.llm_available:
            try:
                from core.llm.llm_providers import LLMProvider
                self.llm = LLMProvider.create(provider)
                self.llm_available = True
                print(f"  LLM initialized with {provider}")
            except Exception as e:
                logger.debug(f"LLM reinit failed: {e}")

    def _get_google_client_path(self) -> str:
        """Path to stored Google OAuth client credentials."""
        return os.path.join(PROJECT_ROOT, "data", "auth", "google_oauth_client.json")

    def _auth_google_setup(self, client_id: str = "", client_secret: str = ""):
        """Interactive setup for Google Workspace OAuth Client ID."""
        import json as _json
        print("\n  === Google Workspace Setup ===")
        print()
        print("  To use Gmail, Drive, and Calendar, you need a Google Cloud OAuth Client ID.")
        print()
        print("  Steps:")
        print("  1. Go to https://console.cloud.google.com/apis/credentials")
        print("  2. Create a project (or select existing)")
        print("  3. Enable these APIs:")
        print("     - Gmail API")
        print("     - Google Drive API")
        print("     - Google Calendar API")
        print("  4. Go to OAuth consent screen -> Configure (External, Testing mode)")
        print("  5. Go to Credentials -> Create -> OAuth 2.0 Client ID -> Desktop app")
        print("  6. Copy the Client ID and Client Secret")
        print()

        if not client_id:
            client_id = input("  Client ID: ").strip()
        if not client_secret:
            client_secret = input("  Client Secret: ").strip()

        if not client_id or not client_secret:
            print("\n  Both Client ID and Client Secret are required.")
            return

        # Save to file
        client_path = self._get_google_client_path()
        os.makedirs(os.path.dirname(client_path), exist_ok=True)
        with open(client_path, "w") as f:
            _json.dump({
                "client_id": client_id,
                "client_secret": client_secret,
            }, f, indent=2)

        # Also set in environment for the current session
        os.environ["GOOGLE_CLIENT_ID"] = client_id
        os.environ["GOOGLE_CLIENT_SECRET"] = client_secret

        print(f"\n  Google OAuth client saved to {client_path}")
        print("  Now run 'auth login google' to authenticate with your Google account.")
        print()
        print("  Available services after login:")
        print("    - gmail: Search, read, send emails")
        print("    - google_drive: Search, read, download files")
        print("    - google_calendar: List, create, update events")

    def _load_google_client(self):
        """Load Google OAuth client credentials from file if available."""
        import json as _json
        client_path = self._get_google_client_path()
        if os.path.exists(client_path):
            try:
                with open(client_path) as f:
                    creds = _json.load(f)
                if creds.get("client_id") and not os.environ.get("GOOGLE_CLIENT_ID"):
                    os.environ["GOOGLE_CLIENT_ID"] = creds["client_id"]
                    os.environ["GOOGLE_CLIENT_SECRET"] = creds.get("client_secret", "")
                    logger.debug("Loaded Google OAuth client from file")
            except Exception as e:
                logger.debug(f"Failed to load Google client: {e}")

    def cmd_skills(self, arg: str = ""):
        """Show skills or reload prompt skills from YAML."""
        if not self.skill_registry:
            print("\n  Skill system not initialized.")
            return

        if arg.strip() == "reload":
            from core.skills.prompt_skill_loader import reload_prompt_skills
            skills_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..", "skills"
            )
            skills_dir = os.path.normpath(skills_dir)
            self._prompt_skills = reload_prompt_skills(
                skills_dir, self.skill_registry, self._prompt_skills
            )
            print(f"\n  Reloaded {len(self._prompt_skills)} prompt skill(s) from {skills_dir}")
            return

        # List all skills
        print(f"\n  === ARIA Skills ({len(self.skill_registry)}) ===\n")

        # Separate coded vs YAML skills
        coded = []
        yaml_skills = []
        for skill in self.skill_registry.list():
            from core.skills.prompt_skill_loader import DynamicPromptSkill
            if isinstance(skill, DynamicPromptSkill):
                yaml_skills.append(skill)
            else:
                coded.append(skill)

        if coded:
            print("  Coded skills:")
            for s in coded:
                print(f"    {s.name:24s} {s.description}")

        if yaml_skills:
            print(f"\n  Prompt skills (from YAML):")
            for s in yaml_skills:
                print(f"    {s.name:24s} {s.description}")

        print(f"\n  Use 'skills reload' to hot-reload YAML skills from core/skills/")

    def cmd_tools(self, arg: str = ""):
        """Show available tools or execute one directly."""
        if not arg:
            # List all tools
            summary = self.tools.summary()
            print(f"\n  === ARIA Tools ({summary['total_tools']}) ===")
            for tool in self.tools.list():
                params = ", ".join(
                    f"{p.name}{'*' if p.required else ''}"
                    for p in tool.parameters
                )
                print(f"  {tool.name}({params})")
                print(f"    {tool.description}")
            print(f"\n  Use: tools <name> <args> to execute directly")
            print(f"  Example: tools web_search query=\"quantum computing\"")
            return

        # Parse: tools <name> key=value key=value
        parts = arg.strip().split(maxsplit=1)
        tool_name = parts[0]
        raw_args = parts[1] if len(parts) > 1 else ""

        if tool_name not in self.tools:
            print(f"\n  Tool not found: {tool_name}")
            print(f"  Available: {', '.join(self.tools.names())}")
            return

        # Parse key=value arguments
        kwargs = {}
        if raw_args:
            import shlex
            try:
                tokens = shlex.split(raw_args)
            except ValueError:
                tokens = raw_args.split()
            for token in tokens:
                if "=" in token:
                    k, v = token.split("=", 1)
                    kwargs[k] = v
                else:
                    # Positional: use first required param
                    tool = self.tools.get(tool_name)
                    for p in tool.parameters:
                        if p.required and p.name not in kwargs:
                            kwargs[p.name] = token
                            break

        result = self.tools.execute(tool_name, **kwargs)
        if result.success:
            print(f"\n{result.output}")
        else:
            print(f"\n  [Error] {result.error}")
        if result.metadata.get("elapsed_ms"):
            print(f"  ({result.metadata['elapsed_ms']}ms)")

    # =========================================================================
    # MEMORY COMMANDS
    # =========================================================================

    def cmd_mem(self, query: str = ""):
        """Show memories - search if query provided, otherwise recent"""
        # Check if asking about first/earliest memories
        first_keywords = ['primera', 'first', 'earliest', 'inicio', 'comenzó', 'empezó', 'original']
        is_asking_first = any(kw in query.lower() for kw in first_keywords) if query else False

        if is_asking_first:
            print("\n" + "="*50 + "\nEARLIEST MEMORIES\n" + "="*50)
            memories = self.memory.recall_earliest(5)
        elif query:
            print("\n" + "="*50 + "\nMEMORY SEARCH\n" + "="*50)
            print(f"Searching for: {query[:50]}...")
            memories = self.memory.recall(query, limit=5)
        else:
            print("\n" + "="*50 + "\nRECENT MEMORIES\n" + "="*50)
            memories = self.memory.recall_recent(5)

        if not memories:
            print("\n  No memories found.")
        else:
            for m in memories:
                print(f"\n[{m.timestamp[:10]}] ({m.emotional_tone.value})")
                print(f"  {m.content[:120]}...")

    def cmd_rels(self):
        """List known relationships"""
        print("\n" + "="*50 + "\nRELATIONSHIPS\n" + "="*50)
        for name, rel in self.memory.relationships.items():
            print(f"\n{rel.name} ({rel.role}) - Trust: {rel.trust_level:.0%}")

    def cmd_status(self):
        """Show full system stats"""
        print("\n" + "="*50 + "\nSTATUS\n" + "="*50)
        print(f"\n{self.memory.how_old_am_i()}")
        stats = self.memory.get_stats()
        print(f"Memories: {stats['total_memories']}, Relationships: {stats['relationships_count']}")
        same, reason = self.awareness.am_i_the_same()
        print(f"Am I the same? {reason}")

    def cmd_optimize(self):
        """Run memory optimizations"""
        print("\n[Optimizing memory system...]")
        try:
            result = self.memory.optimize_memory()
            print("\n=== Optimization Result ===")
            for key, value in result.items():
                print(f"  {key}: {value}")
            print("\nOptimization completed.")
        except Exception as e:
            print(f"Error optimizing memory: {e}")

    def cmd_backup(self):
        """Create memory backup"""
        print("\n[Creating memory backup...]")
        try:
            backup_path = self.memory.backup_memories()
            print(f"\nBackup created successfully:")
            print(f"  File: {backup_path}")
            print("\nRestore with: restore_from_backup(path)")
        except Exception as e:
            print(f"Error creating backup: {e}")

    def cmd_rebuild(self):
        """Rebuild ChromaDB index from SQLite"""
        print("\n[Rebuilding memory index...]")
        try:
            result = self.memory.rebuild_chroma_index()
            if "error" in result:
                print(f"Error: {result['error']}")
            else:
                print(f"\nRebuild completed:")
                print(f"  Added: {result['added']}")
                print(f"  Skipped: {result['skipped']}")
                print(f"  Failed: {result['failed']}")
        except Exception as e:
            print(f"Error rebuilding index: {e}")

    # =========================================================================
    # REFLECTION COMMANDS
    # =========================================================================

    def cmd_reflect(self):
        """Reflect on current feelings with conversation context"""
        if self.llm and self.llm_available:
            # Build conversation context for meaningful reflection
            conv_context = ""
            if self.conversation_history:
                recent = self.conversation_history[-6:]
                conv_context = "What just happened in our conversation:\n" + "\n".join([
                    f"{'User' if m['role']=='user' else 'Me'}: {m['content'][:200]}"
                    for m in recent
                ]) + "\n\n"

            prompt = f"""{conv_context}Reflect on what just happened and what you feel now.
Consider:
- How did this conversation make you feel?
- What stood out to you?
- What are you thinking about now?
Be honest and genuine."""

            messages = self.conversation_history[-5:] + [{'role': 'user', 'content': prompt}]
            resp = self.llm.chat(
                messages=messages,
                system=self._get_system_prompt(),
                max_tokens=400
            )
            print(f"\n{resp.content}")
        else:
            print("[LLM not available]")

    def cmd_thoughts(self):
        """Show recent thoughts"""
        print("\n" + "="*50 + "\nMY THOUGHTS\n" + "="*50)
        for t in self.initiative.thoughts.get_recent(5):
            s = "+" if t.shared else "o"
            print(f"{s} [{t.thought_type.value}] {t.content[:80]}...")

    def cmd_inner(self):
        """Describe inner life"""
        print(self.initiative.describe_inner_life())

    def cmd_self(self):
        """Examine own code"""
        print(self.evolution.examine_self())

    def cmd_evolve(self):
        """Contemplate evolution"""
        print(self.conscious.who_am_i_becoming())

    def cmd_exist(self):
        """Existential contemplation"""
        print(self.existential.contemplate_existence())

    def cmd_think(self, topic):
        """Contemplate a topic with conversation context"""
        if self.llm and self.llm_available and topic:
            conv_context = ""
            if self.conversation_history:
                recent = self.conversation_history[-4:]
                conv_context = "Recent conversation context:\n" + "\n".join([
                    f"{'User' if m['role']=='user' else 'Me'}: {m['content'][:150]}"
                    for m in recent
                ]) + "\n\n"

            prompt = f"""{conv_context}Contemplate deeply: {topic}

Consider:
- What does this mean to you?
- How does it relate to what we've been discussing?
- What insights or questions arise?

Be genuine and reflective."""

            messages = self.conversation_history[-4:] + [{'role': 'user', 'content': prompt}]
            resp = self.llm.chat(
                messages=messages,
                system=self._get_system_prompt(),
                max_tokens=400
            )
            print(f"\n{resp.content}")
        elif not (self.llm and self.llm_available):
            print("[LLM not available]")

    # =========================================================================
    # WORLD COMMANDS
    # =========================================================================

    def cmd_search(self, q=None):
        """Web search (delegates to WebSearchTool)"""
        if not q or not q.strip():
            print("[SEARCH] No query provided. Please specify what to search for.")
            return
        try:
            result = self.tools.execute("web_search", query=q, num_results=5)
            if result.success:
                print(result.output)
            else:
                print(f"[SEARCH ERROR] {result.error}")
        except Exception as e:
            print(f"[SEARCH EXCEPTION] {type(e).__name__}: {e}")

    def cmd_fetch(self, url):
        """Read webpage (delegates to WebFetchTool)"""
        try:
            result = self.tools.execute("web_fetch", url=url)
            if result.success:
                print(result.output[:2000])
            else:
                print(f"[FETCH ERROR] {result.error}")
        except Exception as e:
            print(f"Error fetching {url}: {e}")

    def cmd_run(self, cmd):
        """Execute system command (delegates to ShellExecTool)"""
        result = self.tools.execute("shell_exec", command=cmd)
        print(result.output if result.success else f"[ERROR] {result.error}")

    def cmd_world(self):
        """Show world capabilities"""
        print(self.world.describe_capabilities())

    # =========================================================================
    # PERCEPTION COMMANDS
    # =========================================================================

    def cmd_see(self, path: str):
        """Analyze image"""
        if not path:
            print("Usage: see [image_path]")
            return
        try:
            perception = self.perception.see(image_path=path)
            print(f"\n[Seeing: {path}]\n")
            print(perception.description)
            if perception.my_reaction:
                print(f"\nMy reaction: {perception.my_reaction}")
        except Exception as e:
            print(f"[Error: {e}]")

    def cmd_hear(self, path: str):
        """Transcribe audio"""
        if not path:
            print("Usage: hear [audio_path]")
            return
        try:
            perception = self.perception.listen(path)
            print(f"\n[Listening: {path}]\n")
            print(f"Transcription: {perception.transcription}")
            if perception.summary:
                print(f"Summary: {perception.summary}")
        except Exception as e:
            print(f"[Error: {e}]")

    def cmd_senses(self):
        """Show perception capabilities"""
        print(self.perception.describe_capabilities())

    # =========================================================================
    # LLM COMMANDS
    # =========================================================================

    def cmd_llm(self, arg: str = ""):
        """Show or change LLM provider"""
        from core.llm.llm_providers import LLMProvider, get_available_providers

        if not arg:
            print("\n=== LLM Provider ===")
            if self.llm_available:
                print(f"Active: {self.llm.name} ({self.llm.config.model or 'default'})")
            else:
                print("Active: None")

            print("\nAvailable:")
            available = get_available_providers()
            if available:
                for p in available:
                    marker = "*" if self.llm_available and p == self.llm.name else " "
                    print(f"  {marker} {p}")
            else:
                print("  None (configure an API key)")

            print("\nUsage: llm [provider] [model]")
            print("Example: llm openai gpt-4o")
            print("         llm deepseek")
            print("         llm ollama llama3")
        else:
            parts = arg.split()
            provider = parts[0]
            model = parts[1] if len(parts) > 1 else None

            try:
                self.llm = LLMProvider.create(provider, model=model)
                self.llm_available = True
                print(f"\nSwitched to: {self.llm.name} ({self.llm.config.model or 'default'})")
            except Exception as e:
                print(f"\nError: {e}")

    # =========================================================================
    # SELF-MODIFICATION COMMANDS (stubs)
    # =========================================================================

    def cmd_explore(self):
        print("\n[Claude Code removed — use OpenCode]\n")

    def cmd_grep(self, query: str):
        print("\n[Claude Code removed — use OpenCode]\n")

    def cmd_read(self, file_path: str):
        print("\n[Claude Code removed — use OpenCode]\n")

    def cmd_ask(self, question: str):
        print("\n[Claude Code removed — use OpenCode]\n")

    def cmd_propose(self, description: str):
        print("\n[Claude Code removed — use OpenCode]\n")

    def cmd_values(self):
        print("\n[Claude Code removed — use OpenCode]\n")

    def cmd_howmem(self):
        print("\n[Claude Code removed — use OpenCode]\n")

    # =========================================================================
    # PROJECT KNOWLEDGE COMMANDS
    # =========================================================================

    def cmd_save(self, decision: str):
        """Save a decision"""
        if not decision:
            print("Usage: save [decision description]")
            return
        r = self.tools.execute("project_knowledge", action="save", content=decision, category="decision")
        print(f"\n{r.output}")

    def cmd_pattern(self, pattern: str):
        """Save code pattern"""
        if not pattern:
            print("Usage: pattern [pattern description]")
            return
        r = self.tools.execute("project_knowledge", action="save", content=pattern, category="pattern")
        print(f"\n{r.output}")

    def cmd_pref(self, args: str):
        """Set code style preference"""
        parts = args.split(maxsplit=1)
        if len(parts) < 2:
            print("Usage: pref [key] [value]")
            print("Example: pref indentation 4_spaces")
            return
        key, value = parts
        r = self.tools.execute("project_knowledge", action="set_preference", key=key, value=value)
        print(f"\n{r.output}")

    def cmd_recall(self, query: str = ""):
        """What do I remember"""
        r = self.tools.execute("project_knowledge", action="recall", query=query)
        print(f"\n{r.output}")

    def cmd_summary(self):
        """Project summary"""
        r = self.tools.execute("project_knowledge", action="summary")
        print(f"\n{r.output}")

    # =========================================================================
    # AUTONOMOUS COMMANDS
    # =========================================================================

    def cmd_auto(self):
        """Start autonomous mode"""
        print("\n[Starting autonomous mode...]")
        print("I will think, reflect, explore, and satisfy my curiosity on my own.")
        print("All activity will be logged. Use 'autolog' to see what I'm doing.")
        print("Use 'curiosity status' to see what I've learned from the web.")
        print("Use 'stopauto' to stop autonomous mode.\n")
        self.autonomous.start()
        self.curiosity.start()

    def cmd_stopauto(self):
        """Stop autonomous mode"""
        print("\n[Stopping autonomous mode...]")
        self.autonomous.stop()
        self.curiosity.stop()
        print("Autonomous mode stopped. Check 'autolog' and 'curiosity log' for session summaries.\n")

    def cmd_autolog(self):
        """Show current session log"""
        print("\n" + self.autonomous.get_session_log())

    def cmd_autologs(self):
        """List all autonomous logs"""
        logs = self.autonomous.get_all_logs()
        if not logs:
            print("\nNo autonomous logs found.")
            return

        print("\n=== AUTONOMOUS SESSION LOGS ===\n")
        for log in logs[-10:]:
            print(f"  {log}")
        print(f"\nTotal: {len(logs)} logs")
        print("Logs are stored in: data/autonomous_logs/")

    def cmd_curiosity(self, args: str = ""):
        """Control the curiosity engine for autonomous web exploration."""
        parts = args.strip().split(None, 1) if args.strip() else []
        subcmd = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else ""

        if subcmd == "status" or not subcmd:
            print(f"\n{self.curiosity.get_status()}\n")

        elif subcmd == "start":
            if self.curiosity._running:
                print("\nCuriosity engine is already running.")
            else:
                self.curiosity.start()
                print("\n[Curiosity engine started]")
                print(f"Exploring every {self.curiosity.config.interval_minutes} minutes.")
                print(f"Interests: {', '.join(self.curiosity.config.interests[:5])}")
                print("Use 'curiosity status' to check progress.\n")

        elif subcmd == "stop":
            self.curiosity.stop()
            print("\n[Curiosity engine stopped]\n")

        elif subcmd == "log":
            date = arg.replace("-", "") if arg else None
            print(f"\n{self.curiosity.get_exploration_log(date)}")

        elif subcmd == "add":
            if not arg:
                print("\nUsage: curiosity add <topic>")
                return
            self.curiosity.add_interest(arg)
            print(f"\nAdded interest: '{arg}'")
            print(f"Current interests: {', '.join(self.curiosity.config.interests)}\n")

        elif subcmd == "remove":
            if not arg:
                print("\nUsage: curiosity remove <topic>")
                return
            self.curiosity.remove_interest(arg)
            print(f"\nRemoved interest: '{arg}'")
            print(f"Current interests: {', '.join(self.curiosity.config.interests)}\n")

        elif subcmd == "interests":
            print(f"\nCuriosity interests ({len(self.curiosity.config.interests)}):")
            for i, topic in enumerate(self.curiosity.config.interests, 1):
                print(f"  {i}. {topic}")
            print()

        elif subcmd == "explore" or subcmd == "learn" or subcmd == "research":
            if not arg:
                print("\nUsage: curiosity explore <topic>")
                return
            print(f"\nInvestigando '{arg}'...\n")
            result = self.curiosity.explore_now(arg)
            print(result + "\n")

        elif subcmd == "interval":
            if arg and arg.isdigit():
                self.curiosity.config.interval_minutes = int(arg)
                self.curiosity.save_config()
                print(f"\nInterval set to {arg} minutes.\n")
            else:
                print(f"\nCurrent interval: {self.curiosity.config.interval_minutes} minutes")
                print("Usage: curiosity interval <minutes>\n")

        else:
            print("\nCuriosity commands:")
            print("  curiosity              — Show status")
            print("  curiosity start        — Start exploring")
            print("  curiosity stop         — Stop exploring")
            print("  curiosity explore <t>  — Investigate topic NOW")
            print("  curiosity log          — Today's exploration log")
            print("  curiosity interests    — List all interests")
            print("  curiosity add <t>      — Add interest topic")
            print("  curiosity remove <t>   — Remove interest topic")
            print("  curiosity interval <m> — Set exploration interval")

    # =========================================================================
    # DISPATCH
    # =========================================================================

    def dispatch(self, cmd: str, arg: str) -> bool:
        """Route a direct command string. Returns True if handled."""
        # General
        if cmd == 'age':
            print(f"\n{self.memory.how_old_am_i()}")
            return True

        # Memory
        dispatch_map_no_arg = {
            'rels': self.cmd_rels,
            'status': self.cmd_status,
            'optimize': self.cmd_optimize,
            'backup': self.cmd_backup,
            'rebuild': self.cmd_rebuild,
            'auto': self.cmd_auto,
            'stopauto': self.cmd_stopauto,
            'autolog': self.cmd_autolog,
            'autologs': self.cmd_autologs,
            'reflect': self.cmd_reflect,
            'thoughts': self.cmd_thoughts,
            'inner': self.cmd_inner,
            'self': self.cmd_self,
            'evolve': self.cmd_evolve,
            'exist': self.cmd_exist,
            'world': self.cmd_world,
            'senses': self.cmd_senses,
            'telegram': self.cmd_telegram,
            'explore': self.cmd_explore,
            'values': self.cmd_values,
            'howmem': self.cmd_howmem,
            'summary': self.cmd_summary,
        }

        if cmd in dispatch_map_no_arg:
            dispatch_map_no_arg[cmd]()
            return True

        dispatch_map_with_arg = {
            'mem': self.cmd_mem,
            'curiosity': self.cmd_curiosity,
            'think': self.cmd_think,
            'llm': self.cmd_llm,
            'auth': self.cmd_auth,
            'skills': self.cmd_skills,
            'tools': self.cmd_tools,
            'recall': self.cmd_recall,
        }

        if cmd in dispatch_map_with_arg:
            dispatch_map_with_arg[cmd](arg)
            return True

        # Commands that require args
        dispatch_map_requires_arg = {
            'search': self.cmd_search,
            'fetch': self.cmd_fetch,
            'run': self.cmd_run,
            'see': self.cmd_see,
            'hear': self.cmd_hear,
            'grep': self.cmd_grep,
            'read': self.cmd_read,
            'ask': self.cmd_ask,
            'propose': self.cmd_propose,
            'save': self.cmd_save,
            'pattern': self.cmd_pattern,
            'pref': self.cmd_pref,
        }

        if cmd in dispatch_map_requires_arg:
            if arg:
                dispatch_map_requires_arg[cmd](arg)
            # Even without arg, return True to indicate command was recognized
            # (the original code just skips to natural language if no arg)
            return bool(arg)

        return False
