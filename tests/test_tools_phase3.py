"""
Tests for ARIA Tools - Phase 3
================================
MemoryTool, DownloadTool, SystemInfoTool, PdfTool
"""

import pytest
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tools import MemoryTool, DownloadTool, SystemInfoTool, PdfTool


# =============================================================================
# MEMORY TOOL
# =============================================================================

class TestMemoryTool:
    def test_no_memory_context(self):
        tool = MemoryTool()
        r = tool.execute(query="test")
        assert not r.success
        assert "not available" in r.error

    def test_no_results(self):
        class MockMemory:
            def recall(self, q, limit=5):
                return []
        tool = MemoryTool(context={"memory": MockMemory()})
        r = tool.execute(query="nonexistent")
        assert r.success
        assert "No memories" in r.output

    def test_with_results(self):
        class MockMem:
            content = "William talked about Python"
            timestamp = "2025-12-01T10:00:00"
            involves = ["william"]
            emotional_tone = type("ET", (), {"value": "curious"})()
            tags = ["python", "coding"]

        class MockMemory:
            def recall(self, q, limit=5):
                return [MockMem()]

        tool = MemoryTool(context={"memory": MockMemory()})
        r = tool.execute(query="Python")
        assert r.success
        assert "William talked about Python" in r.output
        assert r.data["count"] == 1

    def test_uses_enhanced_recall(self):
        class MockMemory:
            def recall_enhanced(self, q, limit=5):
                return []
            def recall(self, q, limit=5):
                raise Exception("Should not be called")

        tool = MemoryTool(context={"memory": MockMemory()})
        r = tool.execute(query="test")
        assert r.success

    def test_schema(self):
        s = MemoryTool().to_function_schema()
        assert s["name"] == "memory_search"
        assert "query" in s["parameters"]["properties"]


# =============================================================================
# DOWNLOAD TOOL
# =============================================================================

class TestDownloadTool:
    def test_invalid_url(self):
        tool = DownloadTool()
        r = tool.execute(url="not-a-url")
        assert not r.success

    def test_schema(self):
        s = DownloadTool().to_function_schema()
        assert s["name"] == "download"
        assert "url" in s["parameters"]["properties"]

    def test_auto_filename(self):
        # Just test the tool initializes correctly
        tool = DownloadTool()
        assert tool.name == "download"


# =============================================================================
# SYSTEM INFO TOOL
# =============================================================================

class TestSystemInfoTool:
    def test_overview(self):
        tool = SystemInfoTool()
        r = tool.execute(action="overview")
        assert r.success
        assert "hostname" in r.data or "os" in r.data

    def test_cpu(self):
        tool = SystemInfoTool()
        r = tool.execute(action="cpu")
        assert r.success

    def test_memory(self):
        tool = SystemInfoTool()
        r = tool.execute(action="memory")
        assert r.success

    def test_disk(self):
        tool = SystemInfoTool()
        r = tool.execute(action="disk")
        assert r.success

    def test_processes(self):
        tool = SystemInfoTool()
        r = tool.execute(action="processes", top_n=3)
        assert r.success

    def test_network(self):
        tool = SystemInfoTool()
        r = tool.execute(action="network")
        assert r.success

    def test_schema(self):
        s = SystemInfoTool().to_function_schema()
        assert s["name"] == "system_info"
        assert "action" in s["parameters"]["properties"]


# =============================================================================
# PDF TOOL
# =============================================================================

class TestPdfTool:
    def test_file_not_found(self):
        tool = PdfTool()
        r = tool.execute(path="/nonexistent/file.pdf")
        assert not r.success
        assert "not found" in r.error.lower()

    def test_not_pdf(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".txt", delete=False)
        tmp.write(b"not a pdf")
        tmp.close()
        try:
            tool = PdfTool()
            r = tool.execute(path=tmp.name)
            assert not r.success
            assert "not a PDF" in r.error
        finally:
            os.unlink(tmp.name)

    def test_schema(self):
        s = PdfTool().to_function_schema()
        assert s["name"] == "pdf_read"
        assert "path" in s["parameters"]["properties"]

    def test_page_parse_all(self):
        from core.tools.pdf_tool import _parse_pages
        result = _parse_pages(None, 10)
        assert result == list(range(10))

    def test_page_parse_range(self):
        from core.tools.pdf_tool import _parse_pages
        result = _parse_pages("1-3", 10)
        assert result == [0, 1, 2]

    def test_page_parse_single(self):
        from core.tools.pdf_tool import _parse_pages
        result = _parse_pages("5", 10)
        assert result == [4]

    def test_page_parse_mixed(self):
        from core.tools.pdf_tool import _parse_pages
        result = _parse_pages("1,3,5-7", 10)
        assert result == [0, 2, 4, 5, 6]

    def test_page_parse_out_of_bounds(self):
        from core.tools.pdf_tool import _parse_pages
        result = _parse_pages("99", 10)
        assert isinstance(result, str)  # Error string
