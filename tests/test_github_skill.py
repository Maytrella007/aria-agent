"""Tests for GitHubOpsSkill."""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.skills.base import SkillContext
from core.skills.github_ops import GitHubOpsSkill


def make_ctx(output="Mock GitHub output"):
    tools = MagicMock()
    result = MagicMock()
    result.success = True
    result.output = output
    result.data = {}
    result.error = None
    tools.execute.return_value = result
    return SkillContext(tools=tools)


class TestGitHubOpsSkill:
    def test_detect_pr_list(self):
        s = GitHubOpsSkill()
        assert s._detect_operation("list open prs") == "pr_list"

    def test_detect_issue_view(self):
        s = GitHubOpsSkill()
        assert s._detect_operation("show issue 42") == "issue_view"

    def test_detect_run_list(self):
        s = GitHubOpsSkill()
        assert s._detect_operation("list recent workflow runs") == "run_list"

    def test_execute_pr_checks(self):
        s = GitHubOpsSkill()
        ctx = make_ctx("All checks passed")
        result = s.execute("check CI for PR 12", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("github", action="pr_checks", number=12)

    def test_execute_issue_list(self):
        s = GitHubOpsSkill()
        ctx = make_ctx("1. Bug\n2. Feature")
        result = s.execute("list 5 open issues", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("github", action="issue_list", limit=5)

    def test_clone_repo_by_owner_and_name(self):
        s = GitHubOpsSkill()
        ctx = make_ctx("Cloning into 'ARIA'...")
        result = s.execute("clone ARIA from Maytrella007 on github", ctx)
        assert result.success
        ctx.tools.execute.assert_called_with("git", action="clone", args="https://github.com/Maytrella007/ARIA.git")

    def test_without_tools(self):
        s = GitHubOpsSkill()
        result = s.execute("list prs", SkillContext())
        assert not result.success
