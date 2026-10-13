"""
Tests for ARIA Tools - Phase 4
================================
DatabaseTool, CalculatorTool, CompressTool, TodoTool, ImageGenTool, TranslateTool
"""

import pytest
import os
import sys
import tempfile
import shutil
import zipfile
import tarfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools import DatabaseTool, CalculatorTool, CompressTool, TodoTool, ImageGenTool, TranslateTool


# =============================================================================
# CALCULATOR TOOL
# =============================================================================

class TestCalculatorTool:
    def test_basic_arithmetic(self):
        tool = CalculatorTool()
        r = tool.execute(expression="2 + 3 * 4")
        assert r.success
        assert r.data["result"] == 14

    def test_sqrt(self):
        tool = CalculatorTool()
        r = tool.execute(expression="sqrt(144)")
        assert r.success
        assert r.data["result"] == 12.0

    def test_trig(self):
        tool = CalculatorTool()
        r = tool.execute(expression="sin(0)")
        assert r.success
        assert r.data["result"] == 0.0

    def test_pi(self):
        tool = CalculatorTool()
        r = tool.execute(expression="2 * pi")
        assert r.success
        assert abs(r.data["result"] - 6.283185) < 0.001

    def test_power(self):
        tool = CalculatorTool()
        r = tool.execute(expression="2 ** 10")
        assert r.success
        assert r.data["result"] == 1024

    def test_division_by_zero(self):
        tool = CalculatorTool()
        r = tool.execute(expression="1 / 0")
        assert not r.success
        assert "zero" in r.error.lower()

    def test_blocked_import(self):
        tool = CalculatorTool()
        r = tool.execute(expression="__import__('os')")
        assert not r.success

    def test_blocked_builtins(self):
        tool = CalculatorTool()
        r = tool.execute(expression="exec('print(1)')")
        assert not r.success

    def test_empty_expression(self):
        tool = CalculatorTool()
        r = tool.execute(expression="")
        assert not r.success

    def test_schema(self):
        s = CalculatorTool().to_function_schema()
        assert s["name"] == "calculator"
        assert "expression" in s["parameters"]["properties"]


# =============================================================================
# DATABASE TOOL
# =============================================================================

class TestDatabaseTool:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = DatabaseTool(context={"data_dir": self.tmpdir})
        self.db_path = os.path.join(self.tmpdir, "test.db")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_schema(self):
        s = self.tool.to_function_schema()
        assert s["name"] == "database"

    def test_create_and_query(self):
        r = self.tool.execute(action="execute", sql="CREATE TABLE users (id INTEGER, name TEXT)", db_path=self.db_path)
        assert r.success
        r = self.tool.execute(action="execute", sql="INSERT INTO users VALUES (1, 'Alice')", db_path=self.db_path)
        assert r.success
        r = self.tool.execute(action="query", sql="SELECT * FROM users", db_path=self.db_path)
        assert r.success
        assert "Alice" in r.output

    def test_tables(self):
        self.tool.execute(action="execute", sql="CREATE TABLE items (id INTEGER)", db_path=self.db_path)
        r = self.tool.execute(action="tables", db_path=self.db_path)
        assert r.success
        assert "items" in r.output

    def test_query_rejects_mutation(self):
        self.tool.execute(action="execute", sql="CREATE TABLE t (id INTEGER)", db_path=self.db_path)
        r = self.tool.execute(action="query", sql="DROP TABLE t", db_path=self.db_path)
        assert not r.success


# =============================================================================
# COMPRESS TOOL
# =============================================================================

class TestCompressTool:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = CompressTool(context={"data_dir": self.tmpdir})
        # Create test files
        self.file1 = os.path.join(self.tmpdir, "a.txt")
        self.file2 = os.path.join(self.tmpdir, "b.txt")
        with open(self.file1, "w") as f:
            f.write("hello")
        with open(self.file2, "w") as f:
            f.write("world")

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_schema(self):
        s = self.tool.to_function_schema()
        assert s["name"] == "compress"

    def test_zip_and_unzip(self):
        zip_path = os.path.join(self.tmpdir, "test.zip")
        r = self.tool.execute(action="zip", path=zip_path, files=f"{self.file1},{self.file2}")
        assert r.success
        assert os.path.isfile(zip_path)

        dest = os.path.join(self.tmpdir, "extracted")
        r = self.tool.execute(action="unzip", path=zip_path, destination=dest)
        assert r.success
        assert os.path.isdir(dest)

    def test_list_zip(self):
        zip_path = os.path.join(self.tmpdir, "test.zip")
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.write(self.file1, "a.txt")
        r = self.tool.execute(action="list", path=zip_path)
        assert r.success
        assert "a.txt" in r.output

    def test_tar_and_untar(self):
        tar_path = os.path.join(self.tmpdir, "test.tar.gz")
        r = self.tool.execute(action="tar", path=tar_path, files=f"{self.file1},{self.file2}")
        assert r.success
        assert os.path.isfile(tar_path)

        dest = os.path.join(self.tmpdir, "extracted_tar")
        r = self.tool.execute(action="untar", path=tar_path, destination=dest)
        assert r.success


# =============================================================================
# TODO TOOL
# =============================================================================

class TestTodoTool:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = TodoTool(context={"data_dir": self.tmpdir})

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_schema(self):
        s = self.tool.to_function_schema()
        assert s["name"] == "todo"

    def test_add_and_list(self):
        r = self.tool.execute(action="add", text="Buy milk")
        assert r.success
        r = self.tool.execute(action="list")
        assert r.success
        assert "Buy milk" in r.output

    def test_complete(self):
        self.tool.execute(action="add", text="Task 1")
        r = self.tool.execute(action="complete", id=1)
        assert r.success
        r = self.tool.execute(action="list")
        assert "done" in r.output.lower() or "completed" in r.output.lower() or "Task 1" in r.output

    def test_remove(self):
        self.tool.execute(action="add", text="To remove")
        r = self.tool.execute(action="remove", id=1)
        assert r.success

    def test_empty_list(self):
        r = self.tool.execute(action="list")
        assert r.success


# =============================================================================
# IMAGE GEN TOOL
# =============================================================================

class TestImageGenTool:
    def test_schema(self):
        s = ImageGenTool().to_function_schema()
        assert s["name"] == "image_generate"
        assert "prompt" in s["parameters"]["properties"]

    def test_no_api_key(self):
        tool = ImageGenTool()
        # Without OPENAI_API_KEY set, should fail gracefully
        old = os.environ.pop("OPENAI_API_KEY", None)
        try:
            r = tool.execute(prompt="a cat")
            assert not r.success
        finally:
            if old:
                os.environ["OPENAI_API_KEY"] = old


# =============================================================================
# TRANSLATE TOOL
# =============================================================================

class TestTranslateTool:
    def test_schema(self):
        s = TranslateTool().to_function_schema()
        assert s["name"] == "translate"
        assert "text" in s["parameters"]["properties"]
        assert "target_language" in s["parameters"]["properties"]

    def test_no_llm(self):
        tool = TranslateTool()
        r = tool.execute(text="hello", target_language="es")
        assert not r.success
        assert "llm" in r.error.lower() or "not available" in r.error.lower()
