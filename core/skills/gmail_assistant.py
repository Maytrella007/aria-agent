"""
Gmail Assistant Skill - Read, search, and reply to Gmail.

Uses the Gmail tool with OAuth to access the user's inbox.
Can search, summarize, and help compose replies.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class GmailAssistantSkill(SkillBase):
    name = "gmail_assistant"
    description = "Read, search, and manage Gmail messages"
    requires_tools = [Tools.GMAIL]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        op = self._detect_operation(query)

        if op == "search":
            return self._search_emails(query, ctx)
        elif op == "read":
            return self._read_email(query, ctx)
        elif op == "reply":
            return self._reply_email(query, ctx)
        else:
            return self._check_inbox(ctx)

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["search", "buscar", "find", "emails from", "correos de"]):
            return "search"
        if any(w in q for w in ["read", "leer", "open", "abrir"]):
            return "read"
        if any(w in q for w in ["reply", "respond", "responder", "contestar"]):
            return "reply"
        return "inbox"

    def _check_inbox(self, ctx: SkillContext) -> SkillResult:
        """Check recent/unread emails."""
        result = ctx.tools.execute(
            Tools.GMAIL,
            action="search",
            query="is:unread",
            max_results=10,
        )

        if not result.success:
            return SkillResult(success=False, error=f"Gmail access failed: {result.error}")

        if ctx.llm:
            return self._summarize_emails(result.output, "unread inbox", ctx)

        return SkillResult(
            success=True,
            output=f"Inbox:\n{result.output}",
            data={"action": "inbox"},
        )

    def _search_emails(self, query: str, ctx: SkillContext) -> SkillResult:
        """Search emails by query."""
        search_query = self._extract_search_query(query)

        result = ctx.tools.execute(
            Tools.GMAIL,
            action="search",
            query=search_query,
            max_results=10,
        )

        if not result.success:
            return SkillResult(success=False, error=f"Email search failed: {result.error}")

        if ctx.llm:
            return self._summarize_emails(result.output, search_query, ctx)

        return SkillResult(
            success=True,
            output=f"Search results for '{search_query}':\n{result.output}",
            data={"action": "search", "query": search_query},
        )

    def _read_email(self, query: str, ctx: SkillContext) -> SkillResult:
        """Read a specific email."""
        # Try to extract email ID
        id_match = re.search(r'(?:id|#)\s*(\w+)', query)
        if id_match:
            result = ctx.tools.execute(Tools.GMAIL, action="read", id=id_match.group(1))
            if result.success:
                return SkillResult(
                    success=True,
                    output=result.output,
                    data={"action": "read", "id": id_match.group(1)},
                )

        # Search for the most recent matching email
        search_term = re.sub(
            r'\b(read|leer|open|abrir|email|correo|the|el|my|mi)\b',
            '', query, flags=re.IGNORECASE,
        ).strip()

        if search_term:
            result = ctx.tools.execute(
                Tools.GMAIL,
                action="search",
                query=search_term,
                max_results=1,
            )
            if result.success:
                return SkillResult(
                    success=True,
                    output=result.output,
                    data={"action": "read", "search": search_term},
                )

        return SkillResult(
            success=False,
            error="Specify which email to read (by ID or search term)",
        )

    def _reply_email(self, query: str, ctx: SkillContext) -> SkillResult:
        """Help compose a reply to an email."""
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required to compose replies")

        # Extract what to reply
        reply_content = re.sub(
            r'\b(reply|respond|responder|contestar|to|the|al|email|correo)\b',
            '', query, flags=re.IGNORECASE,
        ).strip()

        prompt = f"""Help compose an email reply based on these instructions:

Instructions: {reply_content or query}

Draft a professional reply. Provide:
SUBJECT: Re: <subject>
---
<reply body>

Keep it concise and professional."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=f"Draft reply:\n\n{response.content}",
                    data={"action": "reply", "draft": True},
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Reply composition failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")

    def _extract_search_query(self, query: str) -> str:
        """Extract Gmail search query from natural language."""
        # "emails from John" -> "from:John"
        m = re.search(r'(?:from|de)\s+(\S+)', query, re.IGNORECASE)
        if m:
            return f"from:{m.group(1)}"

        # "emails about project" -> "subject:project"
        m = re.search(r'(?:about|sobre|regarding)\s+(.+)', query, re.IGNORECASE)
        if m:
            return m.group(1).strip()

        # "unread emails" -> "is:unread"
        if any(w in query.lower() for w in ["unread", "sin leer", "nuevos"]):
            return "is:unread"

        # Remove trigger words
        cleaned = re.sub(
            r'\b(search|buscar|find|email|correo|my|mi|in|en|for|the)\b',
            '', query, flags=re.IGNORECASE,
        )
        return cleaned.strip() or "is:unread"

    def _summarize_emails(self, raw_data, context, ctx) -> SkillResult:
        """Summarize email list with LLM."""
        prompt = f"""Summarize these email results ({context}):

{raw_data[:3000]}

For each email, show:
- From, Subject, Date (1 line each)
- Brief preview (1 line)

Keep it scannable. Highlight important/urgent emails."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=500,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"action": "search", "context": context, "summarized": True},
                )
        except Exception:
            pass

        return SkillResult(
            success=True,
            output=raw_data[:2000],
            data={"action": "search", "context": context},
        )
