"""GitHub Operations Skill - Remote GitHub workflows via gh."""

import re

from .base import SkillBase, SkillContext, SkillResult
from core.tools.tool_names import Tools


class GitHubOpsSkill(SkillBase):
    name = "github_ops"
    description = "GitHub workflows: clone repos by owner/name, pull requests, issues, CI checks, workflow runs, and repo API queries"
    requires_tools = [Tools.GITHUB, Tools.GIT]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        op = self._detect_operation(query)
        if op == "pr_list":
            result = ctx.tools.execute(Tools.GITHUB, action="pr_list", limit=self._extract_limit(query))
        elif op == "clone":
            repo = self._extract_repo_slug(query)
            if not repo:
                return SkillResult(success=False, error="Specify a GitHub repo like owner/name or 'repo name from owner'")
            clone_url = f"https://github.com/{repo}.git"
            result = ctx.tools.execute(Tools.GIT, action="clone", args=clone_url)
        elif op == "pr_view":
            number = self._extract_number(query)
            if number is None:
                return SkillResult(success=False, error="Specify which PR number to inspect")
            result = ctx.tools.execute(Tools.GITHUB, action="pr_view", number=number)
        elif op == "pr_checks":
            number = self._extract_number(query)
            if number is None:
                return SkillResult(success=False, error="Specify which PR number to check")
            result = ctx.tools.execute(Tools.GITHUB, action="pr_checks", number=number)
        elif op == "issue_list":
            result = ctx.tools.execute(Tools.GITHUB, action="issue_list", limit=self._extract_limit(query))
        elif op == "issue_view":
            number = self._extract_number(query)
            if number is None:
                return SkillResult(success=False, error="Specify which issue number to inspect")
            result = ctx.tools.execute(Tools.GITHUB, action="issue_view", number=number)
        elif op == "run_list":
            result = ctx.tools.execute(Tools.GITHUB, action="run_list", limit=self._extract_limit(query))
        elif op == "run_view":
            run_id = self._extract_run_id(query)
            if not run_id:
                return SkillResult(success=False, error="Specify which run id to inspect")
            result = ctx.tools.execute(Tools.GITHUB, action="run_view", run_id=run_id)
        elif op == "auth_status":
            result = ctx.tools.execute(Tools.GITHUB, action="auth_status")
        else:
            api_query = self._extract_api_query(query)
            if not api_query:
                return SkillResult(success=False, error="Unsupported GitHub request")
            result = ctx.tools.execute(Tools.GITHUB, action="api", query=api_query)

        if not result.success:
            return SkillResult(success=False, error=result.error)

        return SkillResult(success=True, output=result.output, data={"operation": op, **(result.data or {})})

    def _detect_operation(self, query: str) -> str:
        q = query.lower()
        if "auth" in q and "github" in q:
            return "auth_status"
        if any(w in q for w in ["clone", "clona", "clonar"]):
            return "clone"
        if "checks" in q or "ci" in q:
            return "pr_checks"
        if "pull request" in q or "prs" in q or re.search(r'\bpr\b', q):
            if any(w in q for w in ["list", "open prs", "show prs", "pull requests", "prs"]):
                return "pr_list"
            return "pr_view"
        if "issue" in q:
            if any(w in q for w in ["list", "open issues", "show issues"]):
                return "issue_list"
            return "issue_view"
        if "run" in q or "workflow" in q:
            if any(w in q for w in ["list", "recent", "latest"]):
                return "run_list"
            return "run_view"
        if "api" in q:
            return "api"
        return "auth_status"

    def _extract_repo_slug(self, query: str) -> str:
        explicit = re.search(r'([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)', query)
        if explicit:
            return explicit.group(1)

        pair = re.search(
            r'(?:repo\s+)?([A-Za-z0-9_.-]+)\s+(?:de|from)\s+([A-Za-z0-9_.-]+)',
            query,
            re.IGNORECASE,
        )
        if pair:
            repo, owner = pair.group(1), pair.group(2)
            return f"{owner}/{repo}"
        return ""

    def _extract_number(self, query: str):
        m = re.search(r'#?(\d+)', query)
        return int(m.group(1)) if m else None

    def _extract_run_id(self, query: str):
        m = re.search(r'run\s+#?(\d+)', query, re.IGNORECASE)
        if m:
            return m.group(1)
        m = re.search(r'workflow\s+#?(\d+)', query, re.IGNORECASE)
        return m.group(1) if m else None

    def _extract_limit(self, query: str) -> int:
        m = re.search(r'(\d+)', query)
        return min(int(m.group(1)), 50) if m else 10

    def _extract_api_query(self, query: str) -> str:
        return re.sub(r'^.*?api\s+', '', query, flags=re.IGNORECASE).strip()
