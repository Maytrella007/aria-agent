"""
Tool Names - Central registry of tool name constants.

Single source of truth for all tool identifiers used across ARIA.
Skills and other modules should import these constants instead of
using raw strings, to avoid typos and enable IDE autocompletion.

Usage:
    from core.tools.tool_names import Tools

    result = ctx.tools.execute(Tools.WEB_SEARCH, query="weather Madrid")
    result = ctx.tools.execute(Tools.GIT, action="status")
"""


class Tools:
    """Constants for every registered tool name."""

    # --- Web & Network ---
    WEB_SEARCH = "web_search"
    WEB_FETCH = "web_fetch"
    HTTP_REQUEST = "http_request"
    BROWSER = "browser"
    DOWNLOAD = "download"

    # --- File System ---
    FILE_MANAGER = "file_manager"
    COMPRESS = "compress"
    PDF_READ = "pdf_read"

    # --- Execution ---
    SHELL_EXEC = "shell_exec"
    CODE_EXEC = "code_exec"

    # --- Data ---
    CALCULATOR = "calculator"
    DATABASE = "database"
    RAG = "rag"
    TRANSLATE = "translate"

    # --- Git ---
    GIT = "git"
    GITHUB = "github"

    # --- Documents ---
    WORD = "word"
    EXCEL = "excel"
    POWERPOINT = "powerpoint"

    # --- Scheduling & Tasks ---
    CRON = "cron"
    TODO = "todo"

    # --- AI & Agents ---
    ORCHESTRATE = "orchestrate"
    IMAGE_GENERATE = "image_generate"

    # --- System ---
    SYSTEM_INFO = "system_info"

    # --- Communication ---
    EMAIL = "email"
    GMAIL = "gmail"
    SLACK = "slack"

    # --- Google Workspace ---
    GOOGLE_DRIVE = "google_drive"
    GOOGLE_CALENDAR = "google_calendar"
    OBSIDIAN = "obsidian"

    # --- Knowledge ---
    MEMORY_SEARCH = "memory_search"
    PROJECT_KNOWLEDGE = "project_knowledge"
    CURIOSITY = "curiosity"
    FEED_WATCHER = "feed_watcher"
    TMUX = "tmux"

    @classmethod
    def all(cls) -> list:
        """Return all tool name constants."""
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str) and k.isupper()
        ]
