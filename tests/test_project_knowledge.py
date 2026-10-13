"""
Tests for ProjectKnowledgeTool
"""

import pytest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools import ProjectKnowledgeTool


class TestProjectKnowledgeTool:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tool = ProjectKnowledgeTool(context={"data_dir": self.tmpdir})

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_schema(self):
        s = self.tool.to_function_schema()
        assert s["name"] == "project_knowledge"
        assert "action" in s["parameters"]["properties"]

    def test_save_decision(self):
        r = self.tool.execute(action="save", content="Use PostgreSQL", category="decision")
        assert r.success
        assert "decision" in r.output
        assert r.data["total_memories"] == 1

    def test_save_pattern(self):
        r = self.tool.execute(action="save", content="Repository pattern for DB access", category="pattern")
        assert r.success
        assert "pattern" in r.output

    def test_save_requires_content(self):
        r = self.tool.execute(action="save")
        assert not r.success
        assert "content" in r.error

    def test_recall_empty(self):
        r = self.tool.execute(action="recall", query="anything")
        assert r.success
        assert r.data["count"] == 0

    def test_recall_with_results(self):
        self.tool.execute(action="save", content="Use Redis for caching", category="decision")
        self.tool.execute(action="save", content="Factory pattern for services", category="pattern")
        r = self.tool.execute(action="recall", query="redis")
        assert r.success
        assert r.data["count"] == 1
        assert "Redis" in r.output

    def test_recall_all(self):
        self.tool.execute(action="save", content="Item 1", category="context")
        self.tool.execute(action="save", content="Item 2", category="context")
        r = self.tool.execute(action="recall")
        assert r.success
        assert r.data["count"] == 2

    def test_summary_empty(self):
        r = self.tool.execute(action="summary")
        assert r.success
        assert "No project knowledge" in r.output

    def test_summary_with_data(self):
        self.tool.execute(action="save", content="Decision 1", category="decision")
        self.tool.execute(action="save", content="Pattern 1", category="pattern")
        r = self.tool.execute(action="summary")
        assert r.success
        assert r.data["total"] == 2
        assert "decision" in r.data["categories"]

    def test_set_preference(self):
        r = self.tool.execute(action="set_preference", key="indent", value="4_spaces")
        assert r.success
        assert "indent" in r.output

    def test_set_preference_requires_both(self):
        r = self.tool.execute(action="set_preference", key="indent")
        assert not r.success

    def test_preference_in_summary(self):
        self.tool.execute(action="set_preference", key="style", value="black")
        r = self.tool.execute(action="summary")
        assert "style" in r.output
        assert "black" in r.output

    def test_persistence(self):
        self.tool.execute(action="save", content="Persistent item", category="decision")
        # Create new tool pointing to same dir
        tool2 = ProjectKnowledgeTool(context={"data_dir": self.tmpdir})
        r = tool2.execute(action="recall", query="persistent")
        assert r.data["count"] == 1

    def test_unknown_action(self):
        r = self.tool.execute(action="invalid")
        assert not r.success
