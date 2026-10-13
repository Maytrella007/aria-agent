"""Tests for SlackTool, ObsidianTool, and TmuxTool."""

import io
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools.slack_tool import SlackTool
from core.tools.obsidian_tool import ObsidianTool
from core.tools.tmux_tool import TmuxTool


class TestSlackTool:
    def test_requires_token(self):
        tool = SlackTool(context={})
        with patch.dict(os.environ, {}, clear=True):
            result = tool.execute(action="read_messages", channel="C12345")
        assert not result.success

    @patch("core.tools.slack_tool.urllib.request.urlopen")
    def test_send_message(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"ok": True, "ts": "123.4"}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        tool = SlackTool(context={"slack_token": "xoxb-test"})
        result = tool.execute(action="send_message", channel="C12345", text="hello")
        assert result.success


class TestObsidianTool:
    def test_write_and_read(self, tmp_path):
        tool = ObsidianTool(context={"data_dir": str(tmp_path)})
        write = tool.execute(action="write", path="notes/test.md", content="hello obsidian")
        assert write.success
        read = tool.execute(action="read", path="notes/test.md")
        assert read.success
        assert "hello obsidian" in read.output

    def test_search(self, tmp_path):
        tool = ObsidianTool(context={"data_dir": str(tmp_path)})
        tool.execute(action="write", path="alpha.md", content="meeting architecture notes")
        result = tool.execute(action="search", query="architecture")
        assert result.success
        assert "alpha.md" in result.output


class TestTmuxTool:
    @patch("core.tools.tmux_tool.shutil.which", return_value=None)
    def test_requires_tmux(self, _mock_which):
        tool = TmuxTool()
        result = tool.execute(action="list_sessions")
        assert not result.success

    @patch("core.tools.tmux_tool.shutil.which", return_value="/usr/bin/tmux")
    @patch("core.tools.tmux_tool.subprocess.run")
    def test_list_sessions(self, mock_run, _mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="dev: 1 windows", stderr="")
        tool = TmuxTool()
        result = tool.execute(action="list_sessions")
        assert result.success
        assert "dev" in result.output
