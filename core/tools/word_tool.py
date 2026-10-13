"""
ARIA - Word Tool
=================

Read, create, and modify Word documents (.docx).
Uses python-docx for full document manipulation including
paragraphs, tables, images, headers, styles, and sections.

Actions:
  read      — Read document text content
  create    — Create new document with content
  edit      — Add/modify/delete paragraphs, headings, tables
  info      — Get document metadata (sections, styles, word count)
  add_table — Insert a table
  add_image — Insert an image
  replace   — Find and replace text
  style     — Apply formatting to paragraphs/runs
"""

import logging
import os
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.word")

MAX_TEXT_LENGTH = 200_000


class WordTool(ToolBase):
    """Read, create, and modify Word documents (.docx)."""

    name = "word"
    description = (
        "Work with Word documents (.docx). "
        "Actions: read (extract text), create (new document), edit (add content), "
        "info (metadata), add_table, add_image, replace (find/replace), style. "
        "Use 'read' to inspect, 'create' for new files, 'edit' to modify."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: read, create, edit, info, add_table, add_image, replace, style",
            required=True,
            enum=["read", "create", "edit", "info", "add_table", "add_image", "replace", "style"],
        ),
        ToolParam(
            name="path",
            type="string",
            description="Path to the Word document",
            required=True,
        ),
        ToolParam(
            name="content",
            type="string",
            description=(
                "Text content for create/edit. For create: plain text (paragraphs separated by \\n\\n) "
                "or JSON: {\"title\": \"...\", \"sections\": [{\"heading\": \"...\", \"text\": \"...\"}]}. "
                "For edit: JSON {\"action\": \"append/insert/delete\", \"text\": \"...\", \"position\": 0}"
            ),
            required=False,
        ),
        ToolParam(
            name="data",
            type="string",
            description=(
                "JSON data for add_table: [[\"H1\",\"H2\"],[\"r1c1\",\"r1c2\"]] or "
                "for replace: {\"find\": \"old\", \"replace\": \"new\"} or "
                "for style: {\"bold\": true, \"font_size\": 14, \"font_name\": \"Arial\", \"color\": \"FF0000\", \"align\": \"center\"}"
            ),
            required=False,
        ),
        ToolParam(
            name="image_path",
            type="string",
            description="Path to image file for add_image action",
            required=False,
        ),
        ToolParam(
            name="image_width",
            type="number",
            description="Image width in inches (default: 5.0)",
            required=False,
            default=5.0,
        ),
        ToolParam(
            name="range",
            type="string",
            description="Paragraph index or range for edit/style (e.g. '0', '2-5', 'all'). Default: last/all.",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        try:
            import docx
        except ImportError:
            return ToolResult(success=False, error="python-docx not installed. Run: pip install python-docx")

        action = kwargs["action"]
        dispatch = {
            "read": self._read,
            "create": self._create,
            "edit": self._edit,
            "info": self._info,
            "add_table": self._add_table,
            "add_image": self._add_image,
            "replace": self._replace,
            "style": self._style,
        }

        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(kwargs)

    # -------------------------------------------------------------------------
    # READ
    # -------------------------------------------------------------------------

    def _read(self, kwargs) -> ToolResult:
        import docx

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        doc = docx.Document(path)
        lines = []
        word_count = 0

        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not text:
                continue

            style = para.style.name if para.style else "Normal"
            word_count += len(text.split())

            if "Heading" in style:
                level = style.replace("Heading ", "").strip()
                prefix = "#" * int(level) if level.isdigit() else "#"
                lines.append(f"{prefix} {text}")
            else:
                lines.append(text)

        # Also extract tables
        for t_idx, table in enumerate(doc.tables):
            lines.append(f"\n[Table {t_idx + 1}: {len(table.rows)}×{len(table.columns)}]")
            for r_idx, row in enumerate(table.rows):
                cells = [cell.text.strip()[:40] for cell in row.cells]
                lines.append(f"  {' | '.join(cells)}")
                if r_idx >= 20:
                    lines.append(f"  ... ({len(table.rows) - 20} more rows)")
                    break

        content = "\n".join(lines)
        if len(content) > MAX_TEXT_LENGTH:
            content = content[:MAX_TEXT_LENGTH] + f"\n... [truncated at {MAX_TEXT_LENGTH} chars]"

        return ToolResult(
            success=True,
            output=f"Document: {os.path.basename(path)} ({word_count} words, {len(doc.paragraphs)} paragraphs)\n\n{content}",
            data={
                "word_count": word_count,
                "paragraphs": len(doc.paragraphs),
                "tables": len(doc.tables),
            },
        )

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------

    def _create(self, kwargs) -> ToolResult:
        import json
        import docx

        path = os.path.expanduser(kwargs["path"])
        content = kwargs.get("content", "")

        doc = docx.Document()

        paragraphs_added = 0

        if content:
            # Try JSON format first
            try:
                data = json.loads(content)
                if isinstance(data, dict):
                    # {"title": "...", "sections": [{"heading": "...", "text": "..."}]}
                    if "title" in data:
                        doc.add_heading(data["title"], level=0)
                        paragraphs_added += 1

                    for section in data.get("sections", []):
                        if "heading" in section:
                            level = section.get("level", 1)
                            doc.add_heading(section["heading"], level=level)
                            paragraphs_added += 1
                        if "text" in section:
                            doc.add_paragraph(section["text"])
                            paragraphs_added += 1
                        if "bullets" in section:
                            for bullet in section["bullets"]:
                                doc.add_paragraph(bullet, style="List Bullet")
                                paragraphs_added += 1
                elif isinstance(data, list):
                    for item in data:
                        if isinstance(item, str):
                            doc.add_paragraph(item)
                            paragraphs_added += 1
                        elif isinstance(item, dict):
                            if "heading" in item:
                                doc.add_heading(item["heading"], level=item.get("level", 1))
                            if "text" in item:
                                doc.add_paragraph(item["text"])
                            paragraphs_added += 1
            except (json.JSONDecodeError, TypeError):
                # Plain text: split by double newlines for paragraphs
                for para_text in content.split("\n\n"):
                    para_text = para_text.strip()
                    if para_text:
                        if para_text.startswith("# "):
                            doc.add_heading(para_text[2:], level=1)
                        elif para_text.startswith("## "):
                            doc.add_heading(para_text[3:], level=2)
                        elif para_text.startswith("### "):
                            doc.add_heading(para_text[4:], level=3)
                        else:
                            doc.add_paragraph(para_text)
                        paragraphs_added += 1

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        doc.save(path)

        return ToolResult(
            success=True,
            output=f"Created '{os.path.basename(path)}': {paragraphs_added} paragraphs",
            data={"path": path, "paragraphs": paragraphs_added},
        )

    # -------------------------------------------------------------------------
    # EDIT
    # -------------------------------------------------------------------------

    def _edit(self, kwargs) -> ToolResult:
        import json
        import docx

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        content = kwargs.get("content")
        if not content:
            return ToolResult(success=False, error="'content' is required for edit")

        doc = docx.Document(path)

        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            # Simple text: append as paragraph
            doc.add_paragraph(content)
            doc.save(path)
            return ToolResult(success=True, output=f"Appended paragraph to '{os.path.basename(path)}'")

        edit_action = data.get("action", "append")

        if edit_action == "append":
            text = data.get("text", "")
            heading = data.get("heading")
            if heading:
                doc.add_heading(heading, level=data.get("level", 1))
            if text:
                doc.add_paragraph(text)
            doc.save(path)
            return ToolResult(success=True, output=f"Appended content to '{os.path.basename(path)}'")

        elif edit_action == "insert":
            position = data.get("position", 0)
            text = data.get("text", "")
            # Insert before position by manipulating XML
            if position < len(doc.paragraphs):
                ref_para = doc.paragraphs[position]
                new_para = docx.oxml.OxmlElement("w:p")
                run = docx.oxml.OxmlElement("w:r")
                t = docx.oxml.OxmlElement("w:t")
                t.text = text
                run.append(t)
                new_para.append(run)
                ref_para._element.addprevious(new_para)
            else:
                doc.add_paragraph(text)
            doc.save(path)
            return ToolResult(success=True, output=f"Inserted paragraph at position {position}")

        elif edit_action == "delete":
            position = data.get("position", -1)
            if position < 0:
                position = len(doc.paragraphs) + position
            if 0 <= position < len(doc.paragraphs):
                para = doc.paragraphs[position]
                para._element.getparent().remove(para._element)
                doc.save(path)
                return ToolResult(success=True, output=f"Deleted paragraph at position {position}")
            return ToolResult(success=False, error=f"Position {position} out of range (0-{len(doc.paragraphs) - 1})")

        return ToolResult(success=False, error=f"Unknown edit action: {edit_action}. Use: append, insert, delete")

    # -------------------------------------------------------------------------
    # INFO
    # -------------------------------------------------------------------------

    def _info(self, kwargs) -> ToolResult:
        import docx

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        file_size = os.path.getsize(path)
        doc = docx.Document(path)

        word_count = sum(len(p.text.split()) for p in doc.paragraphs)
        char_count = sum(len(p.text) for p in doc.paragraphs)

        # Styles used
        styles_used = set()
        for p in doc.paragraphs:
            if p.style:
                styles_used.add(p.style.name)

        # Core properties
        props = doc.core_properties
        meta = {}
        for attr in ["author", "title", "subject", "keywords", "created", "modified"]:
            val = getattr(props, attr, None)
            if val:
                meta[attr] = str(val)

        lines = [
            f"File: {os.path.basename(path)} ({file_size / 1024:.1f} KB)",
            f"Words: {word_count} | Characters: {char_count}",
            f"Paragraphs: {len(doc.paragraphs)} | Tables: {len(doc.tables)}",
            f"Sections: {len(doc.sections)} | Images: {len(doc.inline_shapes)}",
            f"Styles used: {', '.join(sorted(styles_used)) or 'none'}",
        ]

        if meta:
            lines.append("Metadata:")
            for k, v in meta.items():
                lines.append(f"  {k}: {v}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "word_count": word_count,
                "paragraphs": len(doc.paragraphs),
                "tables": len(doc.tables),
                "sections": len(doc.sections),
                "metadata": meta,
            },
        )

    # -------------------------------------------------------------------------
    # ADD TABLE
    # -------------------------------------------------------------------------

    def _add_table(self, kwargs) -> ToolResult:
        import json
        import docx

        path = os.path.expanduser(kwargs["path"])
        data_str = kwargs.get("data")
        if not data_str:
            return ToolResult(success=False, error="'data' is required: [[\"H1\",\"H2\"],[\"r1c1\",\"r1c2\"]]")

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON: {e}")

        if not isinstance(data, list) or not data:
            return ToolResult(success=False, error="Data must be a list of rows: [[col1, col2], ...]")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        doc = docx.Document(path)

        cols = max(len(row) if isinstance(row, list) else 1 for row in data)
        table = doc.add_table(rows=len(data), cols=cols, style="Table Grid")

        for r_idx, row in enumerate(data):
            cells = row if isinstance(row, list) else [row]
            for c_idx, val in enumerate(cells):
                if c_idx < cols:
                    table.rows[r_idx].cells[c_idx].text = str(val)

        # Bold the header row
        for cell in table.rows[0].cells:
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    run.bold = True

        doc.save(path)

        return ToolResult(
            success=True,
            output=f"Added table ({len(data)}×{cols}) to '{os.path.basename(path)}'",
            data={"rows": len(data), "cols": cols},
        )

    # -------------------------------------------------------------------------
    # ADD IMAGE
    # -------------------------------------------------------------------------

    def _add_image(self, kwargs) -> ToolResult:
        import docx
        from docx.shared import Inches

        path = os.path.expanduser(kwargs["path"])
        image_path = kwargs.get("image_path")
        if not image_path:
            return ToolResult(success=False, error="'image_path' is required for add_image")

        image_path = os.path.expanduser(image_path)
        if not os.path.isfile(image_path):
            return ToolResult(success=False, error=f"Image not found: {image_path}")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"Document not found: {path}")

        doc = docx.Document(path)
        width = Inches(kwargs.get("image_width", 5.0))
        doc.add_picture(image_path, width=width)
        doc.save(path)

        return ToolResult(
            success=True,
            output=f"Added image '{os.path.basename(image_path)}' to '{os.path.basename(path)}'",
        )

    # -------------------------------------------------------------------------
    # REPLACE
    # -------------------------------------------------------------------------

    def _replace(self, kwargs) -> ToolResult:
        import json
        import docx

        path = os.path.expanduser(kwargs["path"])
        data_str = kwargs.get("data")
        if not data_str:
            return ToolResult(success=False, error="'data' is required: {\"find\": \"old\", \"replace\": \"new\"}")

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON: {e}")

        find_text = data.get("find", "")
        replace_text = data.get("replace", "")
        if not find_text:
            return ToolResult(success=False, error="'find' text is required")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        doc = docx.Document(path)
        count = 0

        for para in doc.paragraphs:
            if find_text in para.text:
                for run in para.runs:
                    if find_text in run.text:
                        run.text = run.text.replace(find_text, replace_text)
                        count += 1

        # Also check table cells
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        if find_text in para.text:
                            for run in para.runs:
                                if find_text in run.text:
                                    run.text = run.text.replace(find_text, replace_text)
                                    count += 1

        doc.save(path)

        return ToolResult(
            success=True,
            output=f"Replaced {count} occurrences of '{find_text}' with '{replace_text}'",
            data={"replacements": count},
        )

    # -------------------------------------------------------------------------
    # STYLE
    # -------------------------------------------------------------------------

    def _style(self, kwargs) -> ToolResult:
        import json
        import docx
        from docx.shared import Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        path = os.path.expanduser(kwargs["path"])
        data_str = kwargs.get("data")
        para_range = kwargs.get("range", "all")

        if not data_str:
            return ToolResult(success=False, error="'data' JSON style is required")

        try:
            style = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid style JSON: {e}")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        doc = docx.Document(path)

        # Parse range
        if para_range == "all":
            indices = list(range(len(doc.paragraphs)))
        elif "-" in para_range:
            start, end = para_range.split("-", 1)
            indices = list(range(int(start), int(end) + 1))
        else:
            indices = [int(para_range)]

        align_map = {
            "left": WD_ALIGN_PARAGRAPH.LEFT,
            "center": WD_ALIGN_PARAGRAPH.CENTER,
            "right": WD_ALIGN_PARAGRAPH.RIGHT,
            "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
        }

        styled = 0
        for idx in indices:
            if idx >= len(doc.paragraphs):
                continue
            para = doc.paragraphs[idx]

            if "align" in style:
                para.alignment = align_map.get(style["align"], WD_ALIGN_PARAGRAPH.LEFT)

            for run in para.runs:
                if "bold" in style:
                    run.bold = style["bold"]
                if "italic" in style:
                    run.italic = style["italic"]
                if "underline" in style:
                    run.underline = style["underline"]
                if "font_size" in style:
                    run.font.size = Pt(style["font_size"])
                if "font_name" in style:
                    run.font.name = style["font_name"]
                if "color" in style:
                    hex_color = style["color"].lstrip("#")
                    run.font.color.rgb = RGBColor(
                        int(hex_color[0:2], 16),
                        int(hex_color[2:4], 16),
                        int(hex_color[4:6], 16),
                    )

            styled += 1

        doc.save(path)

        return ToolResult(
            success=True,
            output=f"Styled {styled} paragraphs in '{os.path.basename(path)}'",
            data={"paragraphs_styled": styled},
        )
