"""
ARIA - Tools Module
====================

Unified tool system inspired by OpenClaw's architecture.
Each tool has a standard interface, typed parameters, and function calling schemas.
"""

from .tool_base import ToolBase, ToolParam, ToolResult
from .tool_names import Tools
from .registry import ToolRegistry
from .web_search import WebSearchTool
from .web_fetch import WebFetchTool
from .shell_exec import ShellExecTool
from .cron_tool import CronTool
from .file_manager import FileManagerTool
from .http_request import HttpRequestTool
from .code_exec import CodeExecTool
from .git_tool import GitTool
from .github_tool import GitHubTool
from .email_tool import EmailTool
from .slack_tool import SlackTool
from .memory_tool import MemoryTool
from .download_tool import DownloadTool
from .system_info import SystemInfoTool
from .pdf_tool import PdfTool
from .project_knowledge import ProjectKnowledgeTool
from .database_tool import DatabaseTool
from .calculator_tool import CalculatorTool
from .compress_tool import CompressTool
from .todo_tool import TodoTool
from .image_gen_tool import ImageGenTool
from .translate_tool import TranslateTool
from .rag_tool import DocumentRAGTool
from .browser_tool import BrowserTool
from .feed_watcher import FeedWatcherTool
from .excel_tool import ExcelTool
from .word_tool import WordTool
from .powerpoint_tool import PowerPointTool
from .curiosity_tool import CuriosityTool
from .gmail_tool import GmailTool
from .drive_tool import GoogleDriveTool
from .calendar_tool import GoogleCalendarTool
from .obsidian_tool import ObsidianTool
from .tmux_tool import TmuxTool

__all__ = [
    "ToolBase", "ToolParam", "ToolResult", "Tools", "ToolRegistry",
    "WebSearchTool", "WebFetchTool", "ShellExecTool",
    "CronTool", "FileManagerTool", "HttpRequestTool",
    "CodeExecTool", "GitTool", "GitHubTool", "EmailTool", "SlackTool",
    "MemoryTool", "DownloadTool", "SystemInfoTool", "PdfTool",
    "ProjectKnowledgeTool", "DatabaseTool", "CalculatorTool",
    "CompressTool", "TodoTool", "ImageGenTool", "TranslateTool",
    "DocumentRAGTool", "BrowserTool",
    "FeedWatcherTool",
    "ExcelTool", "WordTool", "PowerPointTool", "ObsidianTool", "TmuxTool",
    "CuriosityTool",
    "GmailTool", "GoogleDriveTool", "GoogleCalendarTool",
]
