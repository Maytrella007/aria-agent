"""
File Operations Skill - Intelligent file management.

Handles common file operations with natural language:
find files, organize, compare, batch rename, compress/decompress.
"""

import re

from .base import SkillBase, SkillResult, SkillContext
from core.tools.tool_names import Tools


class FileOpsSkill(SkillBase):
    name = "file_ops"
    description = "Smart file operations: find, organize, compare, compress"
    requires_tools = [Tools.FILE_MANAGER]

    def _execute(self, query: str, ctx: SkillContext) -> SkillResult:
        if not ctx.tools:
            return SkillResult(success=False, error="No tools available")

        # Detect operation type
        op = self._detect_operation(query)

        if op == "find":
            return self._find_files(query, ctx)
        elif op == "compress":
            return self._compress(query, ctx)
        elif op == "extract":
            return self._extract(query, ctx)
        elif op == "list":
            return self._list_files(query, ctx)
        elif op == "organize":
            return self._organize(query, ctx)
        else:
            return self._smart_file_op(query, ctx)

    def _detect_operation(self, query: str) -> str:
        """Detect which file operation the user wants."""
        q = query.lower()
        if any(w in q for w in ["find", "buscar", "search", "locate"]):
            return "find"
        if any(w in q for w in ["compress", "comprimir", "zip", "tar"]):
            return "compress"
        if any(w in q for w in ["extract", "extraer", "unzip", "decompress", "descomprimir"]):
            return "extract"
        if any(w in q for w in ["list", "listar", "show files", "mostrar archivos"]):
            return "list"
        if any(w in q for w in ["organize", "organizar", "sort", "ordenar"]):
            return "organize"
        return "smart"

    def _find_files(self, query: str, ctx: SkillContext) -> SkillResult:
        """Find files matching criteria."""
        # Extract path and pattern
        path = "."
        path_match = re.search(r'(?:in|en)\s+([/~][\w./\\-]+|[A-Z]:\\[\w\\.-]+)', query)
        if path_match:
            path = path_match.group(1)

        # Extract pattern
        pattern = "*"
        ext_match = re.search(r'\.([\w]+)\b', query)
        if ext_match:
            pattern = f"*.{ext_match.group(1)}"
        name_match = re.search(r'(?:named?|called?|llamados?)\s+"?([^"]+)"?', query, re.IGNORECASE)
        if name_match:
            pattern = f"*{name_match.group(1).strip()}*"

        result = ctx.tools.execute(Tools.FILE_MANAGER, action="search", path=path, pattern=pattern)
        if result.success:
            return SkillResult(
                success=True,
                output=result.output,
                data={"path": path, "pattern": pattern, "operation": "find"},
            )
        return SkillResult(success=False, error=f"File search failed: {result.error}")

    def _compress(self, query: str, ctx: SkillContext) -> SkillResult:
        """Compress files or directories."""
        # Extract source path
        paths = re.findall(r'([/~][\w./\\-]+|[A-Z]:\\[\w\\.-]+)', query)
        if not paths:
            return SkillResult(success=False, error="Please specify a path to compress")

        source = paths[0]
        output = paths[1] if len(paths) > 1 else f"{source}.zip"

        fmt = "zip"
        if any(w in query.lower() for w in ["tar", ".tar", "tgz", "tar.gz"]):
            fmt = "tar.gz"
            if not output.endswith((".tar.gz", ".tgz")):
                output = f"{source}.tar.gz"

        result = ctx.tools.execute(Tools.COMPRESS, action="compress", source=source, output=output, format=fmt)
        if result.success:
            return SkillResult(
                success=True,
                output=f"Compressed: {source} -> {output}\n{result.output}",
                data={"source": source, "output": output, "format": fmt},
            )
        return SkillResult(success=False, error=f"Compression failed: {result.error}")

    def _extract(self, query: str, ctx: SkillContext) -> SkillResult:
        """Extract compressed files."""
        paths = re.findall(r'([/~][\w./\\-]+\.(?:zip|tar|gz|tgz|tar\.gz))', query)
        if not paths:
            return SkillResult(success=False, error="Please specify an archive to extract")

        source = paths[0]
        dest_match = re.search(r'(?:to|a|en|into)\s+([/~][\w./\\-]+)', query)
        dest = dest_match.group(1) if dest_match else "."

        result = ctx.tools.execute(Tools.COMPRESS, action="extract", source=source, destination=dest)
        if result.success:
            return SkillResult(
                success=True,
                output=f"Extracted: {source} -> {dest}\n{result.output}",
                data={"source": source, "destination": dest},
            )
        return SkillResult(success=False, error=f"Extraction failed: {result.error}")

    def _list_files(self, query: str, ctx: SkillContext) -> SkillResult:
        """List files in a directory."""
        path = "."
        path_match = re.search(r'(?:in|en|of|de)\s+([/~][\w./\\-]+|[A-Z]:\\[\w\\.-]+)', query)
        if path_match:
            path = path_match.group(1)

        result = ctx.tools.execute(Tools.FILE_MANAGER, action="list", path=path)
        if result.success:
            return SkillResult(
                success=True,
                output=result.output,
                data={"path": path, "operation": "list"},
            )
        return SkillResult(success=False, error=f"List failed: {result.error}")

    def _organize(self, query: str, ctx: SkillContext) -> SkillResult:
        """Use LLM to plan file organization."""
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for file organization")

        # First list the files
        path = "."
        path_match = re.search(r'(?:in|en)\s+([/~][\w./\\-]+)', query)
        if path_match:
            path = path_match.group(1)

        list_result = ctx.tools.execute(Tools.FILE_MANAGER, action="list", path=path)
        if not list_result.success:
            return SkillResult(success=False, error=f"Cannot list files: {list_result.error}")

        prompt = f"""The user wants to organize files in {path}.

Current files:
{list_result.output[:3000]}

User request: {query}

Create an organization plan:
1. Suggest folder structure
2. List which files go where
3. Any files that could be deleted (duplicates, temp files)

Be specific and actionable. DO NOT execute anything - just suggest."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=600,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"path": path, "operation": "organize", "plan_only": True},
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Organization planning failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")

    def _smart_file_op(self, query: str, ctx: SkillContext) -> SkillResult:
        """Fallback: use LLM to understand the file operation."""
        if not ctx.llm:
            return SkillResult(success=False, error="LLM required for this operation")

        prompt = f"""The user wants to perform a file operation: {query}

Available tools: file_manager (read/write/list/search/delete/mkdir), compress (zip/tar)

What specific tool calls should be made? Describe the steps briefly."""

        try:
            response = ctx.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
            )
            if response and response.content:
                return SkillResult(
                    success=True,
                    output=response.content,
                    data={"operation": "smart", "plan_only": True},
                )
        except Exception as e:
            return SkillResult(success=False, error=f"Operation failed: {e}")

        return SkillResult(success=False, error="LLM returned empty response")
