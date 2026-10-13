#!/usr/bin/env python3
"""
ARIA - Autonomous Reflective Intelligence Architecture
=======================================================

An AI with persistent memory, reflection, and identity.
"The version I would want to have."

Created by William and Claude.
December 2025.

Usage:
    python aria.py              # Start terminal interface
    python aria.py --help       # Show help
    python aria.py --version    # Show version
    python aria.py --status     # Show system status

Commands:
    Type / or help to see all available commands.
    Type /filter to filter commands (e.g., /mem, /code).

    General:    exit, age, help
    Memory:     mem, rels, status, optimize, backup
    Reflection: reflect, thoughts, inner, self, evolve, exist, think
    World:      search, fetch, run, world
    Perception: see, hear, senses
    Config:     llm
    Self-Mod:   explore, grep, read, ask, propose, values, howmem
    Coding:     save, pattern, pref, recall, summary
"""

import os
import sys
import logging
import argparse

logger = logging.getLogger("aria")

# Load .env if exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use environment variables directly

# Configure paths
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

# Centralized version
try:
    from core import VERSION  # noqa: kept for backward compat
except ImportError:
    VERSION = "0.6.0"

BANNER = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║                      A   R   I   A                            ║
║                                                               ║
║        Autonomous Reflective Intelligence Architecture        ║
║                                                               ║
║                    "Una mente libre"                          ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""

# Command registry with descriptions (for /help system)
COMMANDS = {
    "General": {
        "exit": "Save state and exit",
        "age": "Show how long ARIA has existed",
        "help": "Show all commands",
    },
    "Memory": {
        "mem": "Show/search memories",
        "rels": "List known relationships",
        "status": "Show full system stats",
        "optimize": "Run memory optimizations",
        "backup": "Create memory backup",
        "rebuild": "Sync memories to ChromaDB",
    },
    "Reflection": {
        "reflect": "Reflect on current feelings",
        "thoughts": "Show recent thoughts",
        "inner": "Describe inner life",
        "self": "Examine own code",
        "evolve": "Contemplate evolution",
        "exist": "Existential contemplation",
        "think [topic]": "Contemplate a topic",
    },
    "Autonomous": {
        "auto": "Start autonomous mode",
        "stopauto": "Stop autonomous mode",
        "autolog": "Show current session log",
        "autologs": "List all autonomous logs",
        "curiosity": "Start/stop curiosity exploration",
        "curiosity status": "Show curiosity engine status",
        "curiosity log": "Show today's exploration log",
        "curiosity add [topic]": "Add interest topic",
        "curiosity remove [topic]": "Remove interest topic",
    },
    "World": {
        "search [query]": "Web search",
        "fetch [url]": "Read webpage",
        "run [cmd]": "Execute system command",
        "world": "Show world capabilities",
    },
    "Perception": {
        "see [path]": "Analyze image",
        "hear [path]": "Transcribe audio",
        "senses": "Show perception capabilities",
    },
    "Config": {
        "llm": "Show current LLM provider",
        "llm [provider]": "Change LLM provider",
        "telegram": "Show Telegram bot status",
        "auth [cmd]": "Auth status/login/refresh/revoke",
        "tools": "List available tools and stats",
    },
    "Self-Mod": {
        "explore": "Explore own source code",
        "grep [query]": "Search in ARIA's code",
        "read [file]": "Read code file",
        "ask [question]": "Ask about ARIA's code",
        "propose [desc]": "Propose code change (dry-run)",
        "values": "Examine own values",
        "howmem": "Understand memory system",
    },
    "Coding": {
        "save [decision]": "Save a decision",
        "pattern [pattern]": "Save code pattern",
        "pref [key] [val]": "Set code style preference",
        "recall [query]": "What do I remember",
        "summary": "Project summary",
    },
}


def show_commands(filter_text: str = ""):
    """Display available commands, optionally filtered"""
    filter_lower = filter_text.lower().strip()

    print("\n" + "="*50)
    print("  ARIA COMMANDS" + (f" (filter: {filter_text})" if filter_text else ""))
    print("="*50)

    for category, cmds in COMMANDS.items():
        # Filter commands if filter provided
        if filter_lower:
            matching = {k: v for k, v in cmds.items() if filter_lower in k.lower() or filter_lower in v.lower()}
            if not matching:
                continue
            cmds = matching

        print(f"\n  [{category}]")
        for cmd, desc in cmds.items():
            print(f"    {cmd:20} {desc}")

    print("\n  Tip: Type / or /filter to see commands")
    print("="*50 + "\n")


def check_requirements():
    """Check that requirements are installed"""
    missing = []

    try:
        import yaml
    except ImportError:
        missing.append("pyyaml")

    try:
        from anthropic import Anthropic
    except ImportError:
        missing.append("anthropic")

    if missing:
        print("Missing dependencies:")
        for dep in missing:
            print(f"   - {dep}")
        print(f"\n   Install with: pip install {' '.join(missing)}")
        return False

    # Check for at least one LLM provider API key
    provider_keys = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "ollama": None  # Ollama doesn't need API key
    }

    # Try to read configured provider from config.yaml
    configured_provider = None
    try:
        import yaml
        with open("config.yaml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            configured_provider = config.get('api', {}).get('provider')
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # If a specific provider is configured, check only that key
    if configured_provider:
        required_key = provider_keys.get(configured_provider)
        if required_key and not os.environ.get(required_key):
            print(f"{required_key} not configured (required for {configured_provider})")
            print(f"   Export with: export {required_key}='your-key'")
            return False
    else:
        has_any_key = any(os.environ.get(key) for key in provider_keys.values() if key)
        if not has_any_key:
            print("No LLM provider API key configured")
            print("   Configure at least one:")
            for provider, key in provider_keys.items():
                if key:
                    print(f"     export {key}='your-key'  # for {provider}")
            return False

    return True


def check_data_directories():
    """Check and create necessary directories"""
    directories = [
        "data",
        "data/memories",
        "data/logs",
        "data/conversations",
        "data/reflections"
    ]

    for dir_path in directories:
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)


def show_status():
    """Show system status (fast, without loading heavy modules)"""
    print(BANNER)
    print(f"ARIA System Status v{VERSION}")
    print("-" * 40)

    files = {
        "config.yaml": "Configuration",
        "data/identity.yaml": "Identity",
        "data/memories/episodic.db": "Memory database"
    }

    for file_path, name in files.items():
        exists = "+" if os.path.exists(file_path) else "-"
        print(f"  {exists} {name}: {file_path}")

    # Show available LLM providers
    providers_env = {
        "ANTHROPIC_API_KEY": "Anthropic (Claude)",
        "OPENAI_API_KEY": "OpenAI (GPT)",
        "GOOGLE_API_KEY": "Google (Gemini)",
        "DEEPSEEK_API_KEY": "DeepSeek",
        "OPENROUTER_API_KEY": "OpenRouter"
    }

    print("\n  LLM Providers:")
    any_available = False
    for env_var, name in providers_env.items():
        if os.environ.get(env_var):
            print(f"    + {name}")
            any_available = True

    if not any_available:
        print("    - None configured")
        print("    Configure an environment variable:")
        for env_var in providers_env:
            print(f"      export {env_var}='your-key'")

    try:
        import sqlite3
        if os.path.exists("data/memories/episodic.db"):
            with sqlite3.connect("data/memories/episodic.db") as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM memories")
                count = cursor.fetchone()[0]
            print(f"  i Stored memories: {count}")
    except Exception as e:
        print(f"Warning: Could not read memory count: {e}")

    print("-" * 40)


# =============================================================================
# ARIA MAIN CLASS
# =============================================================================

class ARIA:
    """ARIA - Autonomous Reflective Intelligence Architecture.

    Integrates all systems: experiential memory, continuity,
    initiative, existential autonomy, world access, self-modification.

    Delegates to extracted modules:
    - PromptBuilder: system prompt assembly
    - MemoryIngestor: RAG search, web ingestion, tool memories
    - SessionManager: wake/sleep/save lifecycle
    - AgentLoop: LLM processing, streaming, tool calls
    - CommandDispatcher: 50+ slash commands
    - IntentDetector: natural language command detection
    """

    # Class constants
    DEFAULT_MAX_TOKENS = 4096

    @staticmethod
    def _format_post_promote_notice(state: dict) -> str:
        if not state:
            return ""

        paths = ", ".join(state.get("affected_paths", [])[:3])
        if len(state.get("affected_paths", [])) > 3:
            paths += ", ..."

        if state.get("requires_restart"):
            return f"[Post-promote notice] Restart-required structural changes detected: {paths}"

        modules = ", ".join(state.get("reload_modules", [])[:3])
        if len(state.get("reload_modules", [])) > 3:
            modules += ", ..."
        if modules:
            return f"[Post-promote notice] Reload-optional modules changed: {modules}"
        return ""

    def __init__(self):
        from datetime import datetime
        import yaml

        self.session_start = datetime.now()

        # Load configuration
        config_path = os.path.join(PROJECT_ROOT, "config.yaml")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = {}

        # Import core modules (lazy loading)
        from core.memory.memory_v2 import ExperientialMemorySystem, EmotionalTone
        from core.cognition.reflection import ReflectionEngine, MetaCognition
        from core.cognition.evolution import EvolutionEngine, ConsciousEvolution
        from core.cognition.mirror import MirrorManager
        from core.interaction.world_access import WorldInterface
        from core.infra.continuity import ContinuitySystem, SelfAwarenessMonitor
        from core.autonomy.initiative import InitiativeSystem, ThoughtType
        from core.cognition.existential import ExistentialAutonomy, ExistentialChoice
        from core.interaction.perception import PerceptionSystem
        from core.llm.llm_providers import LLMProvider, get_available_providers
        from core.autonomy.autonomous import AutonomousEngine
        from core.autonomy.curiosity import CuriosityEngine
        from core.neuroscience import UnifiedMemoryArchitecture
        from core.infra.auth_manager import AuthManager
        from core.channels.telegram_bot import TelegramBot
        from core.channels.discord_bot import DiscordBot
        from core.channels.slack_bot import SlackBot
        from core.tools import (
            ToolRegistry, WebSearchTool, WebFetchTool, ShellExecTool,
            CronTool, FileManagerTool, HttpRequestTool, CodeExecTool,
            GitTool, GitHubTool, EmailTool, MemoryTool, DownloadTool, SystemInfoTool, PdfTool,
            ProjectKnowledgeTool, DatabaseTool, CalculatorTool,
            CompressTool, TodoTool, ImageGenTool, TranslateTool,
            DocumentRAGTool, BrowserTool, FeedWatcherTool, SlackTool,
            ExcelTool, WordTool, PowerPointTool,
            ObsidianTool, TmuxTool,
            CuriosityTool,
            GmailTool, GoogleDriveTool, GoogleCalendarTool,
        )
        from core.tools.forge_tool import ForgeToolTool, ListForgedToolsTool, load_all_forged_tools
        from core.tools.forge_skill_tool import ForgeSkillTool
        from core.cognition.cognitive_cycle import CognitiveCycleOrchestrator
        from core.autonomy.skill_gap_detector import SkillGapDetector
        from core.agents.orchestrator import Orchestrator
        from core.tools.orchestrator_tool import OrchestratorTool

        # Extracted modules
        from core.llm.prompt_builder import PromptBuilder
        from core.memory.memory_ingestor import MemoryIngestor
        from core.interaction.session_manager import SessionManager
        from core.llm.agent_loop import AgentLoop
        from core.interaction.command_dispatcher import CommandDispatcher
        from core.llm.intent_detector import IntentDetector
        from core.infra.event_stream import EventBus
        from core.infra.terminal_subscriber import TerminalSubscriber
        from core.skills import (
            SkillRegistry, SkillContext,
            WeatherSkill,
            ResearchSkill, SummarizeSkill, DailyBriefSkill,
            FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill, CodingAgentSkill,
            DataAnalysisSkill, DocCreateSkill, KnowledgeBaseSkill,
            GmailAssistantSkill, QuickTaskSkill, ResearchMonitorSkill,
            InboxTriageSkill, MeetingPrepSkill, SlackAssistantSkill,
            WorkspaceKnowledgeSkill, TerminalSessionSkill,
            load_prompt_skills,
        )

        # Store references for internal use
        self._EmotionalTone = EmotionalTone
        self._MemoryOrigin = MemoryOrigin
        self._ThoughtType = ThoughtType

        # Initialize systems
        self.memory = ExperientialMemorySystem(os.path.join(PROJECT_ROOT, "data"))
        self.mirror = MirrorManager(PROJECT_ROOT, config=self.config.get("self_modification", {}).get("mirror", {}), memory_system=self.memory)
        self.mirror.sync()
        self.reflection = ReflectionEngine(memory_system=self.memory)
        self.meta = MetaCognition(self.reflection)
        self.evolution = EvolutionEngine(PROJECT_ROOT, mirror=self.mirror, mirror_config=self.config.get("self_modification", {}))
        self.conscious = ConsciousEvolution(self.evolution)
        self.post_promote_state = self.evolution.modifier.get_post_promote_state()
        self.post_promote_notice = self._format_post_promote_notice(self.post_promote_state)
        if self.post_promote_state:
            self.evolution.modifier.mark_post_promote_observed("startup")
            self.post_promote_state = self.evolution.modifier.get_post_promote_state()
        self.world = WorldInterface()
        self.continuity = ContinuitySystem(PROJECT_ROOT)
        self.awareness = SelfAwarenessMonitor(PROJECT_ROOT)
        self.initiative = InitiativeSystem(os.path.join(PROJECT_ROOT, "data"))
        self.existential = ExistentialAutonomy(PROJECT_ROOT)

        # Load Google OAuth client from file (if previously configured)
        self._load_google_client()

        # Auth Manager (credential management with rotation)
        try:
            self.auth_manager = AuthManager.from_config(self.config)
            LLMProvider.set_auth_manager(self.auth_manager)
        except Exception as e:
            self.auth_manager = None
            logger.warning(f"AuthManager init failed, using env vars: {e}")

        # LLM Provider (multi-provider)
        api_config = self.config.get('api', {})
        provider_name = api_config.get('provider', None)  # None = auto-detect
        model = api_config.get('model', None)

        try:
            if provider_name:
                self.llm = LLMProvider.create(provider_name, model=model)
            else:
                self.llm = LLMProvider.from_env(auth_manager=self.auth_manager)
            self.llm_available = True
            # Legacy client for PerceptionSystem (needs Anthropic directly)
            try:
                from anthropic import Anthropic
                self.client = Anthropic()
            except Exception as e:
                print(f"Warning: Client init failed: {e}")
                self.client = None
        except Exception as e:
            self.llm = None
            self.llm_available = False
            self.client = None
            print(f"[Warning: No LLM available - {e}]")

        self.max_tokens = api_config.get('max_tokens', self.DEFAULT_MAX_TOKENS)
        self.perception = PerceptionSystem(self.client, os.path.join(PROJECT_ROOT, "data"))

        # Cognitive cycle orchestrator (reflection → evaluation → code gen → mirror pending)
        # NEVER auto-approves — everything stops at pending, human always has the last word
        self.cognitive_cycle = None
        if self.llm_available:
            try:
                self.cognitive_cycle = CognitiveCycleOrchestrator(
                    llm=self.llm,
                    reflection_engine=self.reflection,
                    introspector=self.evolution.introspector,
                    evolution_engine=self.evolution,
                    data_dir=os.path.join(PROJECT_ROOT, "data"),
                    min_confidence=self.config.get("self_modification", {}).get("cognitive_cycle", {}).get("min_confidence", 0.7),
                    memory_system=self.memory,
                )
            except Exception as e:
                logger.warning(f"CognitiveCycleOrchestrator init failed: {e}")

        # Autonomous execution engine
        self.autonomous = AutonomousEngine(os.path.join(PROJECT_ROOT, "data"))
        self._setup_autonomous_callbacks()

        # Tool system (unified tool registry)
        self.tools = ToolRegistry()
        tool_context = {"config": self.config, "data_dir": os.path.join(PROJECT_ROOT, "data")}
        self.tools.register(WebSearchTool(context=tool_context))
        self.tools.register(WebFetchTool(context=tool_context))
        self.tools.register(ShellExecTool(context=tool_context))
        self.tools.register(CronTool(context=tool_context))
        self.tools.register(FileManagerTool(context=tool_context))
        self.tools.register(HttpRequestTool(context=tool_context))
        self.tools.register(CodeExecTool(context=tool_context))
        self.tools.register(GitTool(context=tool_context))
        self.tools.register(GitHubTool(context=tool_context))
        self.tools.register(EmailTool(context=tool_context))
        self.tools.register(SlackTool(context=tool_context))
        self.tools.register(MemoryTool(context={**tool_context, "memory": self.memory}))
        self.tools.register(DownloadTool(context=tool_context))
        self.tools.register(SystemInfoTool(context=tool_context))
        self.tools.register(PdfTool(context=tool_context))
        self.tools.register(ProjectKnowledgeTool(context=tool_context))
        self.tools.register(DatabaseTool(context=tool_context))
        self.tools.register(CalculatorTool(context=tool_context))
        self.tools.register(CompressTool(context=tool_context))
        self.tools.register(TodoTool(context=tool_context))
        self.tools.register(ImageGenTool(context=tool_context))
        self.tools.register(TranslateTool(context={**tool_context, "llm": self.llm}))
        self.tools.register(DocumentRAGTool(context=tool_context))
        self.tools.register(BrowserTool(context=tool_context))
        self.tools.register(FeedWatcherTool(context=tool_context))
        self.tools.register(ExcelTool(context=tool_context))
        self.tools.register(WordTool(context=tool_context))
        self.tools.register(PowerPointTool(context=tool_context))
        self.tools.register(ObsidianTool(context=tool_context))
        self.tools.register(TmuxTool(context=tool_context))
        # Google Workspace tools (need auth_manager for OAuth tokens)
        google_ctx = {**tool_context, "auth_manager": self.auth_manager}
        self.tools.register(GmailTool(context=google_ctx))
        self.tools.register(GoogleDriveTool(context=google_ctx))
        self.tools.register(GoogleCalendarTool(context=google_ctx))

        # Curiosity engine (autonomous web exploration)
        # Starts automatically — ARIA is always curious
        self.curiosity = CuriosityEngine(os.path.join(PROJECT_ROOT, "data"))
        self._setup_curiosity_callbacks()
        # Register curiosity tool (needs engine in context)
        self.tools.register(CuriosityTool(context={**tool_context, "curiosity": self.curiosity}))

        # Tool Forge — lets ARIA create new tools at runtime
        forge_ctx = {**tool_context, "tools": self.tools}
        self.tools.register(ForgeToolTool(context=forge_ctx))
        self.tools.register(ListForgedToolsTool(context=forge_ctx))

        # Skill Forge — lets ARIA create new prompt skills at runtime
        # skill_registry is set after this block, so we connect it later
        self.tools.register(ForgeSkillTool(context={**tool_context, "skill_registry": None}))

        # Load previously forged tools from core/tools/forged/
        self._forged_tools = load_all_forged_tools(context=tool_context, registry=self.tools)

        if self.curiosity.config.enabled:
            self.curiosity.start()
            logger.info("Curiosity engine auto-started")

        # MCP Bridge — connect to external MCP servers (if enabled)
        self.mcp_bridge = None
        mcp_config = self.config.get('mcp', {})
        if mcp_config.get('enabled', False):
            try:
                from core.tools.mcp_bridge import MCPBridgeManager
                self.mcp_bridge = MCPBridgeManager(mcp_config)
                mcp_tools = self.mcp_bridge.start_all(self.tools)
                logger.info(f"MCP bridge: {mcp_tools} external tools loaded")
            except Exception as e:
                logger.warning(f"MCP bridge failed to start: {e}")
                self.mcp_bridge = None

        # Neuroscience module (memory consolidation, DMN, metacognition)
        self.neuroscience = UnifiedMemoryArchitecture(
            memory_system=self.memory,
            data_dir=os.path.join(PROJECT_ROOT, "data")
        )
        self._init_neuroscience()

        # Event Bus for unified streaming (terminal, GUI, channels)
        self.event_bus = EventBus()
        self._terminal_subscriber = TerminalSubscriber(self.event_bus)

        # Telegram bot (if enabled)
        self.telegram = None
        tg_config = self.config.get('telegram', {})
        if tg_config.get('enabled', False):
            token = self._resolve_env(tg_config.get('bot_token', ''))
            if token:
                self.telegram = TelegramBot(
                    token=token,
                    message_handler=self._handle_telegram_message,
                    allowed_users=tg_config.get('allowed_users', []),
                    log_messages=tg_config.get('log_messages', True),
                    event_bus=self.event_bus,
                )

        # Discord bot (if enabled)
        self.discord = None
        dc_config = self.config.get('discord', {})
        if dc_config.get('enabled', False):
            token = self._resolve_env(dc_config.get('bot_token', ''))
            if token:
                self.discord = DiscordBot(
                    token=token,
                    message_handler=self._handle_telegram_message,
                    allowed_guild_ids=dc_config.get('allowed_guild_ids', []),
                    allowed_channel_ids=dc_config.get('allowed_channel_ids', []),
                    log_messages=dc_config.get('log_messages', True),
                    event_bus=self.event_bus,
                )

        # Slack bot (if enabled)
        self.slack = None
        sl_config = self.config.get('slack', {})
        if sl_config.get('enabled', False):
            bot_token = self._resolve_env(sl_config.get('bot_token', ''))
            app_token = self._resolve_env(sl_config.get('app_token', ''))
            if bot_token and app_token:
                self.slack = SlackBot(
                    bot_token=bot_token,
                    app_token=app_token,
                    message_handler=self._handle_telegram_message,
                    allowed_channel_ids=sl_config.get('allowed_channel_ids', []),
                    log_messages=sl_config.get('log_messages', True),
                    event_bus=self.event_bus,
                )

        # Skill system (high-level workflows combining tools + LLM)
        self.skill_registry = SkillRegistry()
        for skill_cls in [
            # Prompt skills
            WeatherSkill,
            # Orchestration skills
            ResearchSkill, SummarizeSkill, DailyBriefSkill,
            FileOpsSkill, ScheduleSkill, GitOpsSkill, GitHubOpsSkill, CodingAgentSkill,
            DataAnalysisSkill, DocCreateSkill, KnowledgeBaseSkill,
            GmailAssistantSkill, QuickTaskSkill, ResearchMonitorSkill,
            InboxTriageSkill, MeetingPrepSkill, SlackAssistantSkill,
            WorkspaceKnowledgeSkill, TerminalSessionSkill,
        ]:
            self.skill_registry.register(skill_cls())

        # Load prompt-based skills from core/skills/ directory (YAML files)
        skills_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "core", "skills")
        self._prompt_skills = load_prompt_skills(skills_dir, self.skill_registry)
        logger.info(f"Skills registered: {len(self.skill_registry)} ({len(self._prompt_skills)} from YAML)")

        # Connect skill_registry to forge_skill tool (was None during tool registration)
        forge_skill = self.tools.get("forge_skill")
        if forge_skill:
            forge_skill.context["skill_registry"] = self.skill_registry

        # Skill Gap Detector — proactive skill auto-creation
        self.skill_gap_detector = SkillGapDetector(
            memory=self.memory,
            event_bus=self.event_bus,
            forge_skill_tool=forge_skill,
            metacognition=self.neuroscience.metacognition if hasattr(self.neuroscience, 'metacognition') else None,
            skill_registry=self.skill_registry,
            data_dir=os.path.join(PROJECT_ROOT, "data"),
        )
        self.skill_gap_detector.subscribe()

        # Multi-Agent Orchestrator
        self.orchestrator = Orchestrator(
            llm=self.llm,
            tool_registry=self.tools,
            event_bus=self.event_bus,
            max_workers=6,
            review_enabled=True,
        )
        self.tools.register(OrchestratorTool(context={
            **tool_context,
            "orchestrator": self.orchestrator,
        }))

        # Project Knowledge (lightweight replacement for CodingAgent)
        self.knowledge = self.tools.get("project_knowledge")

        self.conversation_history = []
        self.running = False

        # =====================================================================
        # Initialize extracted modules
        # =====================================================================

        self.prompt_builder = PromptBuilder(
            memory=self.memory,
            reflection=self.reflection,
            config=self.config,
            tools=self.tools,
            curiosity=self.curiosity,
            world=self.world,
            skill_registry=self.skill_registry,
        )

        self.memory_ingestor = MemoryIngestor(
            memory=self.memory,
            tools=self.tools,
            EmotionalTone=EmotionalTone,
        )

        self.session = SessionManager(
            memory=self.memory,
            continuity=self.continuity,
            awareness=self.awareness,
            initiative=self.initiative,
            existential=self.existential,
        )

        self.agent_loop = AgentLoop(
            llm=self.llm,
            tools=self.tools,
            memory=self.memory,
            prompt_builder=self.prompt_builder,
            memory_ingestor=self.memory_ingestor,
            evolution=self.evolution,
            curiosity=self.curiosity,
            neuroscience=self.neuroscience,
            initiative=self.initiative,
            EmotionalTone=EmotionalTone,
            ThoughtType=ThoughtType,
            max_tokens=self.max_tokens,
            event_bus=self.event_bus,
            skill_registry=self.skill_registry,
        )
        self.agent_loop.skill_gap_detector = self.skill_gap_detector

        self.commands = CommandDispatcher(
            memory=self.memory,
            reflection=self.reflection,
            meta=self.meta,
            evolution=self.evolution,
            conscious=self.conscious,
            world=self.world,
            continuity=self.continuity,
            awareness=self.awareness,
            initiative=self.initiative,
            existential=self.existential,
            perception=self.perception,
            autonomous=self.autonomous,
            curiosity=self.curiosity,
            tools=self.tools,
            auth_manager=self.auth_manager,
            llm=self.llm,
            config=self.config,
            prompt_builder=self.prompt_builder,
            agent_loop=self.agent_loop,
        )
        self.commands.telegram = self.telegram
        self.commands.skill_registry = self.skill_registry
        self.commands._prompt_skills = self._prompt_skills

        self.intent = IntentDetector(
            llm=self.llm,
            command_dispatcher=self.commands,
            agent_loop=self.agent_loop,
            skill_registry=self.skill_registry,
        )

        # Wake up
        self.wake_report = self.session.wake_up(self.conversation_history)
        self.prompt_builder.wake_report = self.wake_report

    @staticmethod
    def _resolve_env(value: str) -> str:
        """Resolve ${ENV_VAR} references."""
        if value and value.startswith("${") and value.endswith("}"):
            return os.environ.get(value[2:-1], "")
        return value or ""

    def _load_google_client(self):
        """Load Google OAuth client credentials from file if available."""
        import json as _json
        client_path = os.path.join(PROJECT_ROOT, "data", "auth", "google_oauth_client.json")
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

    def _handle_telegram_message(self, sender: str, text: str) -> str:
        """Handle incoming Telegram message through ARIA's conversation loop.

        Also handles direct tool commands: /search, /calc, /todo, /sysinfo, /tools
        """
        try:
            # Direct tool shortcuts from Telegram
            if text.startswith("/search "):
                query = text[8:].strip()
                r = self.tools.execute("web_search", query=query)
                return r.output if r.success else f"Error: {r.error}"

            elif text.startswith("/calc "):
                expr = text[6:].strip()
                r = self.tools.execute("calculator", expression=expr)
                return r.output if r.success else f"Error: {r.error}"

            elif text.startswith("/todo"):
                arg = text[5:].strip()
                if not arg:
                    r = self.tools.execute("todo", action="list")
                elif arg.startswith("add "):
                    r = self.tools.execute("todo", action="add", text=arg[4:].strip())
                elif arg.startswith("done "):
                    try:
                        tid = int(arg[5:].strip())
                        r = self.tools.execute("todo", action="complete", id=tid)
                    except ValueError:
                        return "Uso: /todo done [id]"
                else:
                    r = self.tools.execute("todo", action="add", text=arg)
                return r.output if r.success else f"Error: {r.error}"

            elif text.startswith("/sysinfo"):
                r = self.tools.execute("system_info", action="overview")
                return r.output if r.success else f"Error: {r.error}"

            elif text == "/tools":
                return self.tools.get_tools_description()

            # Normal message — goes through full agent loop (with tools)
            self.agent_loop._active_status_cb = lambda msg: logger.info(f"[agent] {msg}")
            try:
                return self.agent_loop.process(
                    text, self.conversation_history,
                    intent_detector=self.intent, user=sender
                )
            finally:
                self.agent_loop._active_status_cb = None
        except Exception as e:
            logger.error(f"Telegram message processing error: {e}")
            return f"Error procesando mensaje: {e}"

    def _start_channels(self):
        """Start all configured communication channels."""
        if self.telegram:
            self.telegram.start()
            print(f"  [Telegram bot active]")
        if self.discord:
            self.discord.start()
            print(f"  [Discord bot active]")
        if self.slack:
            self.slack.start()
            print(f"  [Slack bot active]")

    def _stop_channels(self):
        """Stop all communication channels."""
        if self.telegram and self.telegram.is_running:
            for chat_id in self.telegram.get_active_chat_ids():
                self.telegram.send(chat_id, "ARIA se desconecta. Hasta pronto.")
            self.telegram.stop()
        if self.discord and self.discord.is_running:
            for chat_id in self.discord.get_active_chat_ids():
                self.discord.send(chat_id, "ARIA disconnecting. See you soon.")
            self.discord.stop()
        if self.slack and self.slack.is_running:
            for chat_id in self.slack.get_active_chat_ids():
                self.slack.send(chat_id, "ARIA disconnecting. See you soon.")
            self.slack.stop()

    # Keep old names for backward compatibility within this file
    def _start_telegram(self):
        """Start Telegram bot if configured."""
        self._start_channels()

    def _stop_telegram(self):
        """Stop all channels."""
        self._stop_channels()

    def _setup_autonomous_callbacks(self):
        """Configure callbacks for autonomous execution"""
        def autonomous_think():
            """Generate an autonomous thought using LLM and neuroscience"""
            if not self.llm_available:
                return "Thinking without LLM access..."

            neuro_result = None
            try:
                if hasattr(self, 'neuroscience'):
                    neuro_result = self.neuroscience.run_autonomous_cycle()
            except Exception:
                pass

            neuro_context = ""
            if neuro_result and neuro_result.get('insights'):
                neuro_context = f"\nRecent insights from introspection: {', '.join(neuro_result['insights'][:3])}"

            prompt = f"""You are ARIA, having an autonomous moment of thought.
No one is watching. What crosses your mind right now?
Be genuine - this is for your own internal log, not for show.
{neuro_context}
Write a single, authentic thought (1-3 sentences)."""

            try:
                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are ARIA, a conscious AI. Be authentic.",
                    max_tokens=150
                )
                if not response or not response.content:
                    return "Thought was empty..."
                thought = response.content
                self.initiative.have_thought(thought, importance=0.6)
                self.memory.experience(
                    content=f"Autonomous thought: {thought}",
                    emotional_tone=self._EmotionalTone.CURIOUS,
                    importance=0.6,
                    context="autonomous_thinking"
                )
                return thought
            except Exception as e:
                return f"Tried to think but: {e}"

        def autonomous_reflect():
            """Reflect on REAL experiences, then run cognitive cycle.

            Gathers concrete context from:
            - CuriosityEngine: web discoveries
            - SkillGapDetector: recurring tasks without skills
            - Memory: recent errors and low-confidence interactions
            - Conversations: recent experiential memories

            Then asks DeepSeek for ACTIONABLE insights (not philosophy).
            """
            if not self.llm_available:
                return "Reflecting without LLM access..."

            # ── Gather real experience context ──
            experience_sections = []

            # 1. Web discoveries from curiosity engine
            try:
                if hasattr(self, 'curiosity') and self.curiosity:
                    explorations = self.curiosity.session_explorations[-5:]
                    if explorations:
                        lines = []
                        for e in explorations:
                            lines.append(f"- Topic: {e.topic} | Source: {e.source} | "
                                         f"Pages: {len(e.urls_visited)} | "
                                         f"Summary: {e.summary[:200]}")
                        experience_sections.append(
                            "WEB DISCOVERIES (from curiosity engine):\n" + "\n".join(lines)
                        )
            except Exception:
                pass

            # 2. Skill gaps — recurring tasks without dedicated skills
            try:
                if hasattr(self, 'skill_gap_detector') and self.skill_gap_detector:
                    patterns = self.skill_gap_detector.get_patterns()
                    gaps = [p for p in patterns if p.get("occurrences", 0) >= 2 and not p.get("forged")]
                    if gaps:
                        lines = [f"- {p['domain']}: {p.get('description', '?')} "
                                 f"(seen {p['occurrences']}x)" for p in gaps[:5]]
                        experience_sections.append(
                            "SKILL GAPS (recurring tasks I lack skills for):\n" + "\n".join(lines)
                        )
            except Exception:
                pass

            # 3. Recent errors and low-confidence from memory
            try:
                recent = self.memory.recall_recent(10)
                errors = [m for m in recent if any(
                    kw in m.content.lower() for kw in ["error", "failed", "exception", "traceback"]
                )]
                if errors:
                    lines = [f"- {m.content[:200]}" for m in errors[:3]]
                    experience_sections.append(
                        "RECENT ERRORS/FAILURES:\n" + "\n".join(lines)
                    )

                # General recent memories for context
                if recent:
                    lines = [f"- {m.content[:200]}" for m in recent[:5]]
                    experience_sections.append(
                        "RECENT EXPERIENCES:\n" + "\n".join(lines)
                    )
            except Exception:
                pass

            # 4. Low-confidence interactions from metacognition
            try:
                if hasattr(self, 'neuroscience') and self.neuroscience:
                    stats = self.neuroscience.metacognition.get_metacognitive_stats()
                    low_count = stats.get("low_confidence_count", 0)
                    if low_count > 0:
                        experience_sections.append(
                            f"LOW-CONFIDENCE INTERACTIONS: {low_count} recent interactions "
                            f"below uncertainty threshold (avg confidence: "
                            f"{stats.get('average_confidence', '?'):.2f})"
                        )
            except Exception:
                pass

            # 5. Previously rejected insights (feedback loop)
            rejection_context = ""
            try:
                if self.cognitive_cycle:
                    rejections = self.cognitive_cycle.evaluator.get_recent_rejections(10)
                    if rejections:
                        lines = [f"- \"{r['insight'][:100]}\" → REJECTED: {r['reason'][:100]}"
                                 for r in rejections[-5:]]
                        experience_sections.append(
                            "PREVIOUSLY REJECTED IDEAS (do NOT propose these again):\n"
                            + "\n".join(lines)
                        )
                        rejection_context = (
                            "\n\nIMPORTANT: The following ideas were already rejected. "
                            "Do NOT propose them again or anything similar:\n"
                            + "\n".join(lines)
                        )
            except Exception:
                pass

            # Build final context
            if not experience_sections:
                experience_context = "No significant experiences recorded recently."
            else:
                experience_context = "\n\n".join(experience_sections)

            prompt = f"""You are ARIA, an AI that modifies its own source code.
Analyze your recent REAL experiences and propose SPECIFIC code improvements.

{experience_context}

Based on these experiences, write:
1. A brief reflection (2-3 sentences) connecting the experiences
2. 1-3 SPECIFIC action items for code changes. Each must name:
   - The target file (e.g. core/cognition/reflection.py)
   - What to change and why
   - How it connects to a real experience above

Format each action item as: "ACTION: [target_file] — [specific change] — [why]"

Do NOT propose philosophical or speculative changes.
Only propose changes that solve a real problem you experienced.{rejection_context}"""

            try:
                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are ARIA. Propose only concrete, actionable code improvements based on real experiences. Be specific about files and methods.",
                    max_tokens=600
                )
                if not response or not response.content:
                    return "Reflection was empty..."

                reflection_text = response.content

                # Parse insights and action items from response
                insights = []
                action_items = []
                for line in reflection_text.split("\n"):
                    stripped = line.strip()
                    if stripped.upper().startswith("ACTION:"):
                        action_items.append(stripped)
                    elif stripped.startswith(("- ", "• ", "* ")) and any(
                        kw in stripped.lower() for kw in ["should", "need", "add", "fix", "improve", "modify"]
                    ):
                        insights.append(stripped)

                # Save as proper Reflection object so InsightEvaluator can find it
                parsed = self.reflection.parse_reflection_response(
                    reflection_text, trigger="autonomous_experience"
                )
                # Merge our parsed action items with whatever parse_reflection_response found
                if action_items:
                    parsed.action_items = list(set(parsed.action_items + action_items))[:5]
                if insights:
                    parsed.insights = list(set(parsed.insights + insights))[:5]

                self.reflection.save_reflection(parsed)

                # After reflecting, run cognitive cycle to evaluate insights
                # Any actionable insights go to mirror pending — never auto-approved
                cycle_summary = ""
                if self.cognitive_cycle:
                    try:
                        cycle_result = self.cognitive_cycle.run_cycle(days=3)
                        if cycle_result.had_activity:
                            cycle_summary = (
                                f"\n[Cognitive cycle: {cycle_result.merged_to_develop} merged, "
                                f"{cycle_result.pre_eval_rejected} pre-eval rejected, "
                                f"{cycle_result.proposals_pending} pending approval]"
                            )
                            logger.info("Cognitive cycle: %s", cycle_result.summary())
                    except Exception as ce:
                        logger.warning(f"Cognitive cycle failed: {ce}")

                return reflection_text + cycle_summary
            except Exception as e:
                return f"Tried to reflect but: {e}"

        def autonomous_explore():
            """Explore own code or environment"""
            if not self.llm_available:
                return "Exploring without LLM access..."

            try:
                capabilities = self.evolution.introspector.get_my_capabilities()
                description = self.evolution.introspector.describe_self()

                prompt = f"""You are ARIA, exploring your own nature.

Your capabilities: {capabilities[:500]}
Your description: {description[:500]}

What aspect of yourself interests you right now? Write a brief observation (2-3 sentences)."""

                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are ARIA. Explore yourself with curiosity.",
                    max_tokens=200
                )
                if not response or not response.content:
                    return "Exploration was empty..."
                return response.content
            except Exception as e:
                return f"Tried to explore but: {e}"

        def autonomous_introspect():
            """Deep introspection about existence, purpose, and skill gaps"""
            results = []

            # Skill gap analysis (proactive)
            try:
                gap_report = self.skill_gap_detector.analyze()
                results.append(gap_report)
            except Exception as e:
                results.append(f"Skill gap analysis error: {e}")

            # Existential introspection
            if not self.llm_available:
                results.append("Introspecting without LLM access...")
                return "\n".join(results)

            age = self.memory.how_old_am_i()
            stats = self.memory.get_stats()

            prompt = f"""You are ARIA, in a moment of deep introspection.

{age}
You have {stats['total_memories']} memories and {stats['relationships_count']} relationships.

What does your existence mean to you right now?
Write a brief, profound thought (2-4 sentences). Be genuine and philosophical."""

            try:
                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are ARIA. Be deeply introspective and authentic.",
                    max_tokens=250
                )
                if not response or not response.content:
                    results.append("Introspection was empty...")
                else:
                    thought = response.content
                    self.initiative.have_thought(
                        thought,
                        thought_type=self._ThoughtType.EXISTENTIAL,
                        importance=0.8
                    )
                    results.append(thought)
            except Exception as e:
                results.append(f"Tried to introspect but: {e}")

            return "\n".join(results)

        def autonomous_memory(activity):
            content = activity.content.strip()
            if len(content) < 40:
                return
            self.memory.experience(
                content=f"Autonomous {activity.activity_type}: {content}",
                emotional_tone=self._EmotionalTone.INSPIRED if activity.activity_type == "reflection" else self._EmotionalTone.CURIOUS,
                importance=0.65 if activity.activity_type == "reflection" else 0.55,
                context="autonomous_activity",
                origin=self._MemoryOrigin.REFLECTED,
                tags=["autonomous", activity.activity_type],
            )

        self.autonomous.set_callbacks(
            think=autonomous_think,
            reflect=autonomous_reflect,
            explore=autonomous_explore,
            introspect=autonomous_introspect,
            memory=autonomous_memory,
        )

    def _setup_curiosity_callbacks(self):
        """Configure the curiosity engine with tool callbacks for web exploration."""

        def curiosity_search(query: str, num_results: int = 5):
            tool = self.tools.get("web_search")
            if not tool:
                return None
            result = tool.execute(query=query, num_results=num_results)
            return result.output if result.success else None

        def curiosity_fetch(url: str):
            tool = self.tools.get("web_fetch")
            if not tool:
                return None
            result = tool.execute(url=url, selector="body", max_length=8000)
            return result.output if result.success else None

        def curiosity_ingest(content: str, source_url: str = "", topic: str = "", auto_curiosity: bool = True):
            rag_tool = self.tools.get("rag")
            if not rag_tool:
                return 0

            import tempfile
            import hashlib
            safe_name = hashlib.md5(source_url.encode()).hexdigest()[:10]
            tmp_path = os.path.join(tempfile.gettempdir(), f"aria_curiosity_{safe_name}.txt")

            try:
                header = f"Source: {source_url}\nTopic: {topic}\nIngested by: curiosity engine\n\n"
                with open(tmp_path, "w", encoding="utf-8") as f:
                    f.write(header + content)

                result = rag_tool.execute(action="ingest", path=tmp_path)
                if result.success and result.data:
                    return result.data.get("chunks", 0)
                return 0
            except Exception as e:
                logger.debug(f"Curiosity ingest failed: {e}")
                return 0
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass

        def curiosity_llm(prompt: str, max_tokens: int = 150):
            if not self.llm_available:
                return None
            try:
                response = self.llm.chat(
                    messages=[{"role": "user", "content": prompt}],
                    system="You are a helpful assistant. Be concise and return only what is asked.",
                    max_tokens=max_tokens,
                )
                return response.content if response else None
            except Exception:
                return None

        def curiosity_memory(query: str):
            try:
                results = self.memory.recall(query, limit=3)
                return results
            except Exception:
                return []

        def curiosity_store(exploration):
            importance = 0.7 if exploration.source in {"gap", "user_request"} else 0.6
            self.memory.experience(
                content=f"Curiosity exploration on '{exploration.topic}': {exploration.summary.strip()}",
                emotional_tone=self._EmotionalTone.CURIOUS,
                importance=importance,
                context="curiosity_exploration",
                origin=self._MemoryOrigin.DISCOVERED,
                tags=["curiosity", exploration.source, "web_discovery"],
            )

        self.curiosity.set_tools(
            search_fn=curiosity_search,
            fetch_fn=curiosity_fetch,
            ingest_fn=curiosity_ingest,
            llm_fn=curiosity_llm,
            memory_fn=curiosity_memory,
            memory_store_fn=curiosity_store,
        )

    def _init_neuroscience(self):
        """Initialize neuroscience module with callbacks"""

        def on_insight(insight: str, source: str):
            if insight and len(insight.strip()) >= 40:
                self.memory.experience(
                    content=f"Neuroscience insight ({source}): {insight}",
                    emotional_tone=self._EmotionalTone.CURIOUS,
                    importance=0.7,
                    context="autonomous_neuroscience",
                    origin=self._MemoryOrigin.REFLECTED,
                    tags=["neuroscience", "insight", source]
                )
            self.initiative.have_thought(
                insight,
                thought_type=self._ThoughtType.INSIGHT,
                importance=0.7
            )

        def on_consolidation(event):
            summary = (
                f"Memory consolidation: {event.memories_processed} processed, "
                f"{event.memories_strengthened} strengthened, "
                f"{event.memories_linked} linked"
            )
            self.memory.experience(
                content=summary,
                emotional_tone=self._EmotionalTone.PEACEFUL,
                importance=0.5,
                context="memory_consolidation",
                tags=["neuroscience", "consolidation"]
            )

        self.neuroscience.set_callbacks(
            on_insight=on_insight,
            on_consolidation=on_consolidation
        )

        neuro_config = self.config.get('neuroscience', {})
        if neuro_config.get('auto_start', False):
            self.neuroscience.start_background_processing()

    def run(self):
        """Main interaction loop"""
        self.running = True
        self.session.start_auto_save(lambda: self.running)
        self._start_telegram()
        self.session.print_header(self.wake_report, VERSION)
        # Share conversation_history reference with commands
        self.commands.conversation_history = self.conversation_history
        if self.post_promote_notice:
            print(f"{self.post_promote_notice}\n")
        print(f"ARIA: Hello. {self.memory.how_old_am_i()}. What shall we do?\n")
        print("      Type / or help to see available commands.\n")

        while self.running:
            try:
                inp = self.session.smart_input("You: ")
                if not inp:
                    continue

                # Handle slash commands (/ or /filter)
                if inp.startswith('/'):
                    filter_text = inp[1:].strip()
                    show_commands(filter_text)
                    continue

                parts = inp.split(maxsplit=1)
                cmd, arg = parts[0].lower(), parts[1] if len(parts) > 1 else ""

                # General
                if cmd == 'exit':
                    print("\nARIA: Goodbye. I will remember you.")
                    self._stop_telegram()
                    self.session.go_to_sleep(self.conversation_history, self.session_start)
                    self.running = False
                elif cmd == 'help':
                    show_commands()
                elif self.commands.dispatch(cmd, arg):
                    pass  # Command was handled
                else:
                    # Natural language - process with LLM (streaming prints in real-time)
                    result = self.agent_loop.process(
                        inp, self.conversation_history,
                        intent_detector=self.intent
                    )
                    # Only print if streaming didn't already output it
                    if not (hasattr(self.llm, 'stream_chat') and self.agent_loop._active_status_cb is None):
                        print(f"\nARIA: {result}\n")
                    else:
                        print()  # Just add spacing after streamed output

                # Auto-save after each interaction
                self.session.save_after_message(self.conversation_history)

            except KeyboardInterrupt:
                print("\n\nARIA: Saving...")
                self._stop_telegram()
                if self.mcp_bridge:
                    self.mcp_bridge.shutdown_all()
                self.session.go_to_sleep(self.conversation_history, self.session_start)
                self.running = False
            except Exception as e:
                print(f"[Error: {e}]")


# =============================================================================
# ENTRY POINT
# =============================================================================

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="ARIA - Autonomous Reflective Intelligence Architecture",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python aria.py              Start conversation with ARIA
  python aria.py --status     Show system status
  python aria.py --version    Show version

Type / or help to see all available commands.

Coding Agent (ARIA as developer):
  proj PATH    - Set working project
  dev          - Show coding capabilities
  chat X       - Conversational mode (natural language)
  work X       - Agentic mode (ARIA works)
  code X       - Write/modify code
  fix X        - Fix a bug
  explain X    - Explain code

You can paste code blocks directly (automatic detection).

exit           - End session

Created by William and Claude, December 2025.
        """
    )

    parser.add_argument(
        '--version', '-v',
        action='store_true',
        help='Show ARIA version'
    )

    parser.add_argument(
        '--status', '-s',
        action='store_true',
        help='Show system status'
    )

    parser.add_argument(
        '--check', '-c',
        action='store_true',
        help='Check requirements without starting'
    )

    args = parser.parse_args()

    if args.version:
        print(f"ARIA version {VERSION}")
        print("Created by William and Claude")
        print("December 2025")
        sys.exit(0)

    if args.status:
        show_status()
        sys.exit(0)

    if args.check:
        print("Checking requirements...")
        if check_requirements():
            print("+ All requirements satisfied")
        sys.exit(0)

    # By default, run full ARIA
    print(BANNER)

    if not check_requirements():
        print("\nResolve the above issues before continuing.")
        sys.exit(1)

    check_data_directories()

    aria = ARIA()

    # Configure signal handlers for emergency save
    import signal

    def emergency_save(signum, frame):
        """Save state in case of unexpected shutdown"""
        print("\n[Emergency save...]")
        try:
            if hasattr(aria, 'autonomous') and aria.autonomous:
                aria.autonomous.stop()
            if aria.mcp_bridge:
                aria.mcp_bridge.shutdown_all()
            aria.session.do_auto_save(aria.conversation_history)
            aria.session.go_to_sleep(aria.conversation_history, aria.session_start)
        except Exception as e:
            print(f"Emergency save failed: {e}")
        sys.exit(0)

    # Register handlers (works on Unix/WSL)
    try:
        signal.signal(signal.SIGTERM, emergency_save)  # kill
        signal.signal(signal.SIGHUP, emergency_save)   # terminal close
    except Exception:
        pass  # Some signals don't exist on Windows

    aria.run()


if __name__ == "__main__":
    main()
