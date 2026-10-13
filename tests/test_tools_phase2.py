"""
Tests for ARIA Tools - Phase 2
================================
CronTool, FileManagerTool, HttpRequestTool, CodeExecTool, GitTool, EmailTool
"""

import pytest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools import (
    CronTool, FileManagerTool, HttpRequestTool,
    CodeExecTool, GitTool, EmailTool,
)


# =============================================================================
# CRON TOOL
# =============================================================================

class TestCronTool:
    def test_list_empty(self):
        tool = CronTool(context={"data_dir": tempfile.mkdtemp()})
        r = tool.execute(action="list")
        assert r.success
        assert "No scheduled" in r.output

    def test_add_and_list(self):
        tool = CronTool(context={"data_dir": tempfile.mkdtemp()})
        r = tool.execute(action="add", name="test_job", schedule="every 5 minutes", task="say hello")
        assert r.success
        assert "test_job" in r.output

        r = tool.execute(action="list")
        assert r.success
        assert "test_job" in r.output
        assert "every 5 minutes" in r.output

    def test_remove(self):
        d = tempfile.mkdtemp()
        tool = CronTool(context={"data_dir": d})
        tool.execute(action="add", name="rm_job", schedule="every 1 hour", task="cleanup")
        r = tool.execute(action="remove", name="rm_job")
        assert r.success

    def test_remove_nonexistent(self):
        tool = CronTool(context={"data_dir": tempfile.mkdtemp()})
        r = tool.execute(action="remove", name="nope")
        assert not r.success

    def test_disable_enable(self):
        d = tempfile.mkdtemp()
        tool = CronTool(context={"data_dir": d})
        tool.execute(action="add", name="toggle_job", schedule="every 10 minutes", task="ping")
        r = tool.execute(action="disable", name="toggle_job")
        assert r.success
        assert "disabled" in r.output

        r = tool.execute(action="enable", name="toggle_job")
        assert r.success
        assert "enabled" in r.output

    def test_run_now(self):
        d = tempfile.mkdtemp()
        tool = CronTool(context={"data_dir": d})
        tool.execute(action="add", name="run_job", schedule="every 1 hour", task="do thing")
        r = tool.execute(action="run", name="run_job")
        assert r.success
        assert "do thing" in r.output

    def test_add_missing_params(self):
        tool = CronTool(context={"data_dir": tempfile.mkdtemp()})
        r = tool.execute(action="add", name="x")
        assert not r.success

    def test_schema(self):
        tool = CronTool()
        s = tool.to_function_schema()
        assert s["name"] == "cron"
        assert "action" in s["parameters"]["properties"]


# =============================================================================
# FILE MANAGER TOOL
# =============================================================================

class TestFileManagerTool:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = FileManagerTool()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read(self):
        path = os.path.join(self.tmpdir, "test.txt")
        r = self.tool.execute(action="write", path=path, content="hello world")
        assert r.success

        r = self.tool.execute(action="read", path=path)
        assert r.success
        assert "hello world" in r.output

    def test_append(self):
        path = os.path.join(self.tmpdir, "append.txt")
        self.tool.execute(action="write", path=path, content="line1\n")
        self.tool.execute(action="append", path=path, content="line2\n")
        r = self.tool.execute(action="read", path=path)
        assert "line1" in r.output
        assert "line2" in r.output

    def test_list(self):
        open(os.path.join(self.tmpdir, "a.txt"), "w").close()
        open(os.path.join(self.tmpdir, "b.py"), "w").close()
        r = self.tool.execute(action="list", path=self.tmpdir)
        assert r.success
        assert "a.txt" in r.output
        assert "b.py" in r.output

    def test_search(self):
        os.makedirs(os.path.join(self.tmpdir, "sub"))
        open(os.path.join(self.tmpdir, "sub", "found.py"), "w").close()
        open(os.path.join(self.tmpdir, "other.txt"), "w").close()
        r = self.tool.execute(action="search", path=self.tmpdir, pattern="*.py")
        assert r.success
        assert "found.py" in r.output
        assert "other.txt" not in r.output

    def test_info(self):
        path = os.path.join(self.tmpdir, "info.txt")
        with open(path, "w") as f:
            f.write("data")
        r = self.tool.execute(action="info", path=path)
        assert r.success
        assert "file" in r.output

    def test_mkdir(self):
        path = os.path.join(self.tmpdir, "newdir", "sub")
        r = self.tool.execute(action="mkdir", path=path)
        assert r.success
        assert os.path.isdir(path)

    def test_delete(self):
        path = os.path.join(self.tmpdir, "del.txt")
        open(path, "w").close()
        r = self.tool.execute(action="delete", path=path)
        assert r.success
        assert not os.path.exists(path)

    def test_delete_dir_blocked(self):
        r = self.tool.execute(action="delete", path=self.tmpdir)
        assert not r.success
        assert "Cannot delete directories" in r.error

    def test_read_nonexistent(self):
        r = self.tool.execute(action="read", path="/nonexistent/file.txt")
        assert not r.success

    def test_write_missing_content(self):
        r = self.tool.execute(action="write", path=os.path.join(self.tmpdir, "x"))
        assert not r.success


# =============================================================================
# HTTP REQUEST TOOL
# =============================================================================

class TestHttpRequestTool:
    def test_init(self):
        tool = HttpRequestTool()
        assert tool.name == "http_request"

    def test_invalid_url(self):
        tool = HttpRequestTool()
        r = tool.execute(url="not-a-url")
        assert not r.success

    def test_schema(self):
        tool = HttpRequestTool()
        s = tool.to_function_schema()
        assert "url" in s["parameters"]["properties"]
        assert "method" in s["parameters"]["properties"]

    def test_bad_headers_json(self):
        tool = HttpRequestTool()
        r = tool.execute(url="https://example.com", headers="not json")
        assert not r.success
        assert "Invalid headers" in r.error


# =============================================================================
# CODE EXEC TOOL
# =============================================================================

class TestCodeExecTool:
    def test_simple_print(self):
        tool = CodeExecTool()
        r = tool.execute(code="print('hello from python')")
        assert r.success
        assert "hello from python" in r.output

    def test_expression_result(self):
        tool = CodeExecTool()
        r = tool.execute(code="2 + 2")
        assert r.success
        assert "4" in r.output

    def test_multiline(self):
        tool = CodeExecTool()
        r = tool.execute(code="x = [1,2,3]\nprint(sum(x))")
        assert r.success
        assert "6" in r.output

    def test_import(self):
        tool = CodeExecTool()
        r = tool.execute(code="import math\nprint(math.pi)")
        assert r.success
        assert "3.14" in r.output

    def test_error_handling(self):
        tool = CodeExecTool()
        r = tool.execute(code="1/0")
        assert not r.success
        assert "ZeroDivision" in r.output

    def test_syntax_error(self):
        tool = CodeExecTool()
        r = tool.execute(code="def foo(")
        assert not r.success

    def test_schema(self):
        tool = CodeExecTool()
        s = tool.to_function_schema()
        assert "code" in s["parameters"]["properties"]


# =============================================================================
# GIT TOOL
# =============================================================================

class TestGitTool:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Init a git repo
        os.system(f"cd {self.tmpdir} && git init -q && git config user.email 'test@test.com' && git config user.name 'Test'")
        self.tool = GitTool()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_status(self):
        r = self.tool.execute(action="status", repo_path=self.tmpdir)
        assert r.success

    def test_init_already(self):
        r = self.tool.execute(action="init", repo_path=self.tmpdir)
        assert r.success

    def test_add_and_commit(self):
        # Create a file
        with open(os.path.join(self.tmpdir, "test.txt"), "w") as f:
            f.write("hello")
        r = self.tool.execute(action="add", args=".", repo_path=self.tmpdir)
        assert r.success

        r = self.tool.execute(action="commit", args="Initial commit", repo_path=self.tmpdir)
        assert r.success

    def test_log_empty_repo(self):
        r = self.tool.execute(action="log", repo_path=self.tmpdir)
        # Empty repo has no commits, git log fails
        assert not r.success

    def test_branch(self):
        # Need at least one commit
        with open(os.path.join(self.tmpdir, "x.txt"), "w") as f:
            f.write("x")
        os.system(f"cd {self.tmpdir} && git add . && git commit -q -m 'init'")
        r = self.tool.execute(action="branch", repo_path=self.tmpdir)
        assert r.success

    def test_diff(self):
        r = self.tool.execute(action="diff", repo_path=self.tmpdir)
        assert r.success

    def test_invalid_repo(self):
        r = self.tool.execute(action="status", repo_path="/nonexistent")
        assert not r.success

    def test_schema(self):
        s = self.tool.to_function_schema()
        assert s["name"] == "git"
        assert "action" in s["parameters"]["properties"]


# =============================================================================
# EMAIL TOOL
# =============================================================================

class TestEmailTool:
    def test_init(self):
        tool = EmailTool()
        assert tool.name == "email"

    def test_send_no_smtp(self):
        tool = EmailTool(context={"config": {}})
        r = tool.execute(action="send", to="test@test.com", subject="hi", body="hello")
        assert not r.success
        assert "not configured" in r.error

    def test_test_no_smtp(self):
        tool = EmailTool(context={"config": {}})
        r = tool.execute(action="test")
        assert not r.success
        assert "not configured" in r.error

    def test_send_missing_to(self):
        tool = EmailTool(context={"config": {"email": {"smtp_host": "localhost"}}})
        r = tool.execute(action="send", subject="hi")
        assert not r.success
        assert "Missing" in r.error

    def test_invalid_email(self):
        tool = EmailTool(context={"config": {"email": {"smtp_host": "localhost"}}})
        r = tool.execute(action="send", to="not-an-email", subject="hi")
        assert not r.success
        assert "Invalid email" in r.error

    def test_schema(self):
        tool = EmailTool()
        s = tool.to_function_schema()
        assert s["name"] == "email"
        assert "action" in s["parameters"]["properties"]
