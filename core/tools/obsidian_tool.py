"""ARIA - Obsidian Tool."""

import os

from .tool_base import ToolBase, ToolParam, ToolResult


class ObsidianTool(ToolBase):
    name = "obsidian"
    description = "Manage a local Obsidian vault. Actions: list, search, read, write, append."
    parameters = [
        ToolParam(name="action", type="string", description="Vault action", required=True,
                  enum=["list", "search", "read", "write", "append"]),
        ToolParam(name="path", type="string", description="Relative note path inside the vault", required=False),
        ToolParam(name="query", type="string", description="Search query", required=False),
        ToolParam(name="content", type="string", description="Content to write/append", required=False),
    ]

    def _vault_path(self) -> str:
        data_dir = self.context.get("data_dir", ".")
        vault = self.context.get("obsidian_vault") or os.path.join(data_dir, "obsidian_vault")
        os.makedirs(vault, exist_ok=True)
        return vault

    def _resolve(self, relative_path: str) -> str:
        vault = self._vault_path()
        rel = (relative_path or "").strip().lstrip("/")
        full = os.path.abspath(os.path.join(vault, rel))
        if not full.startswith(os.path.abspath(vault)):
            raise ValueError("Path escapes vault")
        return full

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        if action == "list":
            return self._list_notes()
        if action == "search":
            return self._search(kwargs.get("query", ""))
        if action == "read":
            return self._read(kwargs.get("path", ""))
        if action == "write":
            return self._write(kwargs.get("path", ""), kwargs.get("content", ""), append=False)
        if action == "append":
            return self._write(kwargs.get("path", ""), kwargs.get("content", ""), append=True)
        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _list_notes(self) -> ToolResult:
        vault = self._vault_path()
        notes = []
        for root, _dirs, files in os.walk(vault):
            for name in files:
                if name.endswith(".md"):
                    notes.append(os.path.relpath(os.path.join(root, name), vault))
        notes.sort()
        return ToolResult(success=True, output="\n".join(notes) if notes else "No notes found.", data={"notes": notes})

    def _search(self, query: str) -> ToolResult:
        vault = self._vault_path()
        results = []
        needle = query.lower().strip()
        for root, _dirs, files in os.walk(vault):
            for name in files:
                if not name.endswith(".md"):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, vault)
                try:
                    with open(full, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                except Exception:
                    continue
                if not needle or needle in content.lower() or needle in rel.lower():
                    results.append({"path": rel, "preview": content[:200]})
        return ToolResult(success=True, output="\n".join(r["path"] for r in results) if results else "No matching notes.", data={"results": results})

    def _read(self, path: str) -> ToolResult:
        if not path:
            return ToolResult(success=False, error="path required")
        try:
            full = self._resolve(path)
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        if not os.path.isfile(full):
            return ToolResult(success=False, error=f"Note not found: {path}")
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return ToolResult(success=True, output=content, data={"path": path, "size": len(content)})

    def _write(self, path: str, content: str, append: bool) -> ToolResult:
        if not path:
            return ToolResult(success=False, error="path required")
        try:
            full = self._resolve(path if path.endswith(".md") else f"{path}.md")
        except ValueError as e:
            return ToolResult(success=False, error=str(e))
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "a" if append else "w"
        with open(full, mode, encoding="utf-8") as f:
            f.write(content or "")
        return ToolResult(success=True, output=f"Saved note: {os.path.relpath(full, self._vault_path())}", data={"path": os.path.relpath(full, self._vault_path())})
