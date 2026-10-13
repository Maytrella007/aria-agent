"""
ARIA - GitHub Tool
===================

GitHub operations via the `gh` CLI.
Complements the local git tool with remote GitHub workflows.
"""

import json
import shutil
import subprocess
from typing import List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult


class GitHubTool(ToolBase):
    """Operate on GitHub repositories via gh CLI."""

    name = "github"
    description = (
        "GitHub operations via gh CLI. Actions: auth_status, pr_list, pr_view, "
        "pr_create, pr_checks, issue_list, issue_view, issue_create, run_list, "
        "run_view, api. Use for PRs, issues, CI runs, and GitHub API queries."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="GitHub action to perform",
            required=True,
            enum=[
                "auth_status",
                "pr_list", "pr_view", "pr_create", "pr_checks",
                "issue_list", "issue_view", "issue_create",
                "run_list", "run_view",
                "api",
            ],
        ),
        ToolParam(name="repo", type="string", description="Repository in owner/name format.", required=False),
        ToolParam(name="number", type="integer", description="PR or issue number.", required=False),
        ToolParam(name="title", type="string", description="Title for create actions.", required=False),
        ToolParam(name="body", type="string", description="Body for create actions.", required=False),
        ToolParam(name="query", type="string", description="API path for api action.", required=False),
        ToolParam(name="limit", type="integer", description="Max results for list actions.", required=False, default=10),
        ToolParam(name="run_id", type="string", description="Workflow run id for run_view.", required=False),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        gh = shutil.which("gh")
        if not gh:
            return ToolResult(success=False, error="GitHub CLI not installed. Install `gh` first.")

        action = kwargs["action"]
        if action == "auth_status":
            return self._run([gh, "auth", "status"])

        builder = getattr(self, f"_build_{action}", None)
        if not builder:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        cmd = builder(gh, kwargs)
        if not cmd:
            return ToolResult(success=False, error=f"Missing required arguments for action: {action}")

        return self._run(cmd)

    def _with_repo(self, cmd: List[str], repo: Optional[str]) -> List[str]:
        if repo:
            cmd.extend(["--repo", repo])
        return cmd

    def _build_pr_list(self, gh: str, kwargs: dict) -> List[str]:
        return self._with_repo([gh, "pr", "list", "--limit", str(min(kwargs.get("limit", 10), 50))], kwargs.get("repo"))

    def _build_pr_view(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        number = kwargs.get("number")
        if number is None:
            return None
        return self._with_repo([gh, "pr", "view", str(number)], kwargs.get("repo"))

    def _build_pr_create(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        title = kwargs.get("title")
        body = kwargs.get("body")
        if not title or body is None:
            return None
        return self._with_repo([gh, "pr", "create", "--title", title, "--body", body], kwargs.get("repo"))

    def _build_pr_checks(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        number = kwargs.get("number")
        if number is None:
            return None
        return self._with_repo([gh, "pr", "checks", str(number)], kwargs.get("repo"))

    def _build_issue_list(self, gh: str, kwargs: dict) -> List[str]:
        return self._with_repo([gh, "issue", "list", "--limit", str(min(kwargs.get("limit", 10), 50))], kwargs.get("repo"))

    def _build_issue_view(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        number = kwargs.get("number")
        if number is None:
            return None
        return self._with_repo([gh, "issue", "view", str(number)], kwargs.get("repo"))

    def _build_issue_create(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        title = kwargs.get("title")
        body = kwargs.get("body")
        if not title or body is None:
            return None
        return self._with_repo([gh, "issue", "create", "--title", title, "--body", body], kwargs.get("repo"))

    def _build_run_list(self, gh: str, kwargs: dict) -> List[str]:
        return self._with_repo([gh, "run", "list", "--limit", str(min(kwargs.get("limit", 10), 50))], kwargs.get("repo"))

    def _build_run_view(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        run_id = kwargs.get("run_id")
        if not run_id:
            return None
        return self._with_repo([gh, "run", "view", str(run_id)], kwargs.get("repo"))

    def _build_api(self, gh: str, kwargs: dict) -> Optional[List[str]]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            return None
        return [gh, "api", query]

    def _run(self, cmd: List[str]) -> ToolResult:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="GitHub command timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        output = stdout or stderr or "(no output)"

        if proc.returncode != 0:
            return ToolResult(success=False, error=output, data={"command": cmd, "returncode": proc.returncode})

        data = {"command": cmd, "returncode": proc.returncode, "stdout": stdout, "stderr": stderr}
        if stdout:
            try:
                data["json"] = json.loads(stdout)
            except Exception:
                pass

        return ToolResult(success=True, output=output, data=data)
