"""Workspace Knowledge Skill."""

import re

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class WorkspaceKnowledgeSkill(SkillBase):
    name = "workspace_knowledge"
    description = "Search, read, and save shared knowledge in the local Obsidian workspace vault"
    requires_tools = [Tools.OBSIDIAN]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")
        op = self._detect_operation(query)
        if op == "save":
            path = self._extract_note_path(query) or "captured_note.md"
            content = self._extract_content(query)
            result = ctx.tools.execute(Tools.OBSIDIAN, action="write", path=path, content=content)
        elif op == "read":
            path = self._extract_note_path(query)
            if not path:
                return SkillResult(success=False, error="Specify which note to read")
            result = ctx.tools.execute(Tools.OBSIDIAN, action="read", path=path)
        else:
            search_query = self._extract_search_query(query)
            result = ctx.tools.execute(Tools.OBSIDIAN, action="search", query=search_query)
        return SkillResult(success=result.success, output=result.output, error=result.error, data={"operation": op, **(result.data or {})})

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["save", "store", "write note", "guarda", "crear nota"]):
            return "save"
        if any(w in q for w in ["read", "open", "show note", "lee"]):
            return "read"
        return "search"

    def _extract_note_path(self, query: str) -> str:
        m = re.search(r'([\w./-]+\.md)', query)
        return m.group(1) if m else ""

    def _extract_content(self, query: str) -> str:
        m = re.search(r'(?i)(?:save|store|write note|guarda)\s+(.+)', query)
        return m.group(1).strip() if m else query.strip()

    def _extract_search_query(self, query: str) -> str:
        return re.sub(r'\b(search|find|look for|obsidian|note|notes|buscar)\b', '', query, flags=re.IGNORECASE).strip()
