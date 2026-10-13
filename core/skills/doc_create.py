"""
Document Create Skill - Create Office documents from instructions.

Uses LLM to generate content, then Word/Excel/PowerPoint tools
to produce actual documents.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class DocCreateSkill(SkillBase):
    name = "doc_create"
    description = "Create Word, Excel, or PowerPoint documents"
    requires_tools = []

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for document creation")

        # Detect document type
        doc_type = self._detect_doc_type(query)

        if doc_type == "excel":
            return self._create_excel(query, ctx)
        elif doc_type == "powerpoint":
            return self._create_powerpoint(query, ctx)
        else:
            return self._create_word(query, ctx)

    def _detect_doc_type(self, query: str) -> str:
        q = query.lower()
        if any(w in q for w in ["spreadsheet", "hoja de cálculo", "excel", "xlsx", "tabla", "table"]):
            return "excel"
        if any(w in q for w in ["presentation", "presentación", "pptx", "powerpoint", "slides", "diapositivas"]):
            return "powerpoint"
        return "word"

    def _create_word(self, query: str, ctx: SkillContext) -> SkillResult:
        """Create a Word document."""
        import json

        # Extract filename
        filename = self._extract_filename(query, ".docx") or "document.docx"

        prompt = f"""Create content for a Word document based on this request:

Request: {query}

Generate the document as structured JSON with this format:
{{
  "title": "Document Title",
  "sections": [
    {{"heading": "Section 1", "content": "Paragraph text..."}},
    {{"heading": "Section 2", "content": "More text..."}}
  ]
}}

Keep content professional and well-structured. Respond with ONLY the JSON."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            if not response or not response.content:
                return SkillResult(success=False, error="LLM returned empty response")

            content_text = response.content.strip()
            # Extract JSON from response
            json_match = re.search(r'\{[\s\S]+\}', content_text)
            if not json_match:
                # Fallback: write plain text
                result = ctx.tools.execute(
                    Tools.WORD,
                    action="create",
                    path=filename,
                    content=content_text,
                )
                if result.success:
                    return SkillResult(
                        success=True,
                        output=f"Document created: {filename}\n{result.output}",
                        data={"type": "word", "path": filename},
                    )
                return SkillResult(success=False, error=f"Document creation failed: {result.error}")

            try:
                doc_data = json.loads(json_match.group())
            except json.JSONDecodeError:
                result = ctx.tools.execute(
                    Tools.WORD,
                    action="create",
                    path=filename,
                    content=content_text,
                )
                if result.success:
                    return SkillResult(
                        success=True,
                        output=f"Document created: {filename}\n{result.output}",
                        data={"type": "word", "path": filename, "fallback": "plain_text"},
                    )
                return SkillResult(success=False, error=f"Document creation failed: {result.error}")

            title = doc_data.get("title", "Document")
            sections = doc_data.get("sections", [])

            # Build document content
            full_content = f"# {title}\n\n"
            for section in sections:
                heading = section.get("heading", "")
                content = section.get("content", "")
                if heading:
                    full_content += f"## {heading}\n\n"
                full_content += f"{content}\n\n"

            result = ctx.tools.execute(
                Tools.WORD,
                action="create",
                path=filename,
                content=full_content,
                title=title,
            )

            if result.success:
                return SkillResult(
                    success=True,
                    output=f"Document created: {filename}\nTitle: {title}\nSections: {len(sections)}\n{result.output}",
                    data={"type": "word", "path": filename, "title": title},
                )
            return SkillResult(success=False, error=f"Document creation failed: {result.error}")

        except Exception as e:
            return SkillResult(success=False, error=f"Document creation failed: {e}")

    def _create_excel(self, query: str, ctx: SkillContext) -> SkillResult:
        """Create an Excel spreadsheet."""
        filename = self._extract_filename(query, ".xlsx") or "spreadsheet.xlsx"

        prompt = f"""Create data for an Excel spreadsheet based on this request:

Request: {query}

Generate as JSON with this format:
{{
  "title": "Sheet Title",
  "headers": ["Column1", "Column2", "Column3"],
  "rows": [
    ["data1", "data2", "data3"],
    ["data4", "data5", "data6"]
  ]
}}

Respond with ONLY the JSON."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
            )
            if not response or not response.content:
                return SkillResult(success=False, error="LLM returned empty response")

            import json
            json_match = re.search(r'\{[\s\S]+\}', response.content)
            if not json_match:
                return SkillResult(success=False, error="Could not parse spreadsheet data")

            sheet_data = json.loads(json_match.group())
            headers = sheet_data.get("headers", [])
            rows = sheet_data.get("rows", [])

            # Build CSV-like content for the tool
            all_rows = [headers] + rows
            csv_content = "\n".join(",".join(str(cell) for cell in row) for row in all_rows)

            result = ctx.tools.execute(
                Tools.EXCEL,
                action="create",
                path=filename,
                data=csv_content,
                headers=headers,
            )

            if result.success:
                return SkillResult(
                    success=True,
                    output=f"Spreadsheet created: {filename}\nColumns: {len(headers)}, Rows: {len(rows)}\n{result.output}",
                    data={"type": "excel", "path": filename, "rows": len(rows)},
                )
            return SkillResult(success=False, error=f"Spreadsheet creation failed: {result.error}")

        except Exception as e:
            return SkillResult(success=False, error=f"Spreadsheet creation failed: {e}")

    def _create_powerpoint(self, query: str, ctx: SkillContext) -> SkillResult:
        """Create a PowerPoint presentation."""
        filename = self._extract_filename(query, ".pptx") or "presentation.pptx"

        prompt = f"""Create slide content for a PowerPoint presentation:

Request: {query}

Generate as JSON:
{{
  "title": "Presentation Title",
  "slides": [
    {{"title": "Slide Title", "content": "Bullet point 1\\nBullet point 2\\nBullet point 3"}},
    {{"title": "Another Slide", "content": "More content"}}
  ]
}}

Create 4-8 slides. Respond with ONLY the JSON."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1000,
            )
            if not response or not response.content:
                return SkillResult(success=False, error="LLM returned empty response")

            import json
            json_match = re.search(r'\{[\s\S]+\}', response.content)
            if not json_match:
                return SkillResult(success=False, error="Could not parse presentation data")

            ppt_data = json.loads(json_match.group())
            title = ppt_data.get("title", "Presentation")
            slides = ppt_data.get("slides", [])

            result = ctx.tools.execute(
                Tools.POWERPOINT,
                action="create",
                path=filename,
                title=title,
                slides=slides,
            )

            if result.success:
                return SkillResult(
                    success=True,
                    output=f"Presentation created: {filename}\nTitle: {title}\nSlides: {len(slides)}\n{result.output}",
                    data={"type": "powerpoint", "path": filename, "slides": len(slides)},
                )
            return SkillResult(success=False, error=f"Presentation creation failed: {result.error}")

        except Exception as e:
            return SkillResult(success=False, error=f"Presentation creation failed: {e}")

    def _extract_filename(self, query: str, default_ext: str) -> str:
        """Extract filename from query."""
        # Look for quoted filename
        m = re.search(r'"([^"]+)"', query)
        if m:
            name = m.group(1)
            if not name.endswith(default_ext):
                name += default_ext
            return name

        # Look for filename with extension
        m = re.search(r'(\w[\w\s-]*\.(docx|xlsx|pptx))', query, re.IGNORECASE)
        if m:
            return m.group(1).replace(" ", "_")

        # Look for "called/named X"
        m = re.search(r'(?:called|named|llamado|con\s+nombre)\s+"?(\w[\w\s-]*)"?', query, re.IGNORECASE)
        if m:
            return m.group(1).replace(" ", "_") + default_ext

        return ""
