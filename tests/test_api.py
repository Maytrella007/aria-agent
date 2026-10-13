"""
ARIA API Module Tests
=====================

Unit tests for pure functions and helpers across the API layer:
- core.api.errors          — api_error() factory
- core.api.conversation_store — JSON file persistence
- core.api.server          — _humanize_elapsed() time formatting
- core.api.memories_router — _memory_to_item() conversion
- core.api.mirror_router   — _enrich_with_tier(), _mod_to_dict()
"""

import json
import os
import time

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from dataclasses import dataclass


# =========================================================================
# 1. core.api.errors — api_error()
# =========================================================================

from core.api.errors import api_error, APIErrorBody


class TestApiError:
    """Tests for the api_error() HTTPException factory."""

    def test_default_status_code(self):
        exc = api_error("bad_request")
        assert exc.status_code == 400

    def test_custom_status_code(self):
        exc = api_error("not_found", "Resource missing", 404)
        assert exc.status_code == 404

    def test_detail_body_structure(self):
        exc = api_error("validation_failed", "Invalid input", 422)
        body = exc.detail
        assert body["error"] == "validation_failed"
        assert body["detail"] == "Invalid input"
        assert body["status_code"] == 422

    def test_detail_none(self):
        exc = api_error("server_error", status_code=500)
        assert exc.detail["detail"] is None
        assert exc.detail["error"] == "server_error"
        assert exc.detail["status_code"] == 500

    def test_503_service_unavailable(self):
        exc = api_error("service_unavailable", "Memory not ready", 503)
        assert exc.status_code == 503
        assert exc.detail["error"] == "service_unavailable"


# =========================================================================
# 2. core.api.conversation_store — file persistence
# =========================================================================

from core.api import conversation_store
from core.api.conversation_store import (
    _safe_session_id,
    save_conversation,
    list_conversations,
    get_conversation,
)


class TestSafeSessionId:
    """Tests for _safe_session_id() sanitization."""

    def test_normal_id(self):
        assert _safe_session_id("abc123") == "abc123"

    def test_dashes_and_underscores(self):
        assert _safe_session_id("run-42_v2") == "run-42_v2"

    def test_path_traversal_dots(self):
        result = _safe_session_id("../../etc/passwd")
        assert "/" not in result
        assert ".." not in result

    def test_absolute_path(self):
        result = _safe_session_id("/etc/passwd")
        assert "/" not in result

    def test_special_chars_stripped(self):
        result = _safe_session_id("hello world!@#$%")
        assert result == "helloworld"

    def test_empty_after_sanitize_raises(self):
        with pytest.raises(ValueError):
            _safe_session_id("!@#$%^&*()")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            _safe_session_id("")


class TestSaveAndGetConversation:
    """Tests for save_conversation() and get_conversation() round-trip."""

    def test_round_trip(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            messages = [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there!"},
            ]
            save_conversation("sess-001", messages)
            result = get_conversation("sess-001")

            assert result is not None
            assert result["id"] == "sess-001"
            assert result["message_count"] == 2
            assert result["messages"][0]["content"] == "Hello"
            assert result["messages"][1]["content"] == "Hi there!"

    def test_empty_messages(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            save_conversation("empty-sess", [])
            result = get_conversation("empty-sess")

            assert result is not None
            assert result["message_count"] == 0
            assert result["messages"] == []

    def test_unicode_content(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            messages = [
                {"role": "user", "content": "Hola, como estas?"},
                {"role": "assistant", "content": "Tres bien, merci!"},
            ]
            save_conversation("unicode-sess", messages)
            result = get_conversation("unicode-sess")

            assert result["messages"][0]["content"] == "Hola, como estas?"
            assert result["messages"][1]["content"] == "Tres bien, merci!"

    def test_timestamps_added_when_missing(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            messages = [{"role": "user", "content": "No timestamp"}]
            save_conversation("ts-sess", messages)
            result = get_conversation("ts-sess")

            assert "ts" in result["messages"][0]
            assert result["started_at"] is not None

    def test_existing_timestamps_preserved(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            custom_ts = "2026-01-01T00:00:00+00:00"
            messages = [{"role": "user", "content": "Custom ts", "ts": custom_ts}]
            save_conversation("custom-ts", messages)
            result = get_conversation("custom-ts")

            assert result["messages"][0]["ts"] == custom_ts

    def test_get_nonexistent_returns_none(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            assert get_conversation("does-not-exist") is None

    def test_get_invalid_id_returns_none(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            assert get_conversation("!@#$") is None


class TestListConversations:
    """Tests for list_conversations() pagination and ordering."""

    def test_empty_directory(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            result = list_conversations()
            assert result["items"] == []
            assert result["total"] == 0

    def test_pagination_limit(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            for i in range(5):
                save_conversation(f"sess-{i:03d}", [{"role": "user", "content": f"msg {i}"}])

            result = list_conversations(limit=2, offset=0)
            assert len(result["items"]) == 2
            assert result["total"] == 5
            assert result["limit"] == 2
            assert result["offset"] == 0

    def test_pagination_offset(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            for i in range(5):
                save_conversation(f"sess-{i:03d}", [{"role": "user", "content": f"msg {i}"}])

            result = list_conversations(limit=10, offset=3)
            assert len(result["items"]) == 2
            assert result["total"] == 5

    def test_ordered_by_mtime_descending(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            save_conversation("old", [{"role": "user", "content": "old"}])
            # Touch the file to ensure different mtime
            old_path = tmp_path / "old.json"
            os.utime(str(old_path), (1000, 1000))

            save_conversation("new", [{"role": "user", "content": "new"}])

            result = list_conversations()
            assert result["items"][0]["id"] == "new"
            assert result["items"][1]["id"] == "old"

    def test_first_message_preview(self, tmp_path):
        with patch.object(conversation_store, "STORE_PATH", str(tmp_path)):
            messages = [
                {"role": "assistant", "content": "System greeting"},
                {"role": "user", "content": "This is the user message"},
            ]
            save_conversation("preview-test", messages)

            result = list_conversations()
            assert result["items"][0]["first_message_preview"] == "This is the user message"


# =========================================================================
# 3. core.api.server — _humanize_elapsed()
# =========================================================================

from core.api.server import _humanize_elapsed


class TestHumanizeElapsed:
    """Tests for the _humanize_elapsed() time formatting helper."""

    def test_seconds_ago(self):
        ts = time.time() - 30
        assert _humanize_elapsed(ts) == "30s ago"

    def test_minutes_ago(self):
        ts = time.time() - 180
        assert _humanize_elapsed(ts) == "3m ago"

    def test_hours_ago(self):
        ts = time.time() - 7200
        assert _humanize_elapsed(ts) == "2h ago"

    def test_days_ago(self):
        ts = time.time() - 172800
        assert _humanize_elapsed(ts) == "2d ago"

    def test_none_returns_never(self):
        assert _humanize_elapsed(None) == "never"

    def test_iso_string_input(self):
        past = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # Use a fixed epoch that is clearly in the past
        ts = time.time() - 3700
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        result = _humanize_elapsed(iso)
        assert result.endswith("ago")

    def test_invalid_input_returns_unknown(self):
        assert _humanize_elapsed("not-a-timestamp") == "unknown"

    def test_zero_seconds(self):
        ts = time.time()
        result = _humanize_elapsed(ts)
        assert result == "0s ago"


# =========================================================================
# 4. core.api.memories_router — _memory_to_item()
# =========================================================================

from core.api.memories_router import _memory_to_item


class TestMemoryToItem:
    """Tests for _memory_to_item() conversion from memory object to dict."""

    def _make_mock_memory(self, **overrides):
        """Create a mock memory with a to_dict() method."""
        defaults = {
            "id": "mem-001",
            "content": "Test memory",
            "context": "test context",
            "emotional_tone": "curious",
            "emotional_intensity": 0.7,
            "origin": "lived",
            "involves_people": ["alice"],
            "tags": ["test"],
            "memory_strength": 0.9,
            "times_recalled": 3,
            "timestamp": "2026-01-01T00:00:00",
            "consolidation_count": 1,
            "importance": 0.8,
            "is_mine": True,
            "last_recalled": "2026-01-02T00:00:00",
            "connected_memories": ["mem-002"],
            "relationship_impact": {"alice": 0.1},
            "duration_feeling": "long",
            "confidence": 0.95,
            "consolidated": True,
            "encoding_context": "conversation",
        }
        defaults.update(overrides)
        mock = MagicMock()
        mock.to_dict.return_value = defaults
        return mock

    def test_full_conversion(self):
        mem = self._make_mock_memory()
        item = _memory_to_item(mem)

        assert item["id"] == "mem-001"
        assert item["content"] == "Test memory"
        assert item["emotional_tone"] == "curious"
        assert item["strength"] == 0.9
        assert item["recall_count"] == 3
        assert item["created_at"] == "2026-01-01T00:00:00"
        assert item["tags"] == ["test"]
        assert item["involves_people"] == ["alice"]
        assert item["consolidated"] is True

    def test_missing_optional_fields_use_defaults(self):
        mock = MagicMock()
        mock.to_dict.return_value = {
            "id": "mem-minimal",
            "content": "Minimal",
        }
        item = _memory_to_item(mock)

        assert item["id"] == "mem-minimal"
        assert item["context"] == ""
        assert item["emotional_intensity"] == 0.5
        assert item["involves_people"] == []
        assert item["tags"] == []
        assert item["strength"] == 1.0
        assert item["recall_count"] == 0
        assert item["importance"] == 0.5
        assert item["confidence"] == 0.9
        assert item["consolidated"] is False

    def test_encoding_context_preserved(self):
        mem = self._make_mock_memory(encoding_context="deep reflection")
        item = _memory_to_item(mem)
        assert item["encoding_context"] == "deep reflection"


# =========================================================================
# 5. core.api.mirror_router — _enrich_with_tier(), _mod_to_dict()
# =========================================================================

from core.api.mirror_router import _enrich_with_tier, _mod_to_dict


class TestEnrichWithTier:
    """Tests for _enrich_with_tier() tier classification."""

    def test_tier3_meta_file(self):
        change = {"target_file": "core/cognition/mirror.py"}
        result = _enrich_with_tier(change)
        assert result["tier"] == 3
        assert result["tier_label"] == "meta"

    def test_tier2_behavioral_file(self):
        change = {"target_file": "core/api/server.py"}
        result = _enrich_with_tier(change)
        assert result["tier"] == 2
        assert result["tier_label"] == "behavioral"

    def test_tier1_cosmetic_file(self):
        change = {"target_file": "docs/README.md"}
        result = _enrich_with_tier(change)
        assert result["tier"] == 1
        assert result["tier_label"] == "cosmetic"

    def test_empty_target_file_defaults_tier1(self):
        change = {"target_file": ""}
        result = _enrich_with_tier(change)
        assert result["tier"] == 1

    def test_missing_target_file_defaults_tier1(self):
        change = {"other_key": "value"}
        result = _enrich_with_tier(change)
        assert result["tier"] == 1

    def test_preserves_existing_fields(self):
        change = {"target_file": "tests/test_foo.py", "id": "mod-99", "reason": "refactor"}
        result = _enrich_with_tier(change)
        assert result["id"] == "mod-99"
        assert result["reason"] == "refactor"
        assert "tier" in result
        assert "tier_label" in result


class TestModToDict:
    """Tests for _mod_to_dict() Modification dataclass conversion."""

    def test_with_to_dict_method(self):
        mock = MagicMock()
        mock.to_dict.return_value = {"id": "mod-1", "target_file": "foo.py"}
        result = _mod_to_dict(mock)
        assert result == {"id": "mod-1", "target_file": "foo.py"}
        mock.to_dict.assert_called_once()

    def test_fallback_getattr(self):
        @dataclass
        class FakeMod:
            id: str = "mod-2"
            timestamp: str = "2026-01-01"
            target_file: str = "bar.py"
            modification_type: str = "edit"
            reason: str = "cleanup"
            initiated_by: str = "aria"
            success: bool = True
            error_message: str = None
            status: str = "promoted"
            validation_result: str = None

        mod = FakeMod()
        result = _mod_to_dict(mod)

        assert result["id"] == "mod-2"
        assert result["target_file"] == "bar.py"
        assert result["modification_type"] == "edit"
        assert result["success"] is True
        assert result["status"] == "promoted"

    def test_fallback_missing_attrs(self):
        """Object with no to_dict and no matching attributes uses defaults."""

        class Bare:
            pass

        mod = Bare()
        result = _mod_to_dict(mod)
        assert result["id"] == ""
        assert result["success"] is False
        assert result["error_message"] is None
