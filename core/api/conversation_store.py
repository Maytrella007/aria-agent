"""
ARIA Conversation Store — Simple JSON-file persistence for chat sessions.

Each conversation is saved as ``data/conversations/{session_id}.json``
with the following schema::

    {
        "id": "abc12345",
        "started_at": "2026-04-08T14:30:00Z",
        "messages": [
            {"role": "user", "content": "Hello", "ts": "..."},
            {"role": "assistant", "content": "Hi!", "ts": "..."}
        ]
    }

The module is intentionally dependency-free (no ORM, no DB) so it can be
imported from server.py with zero extra setup.
"""

import json
import logging
import os
import time

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default store directory — resolved relative to project root at runtime.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STORE_PATH = os.path.join(_PROJECT_ROOT, "data", "conversations")


def _ensure_dir() -> None:
    """Create the store directory if it doesn't exist."""
    os.makedirs(STORE_PATH, exist_ok=True)


def _safe_session_id(session_id: str) -> str:
    """Sanitize session_id to prevent path traversal.

    Strips everything that isn't alphanumeric, dash, or underscore.
    Raises ValueError if the result is empty.
    """
    import re
    clean = re.sub(r"[^a-zA-Z0-9_-]", "", session_id)
    if not clean:
        raise ValueError(f"Invalid session_id: {session_id!r}")
    return clean


def save_conversation(session_id: str, messages: list) -> str:
    """Save a conversation to disk as JSON.

    Parameters
    ----------
    session_id:
        Unique run / session identifier (used as filename stem).
    messages:
        List of message dicts — each should have at least ``role`` and
        ``content`` keys.  A ``ts`` (ISO timestamp) is added automatically
        if missing.

    Returns
    -------
    str
        The absolute path of the written file.
    """
    _ensure_dir()
    session_id = _safe_session_id(session_id)
    filepath = os.path.join(STORE_PATH, f"{session_id}.json")

    now_iso = datetime.now(timezone.utc).isoformat()

    # Normalise messages — ensure every entry has a timestamp.
    normalised: List[dict] = []
    for msg in messages:
        entry = dict(msg)  # shallow copy
        if "ts" not in entry:
            entry["ts"] = now_iso
        normalised.append(entry)

    # Determine started_at from first message or now.
    started_at = normalised[0]["ts"] if normalised else now_iso

    payload = {
        "id": session_id,
        "started_at": started_at,
        "messages": normalised,
    }

    try:
        with open(filepath, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        logger.debug("Saved conversation %s (%d messages)", session_id, len(normalised))
    except Exception as exc:
        logger.error("Failed to save conversation %s: %s", session_id, exc)

    return filepath


def list_conversations(limit: int = 20, offset: int = 0) -> Dict:
    """List saved conversations, most recent first.

    Returns
    -------
    dict
        ``{items: [...], total: N, limit: N, offset: N}``
        Each item contains ``id``, ``started_at``, ``message_count``, and
        ``first_message_preview`` (first 120 chars of the first user message).
    """
    _ensure_dir()

    # Collect all .json files and sort by mtime descending (most recent first).
    files: List[Path] = sorted(
        Path(STORE_PATH).glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    total = len(files)
    page = files[offset : offset + limit]

    items: List[dict] = []
    for fp in page:
        try:
            with open(fp, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            messages = data.get("messages", [])
            # Find first user message for preview.
            preview = ""
            for m in messages:
                if m.get("role") == "user" and m.get("content"):
                    preview = m["content"][:120]
                    break
            items.append({
                "id": data.get("id", fp.stem),
                "started_at": data.get("started_at"),
                "message_count": len(messages),
                "first_message_preview": preview,
            })
        except Exception as exc:
            logger.warning("Skipping corrupt conversation file %s: %s", fp.name, exc)

    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_conversation(session_id: str) -> Optional[Dict]:
    """Load a full conversation from disk.

    Returns
    -------
    dict or None
        ``{id, messages, started_at, message_count}`` if found, else ``None``.
    """
    _ensure_dir()
    try:
        session_id = _safe_session_id(session_id)
    except ValueError:
        return None
    filepath = os.path.join(STORE_PATH, f"{session_id}.json")
    if not os.path.isfile(filepath):
        return None

    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        messages = data.get("messages", [])
        return {
            "id": data.get("id", session_id),
            "messages": messages,
            "started_at": data.get("started_at"),
            "message_count": len(messages),
        }
    except Exception as exc:
        logger.error("Failed to load conversation %s: %s", session_id, exc)
        return None
