"""
ARIA Skills System
===================

Skills come in two flavors:
  - Orchestration skills: Python code that chains multiple tools in specific
    sequences with conditional logic, fallbacks, and state management.
  - Prompt skills: Lightweight LLM prompt templates for domain-specific tasks
    where the value is in the instructions, not in code logic.

Tools the LLM can call directly via function calling don't need a skill wrapper.
"""

from .base import SkillBase, SkillResult, SkillContext, SkillRegistry
from .prompt_skills import (
    PromptSkill,
    WeatherSkill,
)
from .prompt_skill_loader import (
    DynamicPromptSkill,
    load_prompt_skills,
    reload_prompt_skills,
)

# Orchestration skills
from .research import ResearchSkill
from .summarize import SummarizeSkill
from .daily_brief import DailyBriefSkill
from .file_ops import FileOpsSkill
from .schedule import ScheduleSkill
from .git_ops import GitOpsSkill
from .github_ops import GitHubOpsSkill
from .coding_agent import CodingAgentSkill
from .data_analysis import DataAnalysisSkill
from .doc_create import DocCreateSkill
from .knowledge_base import KnowledgeBaseSkill
from .gmail_assistant import GmailAssistantSkill
from .quick_task import QuickTaskSkill
from .research_monitor import ResearchMonitorSkill
from .inbox_triage import InboxTriageSkill
from .meeting_prep import MeetingPrepSkill
from .slack_assistant import SlackAssistantSkill
from .workspace_knowledge import WorkspaceKnowledgeSkill
from .terminal_session import TerminalSessionSkill

__all__ = [
    "SkillBase",
    "SkillResult",
    "SkillContext",
    "SkillRegistry",
    "PromptSkill",
    # Prompt skills (LLM-powered templates)
    "WeatherSkill",
    # Orchestration skills (coded multi-step workflows)
    "ResearchSkill",
    "SummarizeSkill",
    "DailyBriefSkill",
    "FileOpsSkill",
    "ScheduleSkill",
    "GitOpsSkill",
    "GitHubOpsSkill",
    "CodingAgentSkill",
    "DataAnalysisSkill",
    "DocCreateSkill",
    "KnowledgeBaseSkill",
    "GmailAssistantSkill",
    "QuickTaskSkill",
    "ResearchMonitorSkill",
    "InboxTriageSkill",
    "MeetingPrepSkill",
    "SlackAssistantSkill",
    "WorkspaceKnowledgeSkill",
    "TerminalSessionSkill",
    # Dynamic prompt skills
    "DynamicPromptSkill",
    "load_prompt_skills",
    "reload_prompt_skills",
]
