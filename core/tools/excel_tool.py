"""
ARIA - Excel Tool
==================

Read, create, and modify Excel spreadsheets (.xlsx).
Uses openpyxl for full Excel manipulation including formulas, styles, and charts.

Actions:
  read     — Read sheet data (all or range)
  create   — Create new workbook with data
  write    — Write data to cells
  info     — Get workbook metadata (sheets, dimensions, formulas)
  add_sheet — Add a new sheet
  delete_sheet — Remove a sheet
  format   — Apply formatting (bold, colors, borders, number formats)
  formula  — Insert formulas
  chart    — Create a chart from data range
"""

import logging
import os
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.excel")

MAX_ROWS_DISPLAY = 200
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB


def _col_letter(col_num: int) -> str:
    """Convert 1-based column number to Excel letter (1→A, 27→AA)."""
    result = ""
    while col_num > 0:
        col_num, remainder = divmod(col_num - 1, 26)
        result = chr(65 + remainder) + result
    return result


class ExcelTool(ToolBase):
    """Read, create, and modify Excel spreadsheets."""

    name = "excel"
    description = (
        "Work with Excel spreadsheets (.xlsx). "
        "Actions: read (get cell data), create (new workbook), write (modify cells), "
        "info (metadata), add_sheet, delete_sheet, format (styles), formula, chart. "
        "Use 'read' to inspect, 'create' for new files, 'write' to modify."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: read, create, write, info, add_sheet, delete_sheet, format, formula, chart",
            required=True,
            enum=["read", "create", "write", "info", "add_sheet", "delete_sheet", "format", "formula", "chart"],
        ),
        ToolParam(
            name="path",
            type="string",
            description="Path to the Excel file",
            required=True,
        ),
        ToolParam(
            name="sheet",
            type="string",
            description="Sheet name (default: active sheet)",
            required=False,
        ),
        ToolParam(
            name="range",
            type="string",
            description="Cell range, e.g. 'A1:D10', 'B2', 'A:C' (default: all data)",
            required=False,
        ),
        ToolParam(
            name="data",
            type="string",
            description=(
                "Data for write/create as JSON. "
                "For create: [[row1_col1, row1_col2], [row2_col1, row2_col2]] "
                "For write: {\"A1\": \"value\", \"B2\": 42} or [[row_data]] with range"
            ),
            required=False,
        ),
        ToolParam(
            name="style",
            type="string",
            description=(
                "JSON style for format action: "
                "{\"bold\": true, \"italic\": false, \"font_size\": 12, "
                "\"font_color\": \"FF0000\", \"bg_color\": \"FFFF00\", "
                "\"number_format\": \"#,##0.00\", \"border\": true, \"align\": \"center\"}"
            ),
            required=False,
        ),
        ToolParam(
            name="chart_type",
            type="string",
            description="Chart type for chart action: bar, line, pie, scatter, area",
            required=False,
            enum=["bar", "line", "pie", "scatter", "area"],
        ),
        ToolParam(
            name="chart_title",
            type="string",
            description="Chart title",
            required=False,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        try:
            import openpyxl
        except ImportError:
            return ToolResult(success=False, error="openpyxl not installed. Run: pip install openpyxl")

        action = kwargs["action"]
        dispatch = {
            "read": self._read,
            "create": self._create,
            "write": self._write,
            "info": self._info,
            "add_sheet": self._add_sheet,
            "delete_sheet": self._delete_sheet,
            "format": self._format,
            "formula": self._formula,
            "chart": self._chart,
        }

        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        return handler(kwargs)

    # -------------------------------------------------------------------------
    # READ
    # -------------------------------------------------------------------------

    def _read(self, kwargs) -> ToolResult:
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet_name = kwargs.get("sheet") or wb.sheetnames[0]

        if sheet_name not in wb.sheetnames:
            wb.close()
            return ToolResult(success=False, error=f"Sheet '{sheet_name}' not found. Available: {wb.sheetnames}")

        ws = wb[sheet_name]
        cell_range = kwargs.get("range")

        rows = []
        if cell_range:
            try:
                for row in ws[cell_range]:
                    if hasattr(row, '__iter__'):
                        rows.append([str(c.value) if c.value is not None else "" for c in row])
                    else:
                        rows.append([str(row.value) if row.value is not None else ""])
            except Exception as e:
                wb.close()
                return ToolResult(success=False, error=f"Invalid range '{cell_range}': {e}")
        else:
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_ROWS_DISPLAY:
                    rows.append([f"... truncated at {MAX_ROWS_DISPLAY} rows (total: {ws.max_row})"])
                    break
                rows.append([str(v) if v is not None else "" for v in row])

        wb.close()

        # Format as table
        if not rows:
            return ToolResult(success=True, output=f"Sheet '{sheet_name}' is empty.", data={"rows": 0})

        # Calculate column widths for pretty output
        lines = [f"Sheet: {sheet_name} | Range: {cell_range or 'all'}\n"]
        for i, row in enumerate(rows):
            row_num = i + 1
            cells = " | ".join(row)
            lines.append(f"  {row_num:>4}: {cells}")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={
                "sheet": sheet_name,
                "rows": len(rows),
                "data": rows,
            },
        )

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------

    def _create(self, kwargs) -> ToolResult:
        import json
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        data_str = kwargs.get("data")

        wb = openpyxl.Workbook()
        ws = wb.active
        sheet_name = kwargs.get("sheet", "Sheet1")
        ws.title = sheet_name

        rows_written = 0
        if data_str:
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError as e:
                return ToolResult(success=False, error=f"Invalid JSON data: {e}")

            if isinstance(data, list):
                for row in data:
                    if isinstance(row, list):
                        ws.append(row)
                    else:
                        ws.append([row])
                    rows_written += 1
            elif isinstance(data, dict):
                # {"headers": [...], "rows": [[...], ...]}
                if "headers" in data:
                    ws.append(data["headers"])
                    rows_written += 1
                for row in data.get("rows", []):
                    ws.append(row if isinstance(row, list) else [row])
                    rows_written += 1

        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        wb.save(path)
        wb.close()

        return ToolResult(
            success=True,
            output=f"Created '{os.path.basename(path)}': {rows_written} rows in sheet '{sheet_name}'",
            data={"path": path, "rows": rows_written, "sheet": sheet_name},
        )

    # -------------------------------------------------------------------------
    # WRITE
    # -------------------------------------------------------------------------

    def _write(self, kwargs) -> ToolResult:
        import json
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        data_str = kwargs.get("data")
        if not data_str:
            return ToolResult(success=False, error="'data' is required for write")

        try:
            data = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON data: {e}")

        wb = openpyxl.load_workbook(path)
        sheet_name = kwargs.get("sheet") or wb.sheetnames[0]
        if sheet_name not in wb.sheetnames:
            wb.close()
            return ToolResult(success=False, error=f"Sheet '{sheet_name}' not found")

        ws = wb[sheet_name]
        cells_written = 0

        if isinstance(data, dict):
            # {"A1": "value", "B2": 42}
            for cell_ref, value in data.items():
                ws[cell_ref] = value
                cells_written += 1
        elif isinstance(data, list):
            # [[row_data]] starting at range or A1
            start = kwargs.get("range", "A1")
            from openpyxl.utils import coordinate_from_string, column_index_from_string
            col_str, start_row = coordinate_from_string(start)
            start_col = column_index_from_string(col_str)

            for r_idx, row in enumerate(data):
                if isinstance(row, list):
                    for c_idx, val in enumerate(row):
                        ws.cell(row=start_row + r_idx, column=start_col + c_idx, value=val)
                        cells_written += 1
                else:
                    ws.cell(row=start_row + r_idx, column=start_col, value=row)
                    cells_written += 1

        wb.save(path)
        wb.close()

        return ToolResult(
            success=True,
            output=f"Written {cells_written} cells to '{os.path.basename(path)}' sheet '{sheet_name}'",
            data={"path": path, "cells_written": cells_written},
        )

    # -------------------------------------------------------------------------
    # INFO
    # -------------------------------------------------------------------------

    def _info(self, kwargs) -> ToolResult:
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        file_size = os.path.getsize(path)
        wb = openpyxl.load_workbook(path)

        sheets_info = []
        for name in wb.sheetnames:
            ws = wb[name]
            sheets_info.append({
                "name": name,
                "rows": ws.max_row or 0,
                "cols": ws.max_column or 0,
                "dimensions": ws.dimensions or "",
            })

        wb.close()

        lines = [f"File: {os.path.basename(path)} ({file_size / 1024:.1f} KB)"]
        lines.append(f"Sheets ({len(sheets_info)}):")
        for s in sheets_info:
            lines.append(f"  {s['name']}: {s['rows']}×{s['cols']} ({s['dimensions']})")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"file_size": file_size, "sheets": sheets_info},
        )

    # -------------------------------------------------------------------------
    # ADD / DELETE SHEET
    # -------------------------------------------------------------------------

    def _add_sheet(self, kwargs) -> ToolResult:
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        sheet_name = kwargs.get("sheet")
        if not sheet_name:
            return ToolResult(success=False, error="'sheet' name is required")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        wb = openpyxl.load_workbook(path)
        if sheet_name in wb.sheetnames:
            wb.close()
            return ToolResult(success=False, error=f"Sheet '{sheet_name}' already exists")

        wb.create_sheet(title=sheet_name)
        wb.save(path)
        wb.close()

        return ToolResult(success=True, output=f"Added sheet '{sheet_name}' to '{os.path.basename(path)}'")

    def _delete_sheet(self, kwargs) -> ToolResult:
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        sheet_name = kwargs.get("sheet")
        if not sheet_name:
            return ToolResult(success=False, error="'sheet' name is required")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        wb = openpyxl.load_workbook(path)
        if sheet_name not in wb.sheetnames:
            wb.close()
            return ToolResult(success=False, error=f"Sheet '{sheet_name}' not found")

        if len(wb.sheetnames) <= 1:
            wb.close()
            return ToolResult(success=False, error="Cannot delete the last sheet")

        del wb[sheet_name]
        wb.save(path)
        wb.close()

        return ToolResult(success=True, output=f"Deleted sheet '{sheet_name}' from '{os.path.basename(path)}'")

    # -------------------------------------------------------------------------
    # FORMAT
    # -------------------------------------------------------------------------

    def _format(self, kwargs) -> ToolResult:
        import json
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        path = os.path.expanduser(kwargs["path"])
        cell_range = kwargs.get("range")
        style_str = kwargs.get("style")

        if not cell_range:
            return ToolResult(success=False, error="'range' is required for format")
        if not style_str:
            return ToolResult(success=False, error="'style' JSON is required for format")

        try:
            style = json.loads(style_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid style JSON: {e}")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        wb = openpyxl.load_workbook(path)
        sheet_name = kwargs.get("sheet") or wb.sheetnames[0]
        ws = wb[sheet_name]

        # Build style objects
        font_kwargs = {}
        if "bold" in style:
            font_kwargs["bold"] = style["bold"]
        if "italic" in style:
            font_kwargs["italic"] = style["italic"]
        if "font_size" in style:
            font_kwargs["size"] = style["font_size"]
        if "font_color" in style:
            font_kwargs["color"] = style["font_color"]

        font = Font(**font_kwargs) if font_kwargs else None
        fill = PatternFill(start_color=style["bg_color"], end_color=style["bg_color"], fill_type="solid") if "bg_color" in style else None
        align = Alignment(horizontal=style["align"]) if "align" in style else None
        number_fmt = style.get("number_format")

        border = None
        if style.get("border"):
            side = Side(style="thin")
            border = Border(left=side, right=side, top=side, bottom=side)

        cells_formatted = 0
        for row in ws[cell_range]:
            if hasattr(row, '__iter__'):
                for cell in row:
                    if font:
                        cell.font = font
                    if fill:
                        cell.fill = fill
                    if align:
                        cell.alignment = align
                    if number_fmt:
                        cell.number_format = number_fmt
                    if border:
                        cell.border = border
                    cells_formatted += 1
            else:
                if font:
                    row.font = font
                if fill:
                    row.fill = fill
                if align:
                    row.alignment = align
                if number_fmt:
                    row.number_format = number_fmt
                if border:
                    row.border = border
                cells_formatted += 1

        wb.save(path)
        wb.close()

        return ToolResult(
            success=True,
            output=f"Formatted {cells_formatted} cells in range {cell_range}",
            data={"cells_formatted": cells_formatted},
        )

    # -------------------------------------------------------------------------
    # FORMULA
    # -------------------------------------------------------------------------

    def _formula(self, kwargs) -> ToolResult:
        import json
        import openpyxl

        path = os.path.expanduser(kwargs["path"])
        data_str = kwargs.get("data")
        if not data_str:
            return ToolResult(success=False, error="'data' is required: {\"C1\": \"=SUM(A1:B1)\", \"D1\": \"=AVERAGE(A1:C1)\"}")

        try:
            formulas = json.loads(data_str)
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"Invalid JSON: {e}")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        wb = openpyxl.load_workbook(path)
        sheet_name = kwargs.get("sheet") or wb.sheetnames[0]
        ws = wb[sheet_name]

        count = 0
        for cell_ref, formula in formulas.items():
            ws[cell_ref] = formula
            count += 1

        wb.save(path)
        wb.close()

        return ToolResult(
            success=True,
            output=f"Inserted {count} formulas in '{os.path.basename(path)}'",
            data={"formulas_inserted": count},
        )

    # -------------------------------------------------------------------------
    # CHART
    # -------------------------------------------------------------------------

    def _chart(self, kwargs) -> ToolResult:
        import openpyxl
        from openpyxl.chart import BarChart, LineChart, PieChart, ScatterChart, AreaChart, Reference

        path = os.path.expanduser(kwargs["path"])
        cell_range = kwargs.get("range")
        chart_type = kwargs.get("chart_type", "bar")
        chart_title = kwargs.get("chart_title", "Chart")

        if not cell_range:
            return ToolResult(success=False, error="'range' is required for chart (data range, e.g. 'A1:D10')")

        if not os.path.isfile(path):
            return ToolResult(success=False, error=f"File not found: {path}")

        wb = openpyxl.load_workbook(path)
        sheet_name = kwargs.get("sheet") or wb.sheetnames[0]
        ws = wb[sheet_name]

        chart_classes = {
            "bar": BarChart,
            "line": LineChart,
            "pie": PieChart,
            "scatter": ScatterChart,
            "area": AreaChart,
        }

        ChartClass = chart_classes[chart_type]
        chart = ChartClass()
        chart.title = chart_title

        # Parse range to get data reference
        from openpyxl.utils import range_boundaries
        min_col, min_row, max_col, max_row = range_boundaries(cell_range)

        data_ref = Reference(ws, min_col=min_col + 1, min_row=min_row, max_col=max_col, max_row=max_row)
        cats_ref = Reference(ws, min_col=min_col, min_row=min_row + 1, max_row=max_row)

        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)

        # Place chart below the data
        chart_cell = f"A{max_row + 2}"
        ws.add_chart(chart, chart_cell)

        wb.save(path)
        wb.close()

        return ToolResult(
            success=True,
            output=f"Created {chart_type} chart '{chart_title}' at {chart_cell} from range {cell_range}",
            data={"chart_type": chart_type, "position": chart_cell},
        )
