"""
ARIA - PowerPoint Tool
=======================

Read, create, and modify PowerPoint presentations (.pptx).
Uses python-pptx for full presentation manipulation including
slides, text, images, shapes, charts, layouts, and transitions.

Actions:
  read        — Read slide content (text and structure)
  create      — Create new presentation with slides
  add_slide   — Add a slide to existing presentation
  edit_slide  — Modify text/content on a slide
  delete_slide — Remove a slide
  add_image   — Insert image into a slide
  add_chart   — Insert chart into a slide
  info        — Get presentation metadata
"""

import logging
import os
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.powerpoint")


class PowerPointTool(ToolBase):
    """Read, create, and modify PowerPoint presentations (.pptx)."""

    name = "powerpoint"
    description = (
        "Work with PowerPoint presentations (.pptx). "
        "Actions: read (extract text), create (new presentation), "
        "add_slide (append slide), edit_slide (modify content), "
        "delete_slide, add_image, add_chart, info (metadata). "
        "Use 'read' to inspect, 'create' for new files, 'add_slide'/'edit_slide' to modify."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: read, create, add_slide, edit_slide, delete_slide, add_image, add_chart, info",
            required=True,
            enum=["read", "create", "add_slide", "edit_slide", "delete_slide", "add_image", "add_chart", "info"],
        ),
        ToolParam(
            name="path",
            type="string",
            description="Path to the PowerPoint file",
            required=True,
        ),
        ToolParam(
            name="slide_num",
            type="integer",
            description="Slide number (1-based) for edit_slide/delete_slide/add_image/add_chart",
            required=False,
        ),
        ToolParam(
            name="title",
            type="string",
            description="Slide title for add_slide/edit_slide",
            required=False,
        ),
        ToolParam(
            name="content",
            type="string",
            description=(
                "Slide body text for add_slide/edit_slide. Use \\n for bullet points. "
                "For create: JSON array of slides [{\"title\": \"...\", \"content\": \"...\", \"layout\": \"title_and_content\"}]"
            ),
            required=False,
        ),
        ToolParam(
            name="layout",
            type="string",
            description=(
                "Slide layout: title_slide, title_and_content, section_header, "
                "two_content, blank, content_with_caption (default: title_and_content)"
            ),
            required=False,
            enum=["title_slide", "title_and_content", "section_header", "two_content", "blank", "content_with_caption"],
            default="title_and_content",
        ),
        ToolParam(
            name="image_path",
            type="string",
            description="Path to image file for add_image",
            required=False,
        ),
        ToolParam(
            name="data",
            type="string",
            description=(
                "JSON data for add_chart: "
                "{\"type\": \"bar\", \"categories\": [\"A\",\"B\"], \"series\": [{\"name\": \"S1\", \"values\": [10,20]}]}"
            ),
            required=False,
        ),
    ]

    # Layout name → index mapping (standard PowerPoint layouts)
    LAYOUT_MAP = {
        "title_slide": 0,
        "title_and_content": 1,
        "section_header": 2,
        "two_content": 3,
        "blank": 6,
        "content_with_caption": 7,
    }

    def _execute(self, **kwargs) -> ToolResult:
        try:
            import pptx
        except ImportError:
            return ToolResult(success=False, error="python-pptx not installed. Run: pip install python-pptx")

        action = kwargs["action"]
        dispatch = {
            "read": self._read,
            "create": self._create,
            "add_slide": self._add_slide,
            "edit_slide": self._edit_slide,
            "delete_slide": self._delete_slide,
            "add_image": self._add_image,
            "add_chart": self._add_chart,
            "info": self._info,
        }

        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(kwargs)

    # -------------------------------------------------------------------------
    # Helper: get layout
    # -------------------------------------------------------------------------

    def _get_layout(self, prs, layout_name: str):
        """Get slide layout by name, with fallback."""
        idx = self.LAYOUT_MAP.get(layout_name, 1)
        try:
            return prs.slide_layouts[idx]
        except (IndexError, KeyError):
            # Fallback to first available
            return prs.slide_layouts[0]

    def _set_slide_content(self, slide, title: str = None, content: str = None):
        """Set title and body content on a slide."""
        if title:
            if slide.shapes.title:
                slide.shapes.title.text = title
            else:
                # Add title as textbox
                from pptx.util import Inches, Pt
                txBox = slide.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(9), Inches(1))
                tf = txBox.text_frame
                tf.text = title
                tf.paragraphs[0].font.size = Pt(28)
                tf.paragraphs[0].font.bold = True

        if content:
            # Find body placeholder
            body_placeholder = None
            for shape in slide.placeholders:
                if shape.placeholder_format.idx == 1:  # Body
                    body_placeholder = shape
                    break

            if body_placeholder and body_placeholder.has_text_frame:
                tf = body_placeholder.text_frame
                tf.clear()
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if i == 0:
                        tf.paragraphs[0].text = line.strip()
                    else:
                        p = tf.add_paragraph()
                        p.text = line.strip()
            else:
                # Add as textbox
                from pptx.util import Inches
                txBox = slide.shapes.add_textbox(Inches(0.5), Inches(1.5), Inches(9), Inches(5))
                tf = txBox.text_frame
                tf.word_wrap = True
                lines = content.split("\n")
                for i, line in enumerate(lines):
                    if i == 0:
                        tf.paragraphs[0].text = line.strip()
                    else:
                        p = tf.add_paragraph()
                        p.text = line.strip()

    # -------------------------------------------------------------------------
    # READ
    # -------------------------------------------------------------------------

    def _read(self, kwargs) -> ToolResult:
        from pptx import Presentation

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        prs = Presentation(path)
        lines = [f"Presentation: {os.path.basename(path)} ({len(prs.slides)} slides)\n"]

        for i, slide in enumerate(prs.slides, 1):
            layout_name = slide.slide_layout.name if slide.slide_layout else "Unknown"
            lines.append(f"--- Slide {i} ({layout_name}) ---")

            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if text:
                            if shape.shape_id == 0 or (shape == slide.shapes.title if slide.shapes.title else False):
                                lines.append(f"  [Title] {text}")
                            else:
                                lines.append(f"  {text}")

                if shape.has_table:
                    table = shape.table
                    lines.append(f"  [Table {len(table.rows)}x{len(table.columns)}]")
                    for row in table.rows:
                        cells = [cell.text.strip()[:30] for cell in row.cells]
                        lines.append(f"    {' | '.join(cells)}")

                if shape.shape_type == 13:  # Picture
                    lines.append(f"  [Image: {shape.width}x{shape.height}]")

            lines.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"slides": len(prs.slides)},
        )

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------

    def _create(self, kwargs) -> ToolResult:
        import json
        from pptx import Presentation

        path = os.path.expanduser(kwargs["path"])
        content = kwargs.get("content", "")
        title = kwargs.get("title", "")

        prs = Presentation()
        slides_created = 0

        if content:
            try:
                data = json.loads(content)
                if isinstance(data, list):
                    for slide_data in data:
                        layout_name = slide_data.get("layout", "title_and_content")
                        layout = self._get_layout(prs, layout_name)
                        slide = prs.slides.add_slide(layout)
                        self._set_slide_content(
                            slide,
                            title=slide_data.get("title"),
                            content=slide_data.get("content"),
                        )
                        slides_created += 1
                elif isinstance(data, dict):
                    layout = self._get_layout(prs, data.get("layout", "title_slide"))
                    slide = prs.slides.add_slide(layout)
                    self._set_slide_content(slide, title=data.get("title"), content=data.get("content"))
                    slides_created += 1
            except (json.JSONDecodeError, TypeError):
                # Plain text: create title slide + content slide
                if title:
                    layout = self._get_layout(prs, "title_slide")
                    slide = prs.slides.add_slide(layout)
                    self._set_slide_content(slide, title=title, content=content)
                    slides_created += 1
                else:
                    # Split by --- for multiple slides
                    slide_texts = content.split("---")
                    for text in slide_texts:
                        text = text.strip()
                        if text:
                            lines = text.split("\n", 1)
                            s_title = lines[0].strip()
                            s_body = lines[1].strip() if len(lines) > 1 else ""
                            layout = self._get_layout(prs, "title_and_content")
                            slide = prs.slides.add_slide(layout)
                            self._set_slide_content(slide, title=s_title, content=s_body)
                            slides_created += 1
        elif title:
            layout = self._get_layout(prs, "title_slide")
            slide = prs.slides.add_slide(layout)
            self._set_slide_content(slide, title=title)
            slides_created += 1

        if slides_created == 0:
            # Create at least a blank title slide
            layout = self._get_layout(prs, "title_slide")
            slide = prs.slides.add_slide(layout)
            self._set_slide_content(slide, title="New Presentation")
            slides_created = 1

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        prs.save(path)

        return ToolResult(
            success=True,
            output=f"Created '{os.path.basename(path)}': {slides_created} slides",
            data={"path": path, "slides": slides_created},
        )

    # -------------------------------------------------------------------------
    # ADD SLIDE
    # -------------------------------------------------------------------------

    def _add_slide(self, kwargs) -> ToolResult:
        from pptx import Presentation

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        prs = Presentation(path)
        layout_name = kwargs.get("layout", "title_and_content")
        layout = self._get_layout(prs, layout_name)
        slide = prs.slides.add_slide(layout)

        self._set_slide_content(
            slide,
            title=kwargs.get("title"),
            content=kwargs.get("content"),
        )

        prs.save(path)
        slide_num = len(prs.slides)

        return ToolResult(
            success=True,
            output=f"Added slide {slide_num} ({layout_name}) to '{os.path.basename(path)}'",
            data={"slide_num": slide_num, "total_slides": slide_num},
        )

    # -------------------------------------------------------------------------
    # EDIT SLIDE
    # -------------------------------------------------------------------------

    def _edit_slide(self, kwargs) -> ToolResult:
        from pptx import Presentation

        path = os.path.expanduser(kwargs["path"])
        slide_num = kwargs.get("slide_num")
        if not slide_num:
            return ToolResult(success=False, error="'slide_num' is required for edit_slide")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        prs = Presentation(path)
        if slide_num < 1 or slide_num > len(prs.slides):
            return ToolResult(success=False, error=f"Slide {slide_num} out of range (1-{len(prs.slides)})")

        slide = prs.slides[slide_num - 1]
        self._set_slide_content(
            slide,
            title=kwargs.get("title"),
            content=kwargs.get("content"),
        )

        prs.save(path)

        return ToolResult(
            success=True,
            output=f"Updated slide {slide_num} in '{os.path.basename(path)}'",
            data={"slide_num": slide_num},
        )

    # -------------------------------------------------------------------------
    # DELETE SLIDE
    # -------------------------------------------------------------------------

    def _delete_slide(self, kwargs) -> ToolResult:
        from pptx import Presentation
        import copy

        path = os.path.expanduser(kwargs["path"])
        slide_num = kwargs.get("slide_num")
        if not slide_num:
            return ToolResult(success=False, error="'slide_num' is required for delete_slide")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        prs = Presentation(path)
        if slide_num < 1 or slide_num > len(prs.slides):
            return ToolResult(success=False, error=f"Slide {slide_num} out of range (1-{len(prs.slides)})")

        if len(prs.slides) <= 1:
            return ToolResult(success=False, error="Cannot delete the last slide")

        # Delete by removing the XML element
        rId = prs.slides._sldIdLst[slide_num - 1].get("r:id") if hasattr(prs.slides, '_sldIdLst') else None
        slide_element = prs.slides._sldIdLst[slide_num - 1]
        prs.slides._sldIdLst.remove(slide_element)

        prs.save(path)

        return ToolResult(
            success=True,
            output=f"Deleted slide {slide_num}. Remaining: {len(prs.slides)} slides",
            data={"deleted": slide_num, "remaining": len(prs.slides)},
        )

    # -------------------------------------------------------------------------
    # ADD IMAGE
    # -------------------------------------------------------------------------

    def _add_image(self, kwargs) -> ToolResult:
        from pptx import Presentation
        from pptx.util import Inches

        path = os.path.expanduser(kwargs["path"])
        slide_num = kwargs.get("slide_num")
        image_path = kwargs.get("image_path")

        if not slide_num:
            return ToolResult(success=False, error="'slide_num' is required")
        if not image_path:
            return ToolResult(success=False, error="'image_path' is required")

        image_path = os.path.expanduser(image_path)
        if not os.path.isfile(image_path):
            return ToolResult(success=False, error=f"Image not found: {image_path}")
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"Presentation not found: {path}")

        prs = Presentation(path)
        if slide_num < 1 or slide_num > len(prs.slides):
            return ToolResult(success=False, error=f"Slide {slide_num} out of range")

        slide = prs.slides[slide_num - 1]
        # Center the image on the slide
        slide_width = prs.slide_width
        slide_height = prs.slide_height
        img_width = Inches(6)
        left = (slide_width - img_width) // 2
        top = Inches(1.5)

        slide.shapes.add_picture(image_path, left, top, width=img_width)
        prs.save(path)

        return ToolResult(
            success=True,
            output=f"Added image to slide {slide_num} in '{os.path.basename(path)}'",
            data={"slide_num": slide_num, "image": os.path.basename(image_path)},
        )

    # -------------------------------------------------------------------------
    # ADD CHART
    # -------------------------------------------------------------------------

    def _add_chart(self, kwargs) -> ToolResult:
        import json
        from pptx import Presentation
        from pptx.util import Inches
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_CHART_TYPE

        path = os.path.expanduser(kwargs["path"])
        slide_num = kwargs.get("slide_num")
        data_str = kwargs.get("data")

        if not slide_num:
            return ToolResult(success=False, error="'slide_num' is required")
        if not data_str:
            return ToolResult(
                success=False,
                error="'data' JSON required: {\"type\": \"bar\", \"categories\": [...], \"series\": [{\"name\": \"...\", \"values\": [...]}]}",
            )

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON: {e}")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        prs = Presentation(path)
        if slide_num < 1 or slide_num > len(prs.slides):
            return ToolResult(success=False, error=f"Slide {slide_num} out of range")

        chart_type_map = {
            "bar": XL_CHART_TYPE.COLUMN_CLUSTERED,
            "bar_stacked": XL_CHART_TYPE.COLUMN_STACKED,
            "line": XL_CHART_TYPE.LINE,
            "pie": XL_CHART_TYPE.PIE,
            "area": XL_CHART_TYPE.AREA,
            "scatter": XL_CHART_TYPE.XY_SCATTER,
        }

        ct = data.get("type", "bar")
        chart_type = chart_type_map.get(ct, XL_CHART_TYPE.COLUMN_CLUSTERED)

        chart_data = CategoryChartData()
        chart_data.categories = data.get("categories", [])

        for series in data.get("series", []):
            chart_data.add_series(series.get("name", "Series"), series.get("values", []))

        slide = prs.slides[slide_num - 1]
        chart_shape = slide.shapes.add_chart(
            chart_type,
            Inches(1), Inches(1.5), Inches(8), Inches(5),
            chart_data,
        )

        # Set title if provided
        chart_title = data.get("title")
        if chart_title and chart_shape.has_chart:
            chart_shape.chart.has_title = True
            chart_shape.chart.chart_title.text_frame.text = chart_title

        prs.save(path)

        return ToolResult(
            success=True,
            output=f"Added {ct} chart to slide {slide_num} in '{os.path.basename(path)}'",
            data={"slide_num": slide_num, "chart_type": ct},
        )

    # -------------------------------------------------------------------------
    # INFO
    # -------------------------------------------------------------------------

    def _info(self, kwargs) -> ToolResult:
        from pptx import Presentation

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        file_size = os.path.getsize(path)
        prs = Presentation(path)

        slides_info = []
        total_shapes = 0
        total_images = 0
        total_tables = 0

        for i, slide in enumerate(prs.slides, 1):
            shapes = len(slide.shapes)
            images = sum(1 for s in slide.shapes if s.shape_type == 13)
            tables = sum(1 for s in slide.shapes if s.has_table)
            title_text = ""
            if slide.shapes.title:
                title_text = slide.shapes.title.text[:60]

            total_shapes += shapes
            total_images += images
            total_tables += tables

            slides_info.append({
                "num": i,
                "title": title_text,
                "layout": slide.slide_layout.name if slide.slide_layout else "Unknown",
                "shapes": shapes,
                "images": images,
                "tables": tables,
            })

        # Slide dimensions
        width_in = prs.slide_width / 914400  # EMU to inches
        height_in = prs.slide_height / 914400

        lines = [
            f"File: {os.path.basename(path)} ({file_size / 1024:.1f} KB)",
            f"Slides: {len(prs.slides)} | Size: {width_in:.1f}\" x {height_in:.1f}\"",
            f"Total shapes: {total_shapes} | Images: {total_images} | Tables: {total_tables}",
            f"Layouts available: {len(prs.slide_layouts)}",
            "",
            "Slides:",
        ]

        for s in slides_info:
            lines.append(f"  {s['num']}. [{s['layout']}] {s['title'] or '(no title)'} ({s['shapes']} shapes)")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "slides": len(prs.slides),
                "total_shapes": total_shapes,
                "total_images": total_images,
                "slides_info": slides_info,
            },
        )
