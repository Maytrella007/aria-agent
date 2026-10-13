"""
ARIA - World Access Module
===========================
System information and capabilities description.

Note: Web access (search, fetch) and file operations are handled by the
tool system (WebSearchTool, WebFetchTool, ShellExecTool, FileManagerTool).
This module provides only system info for prompt building and a capabilities
description for the /world command.
"""

import os
import platform
from typing import Dict


class SystemAccess:
    """Operating system information for ARIA."""

    def __init__(self):
        self.home_dir = os.path.expanduser("~")
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        )))

    def get_system_info(self) -> Dict:
        """Gets system information for the LLM system prompt."""
        return {
            'os': platform.system(),
            'os_version': platform.version(),
            'machine': platform.machine(),
            'python_version': platform.python_version(),
            'home_directory': self.home_dir,
            'current_directory': os.getcwd(),
            'project_root': self.project_root,
            'user': os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))
        }


class WorldInterface:
    """
    ARIA's interface with the outside world.
    System info + capabilities description.

    Web and file operations are delegated to the tool system.
    """

    def __init__(self):
        self.system = SystemAccess()

    def describe_capabilities(self) -> str:
        """Describes what ARIA can do with the world."""
        return """=== WORLD ACCESS CAPABILITIES ===

INTERNET (via tool system):
- web_search: Search the web (DuckDuckGo)
- web_fetch: Fetch and extract content from any URL (+ Playwright JS rendering)
- browser: Full browser automation with stealth mode
- http_request: Raw HTTP requests (GET, POST, etc.)
- download: Download files up to 100MB+

SYSTEM (via tool system):
- shell_exec: Execute terminal commands (with security validation)
- file_manager: Read, write, copy, move, delete files
- git: 17 hardened git operations
- system_info: CPU, RAM, disk monitoring
- cron_tool: Scheduled tasks

OFFICE & DATA:
- excel, word, powerpoint: Read/write Office documents
- database: SQLite + PostgreSQL
- pdf: PDF text extraction
- calculator: Sandboxed math evaluation

AI & KNOWLEDGE:
- curiosity: Autonomous web exploration
- memory_search: Semantic memory recall
- rag: Document ingestion and retrieval
- translate: Multi-language translation
- image_generate: DALL-E image generation
"""
