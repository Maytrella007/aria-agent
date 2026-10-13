"""
ARIA - PDF Tool
================

Read and extract text from PDF files.
Inspired by OpenClaw's pdf_tool.
Uses PyPDF2 for extraction, can pass to LLM for analysis.
"""

import logging
import os
from typing import Any, Dict, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.pdf")

try:
    from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False

MAX_PAGES = 50
MAX_TEXT_LENGTH = 100_000


class PdfTool(ToolBase):
    """Read and extract text from PDF files."""

    name = "pdf_read"
    description = (
        "Read and extract text from a PDF file. "
        "Returns the text content, page count, and metadata. "
        "Use for reading documents, contracts, papers, reports, etc. "
        "Specify page range to read only specific pages."
    )
    parameters = [
        ToolParam(
            name="path",
            type="string",
            description="Path to the PDF file",
            required=True,
        ),
        ToolParam(
            name="pages",
            type="string",
            description="Page range to read, e.g. '1-5', '3', '1,3,5-10' (default: all)",
            required=False,
        ),
        ToolParam(
            name="max_chars",
            type="integer",
            description=f"Max characters to return (default: {MAX_TEXT_LENGTH})",
            required=False,
            default=MAX_TEXT_LENGTH,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        if not PYPDF2_AVAILABLE:
            return ToolResult(success=False, error="PyPDF2 not installed. Run: pip install PyPDF2")

        path = os.path.expanduser(kwargs["path"])
        pages_str = kwargs.get("pages")
        max_chars = kwargs.get("max_chars", MAX_TEXT_LENGTH)

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        if not path.lower().endswith(".pdf"):
            return ToolResult(success=False, error="File is not a PDF")

        try:
            reader = PdfReader(path)
            total_pages = len(reader.pages)

            # Parse page range
            page_indices = _parse_pages(pages_str, total_pages)
            if isinstance(page_indices, str):
                return ToolResult(success=False, error=page_indices)

            # Limit pages
            if len(page_indices) > MAX_PAGES:
                page_indices = page_indices[:MAX_PAGES]

            # Extract text
            texts = []
            for i in page_indices:
                page = reader.pages[i]
                text = page.extract_text() or ""
                if text.strip():
                    texts.append(f"--- Page {i + 1} ---\n{text.strip()}")

            full_text = "\n\n".join(texts)
            truncated = len(full_text) > max_chars
            if truncated:
                full_text = full_text[:max_chars] + "\n\n[... truncated]"

            # Metadata
            meta = {}
            if reader.metadata:
                for key in ("title", "author", "subject", "creator"):
                    val = getattr(reader.metadata, key, None)
                    if val:
                        meta[key] = str(val)

            if not full_text.strip():
                full_text = "(No extractable text — PDF may contain only images/scans)"

            lines = [f"PDF: {os.path.basename(path)}"]
            lines.append(f"Pages: {total_pages} total, {len(page_indices)} read")
            if meta:
                for k, v in meta.items():
                    lines.append(f"{k.title()}: {v}")
            lines.append("")
            lines.append(full_text)

            return ToolResult(
                success=True,
                output="\n".join(lines),
                data={
                    "path": path,
                    "total_pages": total_pages,
                    "pages_read": len(page_indices),
                    "text_length": len(full_text),
                    "truncated": truncated,
                    "metadata": meta,
                },
            )

        except Exception as e:
            return ToolResult(success=False, error=f"Failed to read PDF: {e}")


def _parse_pages(pages_str: Optional[str], total: int) -> list | str:
    """Parse page range string. Returns list of 0-indexed page numbers or error string."""
    if not pages_str:
        return list(range(total))

    indices = set()
    for part in pages_str.split(","):
        part = part.strip()
        if "-" in part:
            try:
                start, end = part.split("-", 1)
                start = int(start.strip()) - 1
                end = int(end.strip()) - 1
                if start < 0 or end >= total:
                    return f"Page range {part} out of bounds (1-{total})"
                indices.update(range(start, end + 1))
            except ValueError:
                return f"Invalid page range: {part}"
        else:
            try:
                p = int(part) - 1
                if p < 0 or p >= total:
                    return f"Page {part} out of bounds (1-{total})"
                indices.add(p)
            except ValueError:
                return f"Invalid page number: {part}"

    return sorted(indices)
