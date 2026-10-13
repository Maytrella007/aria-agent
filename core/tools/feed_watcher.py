"""
ARIA - Feed Watcher Tool
========================

Track RSS/Atom feeds and simple web pages for updates.
"""

import hashlib
import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .tool_base import ToolBase, ToolParam, ToolResult


class FeedWatcherTool(ToolBase):
    name = "feed_watcher"
    description = (
        "Monitor RSS/Atom feeds and simple web pages. Actions: add, list, scan, "
        "items, mark_read, remove. Useful for tracking source updates over time."
    )
    parameters = [
        ToolParam(name="action", type="string", description="Action to perform", required=True,
                  enum=["add", "list", "scan", "items", "mark_read", "remove"]),
        ToolParam(name="url", type="string", description="Feed or page URL", required=False),
        ToolParam(name="label", type="string", description="Optional label for the watcher", required=False),
        ToolParam(name="item_id", type="string", description="Item ID to mark as read", required=False),
        ToolParam(name="limit", type="integer", description="Max items to return", required=False, default=10),
        ToolParam(name="unread_only", type="boolean", description="Only return unread items", required=False, default=True),
    ]

    def _store_path(self) -> str:
        data_dir = self.context.get("data_dir", ".")
        return os.path.join(data_dir, "feed_watchers.json")

    def _load_store(self) -> dict:
        path = self._store_path()
        if not os.path.exists(path):
            return {"watchers": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"watchers": []}

    def _save_store(self, store: dict):
        path = self._store_path()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(store, f, indent=2, ensure_ascii=False)

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        if action == "add":
            return self._add(kwargs)
        if action == "list":
            return self._list()
        if action == "scan":
            return self._scan(kwargs)
        if action == "items":
            return self._items(kwargs)
        if action == "mark_read":
            return self._mark_read(kwargs)
        if action == "remove":
            return self._remove(kwargs)
        return ToolResult(success=False, error=f"Unknown action: {action}")

    def _add(self, kwargs: dict) -> ToolResult:
        url = (kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(success=False, error="url required for add")
        store = self._load_store()
        for watcher in store["watchers"]:
            if watcher["url"] == url:
                return ToolResult(success=True, output=f"Already watching {url}", data={"watcher": watcher})

        watcher = {
            "url": url,
            "label": kwargs.get("label") or url,
            "kind": "unknown",
            "added_at": datetime.now(timezone.utc).isoformat(),
            "last_checked": None,
            "last_hash": None,
            "items": [],
        }
        store["watchers"].append(watcher)
        self._save_store(store)
        return ToolResult(success=True, output=f"Watching {url}", data={"watcher": watcher})

    def _list(self) -> ToolResult:
        store = self._load_store()
        watchers = store["watchers"]
        if not watchers:
            return ToolResult(success=True, output="No watched sources.", data={"watchers": []})
        lines = [f"Watched sources ({len(watchers)}):", ""]
        for idx, watcher in enumerate(watchers, 1):
            unread = len([i for i in watcher.get("items", []) if not i.get("read")])
            lines.append(f"{idx}. {watcher['label']}")
            lines.append(f"   URL: {watcher['url']}")
            lines.append(f"   Kind: {watcher.get('kind', 'unknown')}")
            lines.append(f"   Unread items: {unread}")
        return ToolResult(success=True, output="\n".join(lines), data={"watchers": watchers})

    def _scan(self, kwargs: dict) -> ToolResult:
        target_url = (kwargs.get("url") or "").strip()
        store = self._load_store()
        watchers = [w for w in store["watchers"] if not target_url or w["url"] == target_url]
        if target_url and not watchers:
            return ToolResult(success=False, error=f"Watcher not found: {target_url}")

        total_new = 0
        scanned = []
        for watcher in watchers:
            html = self._fetch_url(watcher["url"])
            if html is None:
                continue
            is_feed = self._looks_like_feed(html)
            watcher["kind"] = "feed" if is_feed else "page"
            new_items = self._scan_feed(watcher, html) if is_feed else self._scan_page(watcher, html)
            watcher["last_checked"] = datetime.now(timezone.utc).isoformat()
            total_new += len(new_items)
            scanned.append({"url": watcher["url"], "new_items": len(new_items), "items": new_items})

        self._save_store(store)
        return ToolResult(
            success=True,
            output=f"Scanned {len(scanned)} sources, found {total_new} new items.",
            data={"scanned": scanned, "new_items": total_new},
        )

    def _items(self, kwargs: dict) -> ToolResult:
        target_url = (kwargs.get("url") or "").strip()
        unread_only = kwargs.get("unread_only", True)
        limit = min(kwargs.get("limit", 10), 100)
        store = self._load_store()

        items = []
        for watcher in store["watchers"]:
            if target_url and watcher["url"] != target_url:
                continue
            for item in watcher.get("items", []):
                if unread_only and item.get("read"):
                    continue
                items.append({**item, "source": watcher["label"], "source_url": watcher["url"]})

        items.sort(key=lambda x: x.get("published", ""), reverse=True)
        items = items[:limit]
        if not items:
            return ToolResult(success=True, output="No matching items.", data={"items": []})

        lines = [f"Items ({len(items)}):", ""]
        for idx, item in enumerate(items, 1):
            lines.append(f"{idx}. {item['title']}")
            lines.append(f"   Source: {item['source']}")
            if item.get("url"):
                lines.append(f"   Link: {item['url']}")
            if item.get("summary"):
                lines.append(f"   {item['summary'][:140]}")
            lines.append(f"   ID: {item['id']}")
        return ToolResult(success=True, output="\n".join(lines), data={"items": items, "count": len(items)})

    def _mark_read(self, kwargs: dict) -> ToolResult:
        item_id = (kwargs.get("item_id") or "").strip()
        if not item_id:
            return ToolResult(success=False, error="item_id required for mark_read")
        store = self._load_store()
        for watcher in store["watchers"]:
            for item in watcher.get("items", []):
                if item["id"] == item_id:
                    item["read"] = True
                    self._save_store(store)
                    return ToolResult(success=True, output=f"Marked item as read: {item['title']}", data={"item": item})
        return ToolResult(success=False, error=f"Item not found: {item_id}")

    def _remove(self, kwargs: dict) -> ToolResult:
        url = (kwargs.get("url") or "").strip()
        if not url:
            return ToolResult(success=False, error="url required for remove")
        store = self._load_store()
        before = len(store["watchers"])
        store["watchers"] = [w for w in store["watchers"] if w["url"] != url]
        if len(store["watchers"]) == before:
            return ToolResult(success=False, error=f"Watcher not found: {url}")
        self._save_store(store)
        return ToolResult(success=True, output=f"Stopped watching {url}")

    def _fetch_url(self, url: str):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    def _looks_like_feed(self, content: str) -> bool:
        lowered = content.lower()
        return "<rss" in lowered or "<feed" in lowered or "<channel" in lowered

    def _scan_feed(self, watcher: dict, content: str):
        items = self._parse_feed(content)
        existing = {item["id"] for item in watcher.get("items", [])}
        new_items = [item for item in items if item["id"] not in existing]
        watcher.setdefault("items", []).extend(new_items)
        return new_items

    def _scan_page(self, watcher: dict, content: str):
        digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
        prev = watcher.get("last_hash")
        watcher["last_hash"] = digest
        if not prev or prev == digest:
            return []
        title = self._extract_title(content) or watcher["url"]
        item = {
            "id": digest[:16],
            "title": f"Page updated: {title}",
            "url": watcher["url"],
            "published": datetime.now(timezone.utc).isoformat(),
            "summary": "The monitored page content changed.",
            "read": False,
        }
        watcher.setdefault("items", []).insert(0, item)
        return [item]

    def _extract_title(self, html: str) -> str:
        match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        return re.sub(r'\s+', ' ', match.group(1)).strip() if match else ""

    def _parse_feed(self, content: str):
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return []

        items = []
        for node in root.iter():
            tag = node.tag.split("}")[-1]
            if tag not in {"item", "entry"}:
                continue
            title = self._child_text(node, {"title"}) or "(untitled)"
            link = self._entry_link(node)
            published = self._child_text(node, {"pubDate", "published", "updated"}) or datetime.now(timezone.utc).isoformat()
            summary = self._child_text(node, {"description", "summary", "content"}) or ""
            raw_id = self._child_text(node, {"guid", "id"}) or f"{title}|{link}|{published}"
            items.append({
                "id": hashlib.md5(raw_id.encode()).hexdigest()[:16],
                "title": title,
                "url": link,
                "published": published,
                "summary": re.sub(r'<[^>]+>', '', summary).strip(),
                "read": False,
            })
        return items[:20]

    def _child_text(self, node, names):
        for child in list(node):
            if child.tag.split("}")[-1] in names:
                return (child.text or "").strip()
        return ""

    def _entry_link(self, node):
        for child in list(node):
            if child.tag.split("}")[-1] != "link":
                continue
            href = child.attrib.get("href")
            if href:
                return href
            if child.text:
                return child.text.strip()
        return ""
