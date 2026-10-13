"""Tests for GitHubTool."""

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools.github_tool import GitHubTool


class TestGitHubTool:
    @patch("core.tools.github_tool.shutil.which", return_value=None)
    def test_requires_gh_binary(self, _mock_which):
        tool = GitHubTool()
        result = tool.execute(action="auth_status")
        assert not result.success
        assert "gh" in result.error.lower()

    @patch("core.tools.github_tool.shutil.which", return_value="/usr/bin/gh")
    @patch("core.tools.github_tool.subprocess.run")
    def test_auth_status(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="Logged in", stderr="")
        tool = GitHubTool()
        result = tool.execute(action="auth_status")
        assert result.success
        assert "Logged in" in result.output

    @patch("core.tools.github_tool.shutil.which", return_value="/usr/bin/gh")
    @patch("core.tools.github_tool.subprocess.run")
    def test_pr_view_requires_number(self, mock_run, _mock_which):
        tool = GitHubTool()
        result = tool.execute(action="pr_view")
        assert not result.success
        mock_run.assert_not_called()

    @patch("core.tools.github_tool.shutil.which", return_value="/usr/bin/gh")
    @patch("core.tools.github_tool.subprocess.run")
    def test_pr_list_with_repo(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="PR list", stderr="")
        tool = GitHubTool()
        result = tool.execute(action="pr_list", repo="owner/repo", limit=5)
        assert result.success
        cmd = mock_run.call_args.args[0]
        assert cmd[:3] == ["/usr/bin/gh", "pr", "list"]
        assert "--repo" in cmd
        assert "owner/repo" in cmd

    @patch("core.tools.github_tool.shutil.which", return_value="/usr/bin/gh")
    @patch("core.tools.github_tool.subprocess.run")
    def test_api_action(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout='{"ok": true}', stderr="")
        tool = GitHubTool()
        result = tool.execute(action="api", query="repos/octo/demo")
        assert result.success
        assert result.data["json"]["ok"] is True
