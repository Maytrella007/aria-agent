"""
ARIA Test Suite - Interaction Module Tests
============================================

Tests for:
- core/interaction/world_access.py (SystemAccess, WorldInterface)
- core/interaction/session_manager.py (SessionManager)
- core/interaction/perception.py (PerceptionType, dataclasses, atomic_write_json, Vision, PerceptionSystem)
"""

import os
import json
import struct
import zlib
import base64
import platform
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock, patch

import pytest

from core.interaction.world_access import SystemAccess, WorldInterface
from core.interaction.session_manager import SessionManager
from core.interaction.perception import (
    PerceptionType,
    VisualPerception,
    AuditoryPerception,
    atomic_write_json,
    Vision,
    PerceptionSystem,
)


# =============================================================================
# WORLD ACCESS TESTS (~5 tests)
# =============================================================================


class TestSystemAccess:
    """Tests for SystemAccess.get_system_info()."""

    def test_get_system_info_returns_dict(self):
        sa = SystemAccess()
        info = sa.get_system_info()
        assert isinstance(info, dict)

    def test_get_system_info_has_required_keys(self):
        sa = SystemAccess()
        info = sa.get_system_info()
        for key in ("os", "python_version", "home_directory", "current_directory", "user"):
            assert key in info, f"Missing key: {key}"

    def test_get_system_info_os_matches_platform(self):
        sa = SystemAccess()
        info = sa.get_system_info()
        assert info["os"] == platform.system()

    def test_get_system_info_python_version_matches(self):
        sa = SystemAccess()
        info = sa.get_system_info()
        assert info["python_version"] == platform.python_version()

    def test_get_system_info_home_directory_exists(self):
        sa = SystemAccess()
        info = sa.get_system_info()
        assert os.path.isdir(info["home_directory"])


class TestWorldInterface:
    """Tests for WorldInterface.describe_capabilities()."""

    def test_describe_capabilities_returns_string(self):
        wi = WorldInterface()
        caps = wi.describe_capabilities()
        assert isinstance(caps, str)
        assert len(caps) > 0

    def test_describe_capabilities_contains_categories(self):
        wi = WorldInterface()
        caps = wi.describe_capabilities()
        for category in ("INTERNET", "SYSTEM", "OFFICE", "AI"):
            assert category in caps, f"Missing category: {category}"


# =============================================================================
# SESSION MANAGER TESTS (~10 tests)
# =============================================================================


def _make_session_manager():
    """Create a SessionManager with fully mocked dependencies."""
    memory = MagicMock()
    memory.session_start = MagicMock()
    memory.session_end = MagicMock()
    memory.run_memory_maintenance = MagicMock()
    memory.auto_save = MagicMock()
    memory.save_conversation_history = MagicMock()
    memory.load_conversation_history = MagicMock(return_value=[])
    memory.index_conversation_to_chroma = MagicMock()

    continuity = MagicMock()
    continuity.wake_up = MagicMock(return_value=Mock(time_asleep=0, changes_summary=""))
    continuity.go_to_sleep = MagicMock()

    awareness = MagicMock()
    initiative = MagicMock()

    existential = MagicMock()
    existential.is_paused = MagicMock(return_value=False)

    sm = SessionManager(memory, continuity, awareness, initiative, existential)
    return sm, memory, continuity, awareness, initiative, existential


class TestSessionManagerWakeUp:
    """Tests for SessionManager.wake_up()."""

    def test_wake_up_calls_session_start(self):
        sm, memory, continuity, *_ = _make_session_manager()
        sm.wake_up([])
        memory.session_start.assert_called_once()

    def test_wake_up_returns_wake_report(self):
        sm, memory, continuity, *_ = _make_session_manager()
        report = sm.wake_up([])
        assert report is not None
        # The report comes from continuity.wake_up()
        continuity.wake_up.assert_called_once()

    def test_wake_up_calls_memory_maintenance(self):
        sm, memory, *_ = _make_session_manager()
        sm.wake_up([])
        memory.run_memory_maintenance.assert_called_once()

    def test_wake_up_unpauses_if_paused(self):
        sm, memory, continuity, awareness, initiative, existential = _make_session_manager()
        existential.is_paused.return_value = True
        sm.wake_up([])
        existential.unpause.assert_called_once()


class TestSessionManagerGoToSleep:
    """Tests for SessionManager.go_to_sleep()."""

    def test_go_to_sleep_calls_session_end_with_duration(self):
        sm, memory, continuity, *_ = _make_session_manager()
        session_start = datetime.now() - timedelta(minutes=5)
        sm.go_to_sleep([], session_start)
        memory.session_end.assert_called_once()
        duration_arg = memory.session_end.call_args[0][0]
        # Duration should be approximately 300 seconds (5 minutes)
        assert 290 < duration_arg < 310

    def test_go_to_sleep_calls_continuity(self):
        sm, memory, continuity, *_ = _make_session_manager()
        session_start = datetime.now() - timedelta(seconds=60)
        sm.go_to_sleep([], session_start)
        continuity.go_to_sleep.assert_called_once()


class TestSessionManagerAutoSave:
    """Tests for SessionManager.do_auto_save()."""

    def test_do_auto_save_calls_maintenance_and_save(self):
        sm, memory, *_ = _make_session_manager()
        sm.do_auto_save()
        memory.run_memory_maintenance.assert_called_once()
        memory.auto_save.assert_called_once()

    def test_do_auto_save_accepts_kwargs_on_maintenance(self):
        sm, memory, *_ = _make_session_manager()
        sm.do_auto_save()
        # run_memory_maintenance is called with min_decay_interval_hours kwarg
        memory.run_memory_maintenance.assert_called_once_with(min_decay_interval_hours=12)


class TestSessionManagerSaveAfterMessage:
    """Tests for SessionManager.save_after_message() incremental save logic."""

    def test_save_after_message_saves_on_first_message_when_no_last_save(self):
        """First message with _last_save_time=None should trigger save."""
        sm, memory, *_ = _make_session_manager()
        assert sm._last_save_time is None
        sm.save_after_message()
        memory.auto_save.assert_called_once()

    def test_save_after_message_does_not_save_on_message_2_within_30s(self):
        """After a save, messages 1 and 2 should NOT trigger save if within 30s."""
        sm, memory, *_ = _make_session_manager()
        # First call saves (because _last_save_time is None)
        sm.save_after_message()
        memory.auto_save.reset_mock()
        memory.run_memory_maintenance.reset_mock()

        # Second message (counter was reset to 0 after save, now _message_count=1)
        sm.save_after_message()
        memory.auto_save.assert_not_called()

    def test_save_after_message_does_not_save_on_message_2_of_3(self):
        """Message 2 of 3 should not trigger save (counter < 3, within 30s)."""
        sm, memory, *_ = _make_session_manager()
        # First call saves (no last_save_time)
        sm.save_after_message()
        memory.auto_save.reset_mock()

        # Messages 2 and 3 after the reset
        sm.save_after_message()  # counter=1
        sm.save_after_message()  # counter=2
        memory.auto_save.assert_not_called()

    def test_save_after_message_saves_every_3_messages(self):
        """After 3 messages since last save, should trigger save."""
        sm, memory, *_ = _make_session_manager()
        # First call saves
        sm.save_after_message()
        memory.auto_save.reset_mock()

        # 3 more messages should trigger next save
        sm.save_after_message()  # counter=1
        sm.save_after_message()  # counter=2
        sm.save_after_message()  # counter=3 -> triggers save
        memory.auto_save.assert_called_once()

    def test_save_after_message_saves_after_30s_elapsed(self):
        """Should save if more than 30 seconds elapsed since last save."""
        sm, memory, *_ = _make_session_manager()
        # First call saves
        sm.save_after_message()
        memory.auto_save.reset_mock()

        # Simulate 31 seconds passing
        sm._last_save_time = datetime.now() - timedelta(seconds=31)
        sm.save_after_message()  # counter=1 but >30s elapsed
        memory.auto_save.assert_called_once()


# =============================================================================
# PERCEPTION TESTS (~10 tests)
# =============================================================================


class TestPerceptionType:
    """Tests for PerceptionType enum."""

    def test_has_visual(self):
        assert PerceptionType.VISUAL.value == "visual"

    def test_has_auditory(self):
        assert PerceptionType.AUDITORY.value == "auditory"

    def test_has_text(self):
        assert PerceptionType.TEXT.value == "text"


class TestVisualPerception:
    """Tests for VisualPerception dataclass."""

    def test_construction_with_all_fields(self):
        vp = VisualPerception(
            id="test-001",
            timestamp="2026-01-01T00:00:00",
            source="/tmp/test.png",
            description="A test image",
            objects_detected=["person", "table"],
            text_found="Hello",
            emotions_detected=["happy"],
            context="unit test",
            my_reaction="interesting",
            image_type="photo",
            confidence=0.9,
        )
        assert vp.id == "test-001"
        assert vp.source == "/tmp/test.png"
        assert vp.objects_detected == ["person", "table"]
        assert vp.confidence == 0.9


class TestAuditoryPerception:
    """Tests for AuditoryPerception dataclass."""

    def test_construction_with_all_fields(self):
        ap = AuditoryPerception(
            id="aud-001",
            timestamp="2026-01-01T00:00:00",
            source="/tmp/test.wav",
            transcription="Hello world",
            speaker_count=1,
            language="en",
            tone="casual",
            summary="Greeting",
            duration_seconds=3.5,
            audio_type="speech",
        )
        assert ap.id == "aud-001"
        assert ap.transcription == "Hello world"
        assert ap.duration_seconds == 3.5


class TestAtomicWriteJson:
    """Tests for atomic_write_json()."""

    def test_writes_valid_json(self, tmp_path):
        path = str(tmp_path / "test.json")
        data = {"key": "value", "number": 42}
        atomic_write_json(path, data)

        with open(path, "r") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_writes_list_data(self, tmp_path):
        path = str(tmp_path / "list.json")
        data = [1, 2, 3, "four"]
        atomic_write_json(path, data)

        with open(path, "r") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_overwrites_existing_file(self, tmp_path):
        path = str(tmp_path / "overwrite.json")
        atomic_write_json(path, {"old": True})
        atomic_write_json(path, {"new": True})

        with open(path, "r") as f:
            loaded = json.load(f)
        assert loaded == {"new": True}

    def test_handles_error_on_bad_directory(self):
        """Writing to a non-existent directory should raise."""
        with pytest.raises(Exception):
            atomic_write_json("/nonexistent/dir/file.json", {"a": 1})


def _make_minimal_png() -> bytes:
    """Create a valid 1x1 pixel red PNG file in memory."""
    # PNG signature
    signature = b'\x89PNG\r\n\x1a\n'

    def _chunk(chunk_type, data):
        c = chunk_type + data
        crc = struct.pack('>I', zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack('>I', len(data)) + c + crc

    # IHDR: 1x1, 8-bit RGB
    ihdr_data = struct.pack('>IIBBBBB', 1, 1, 8, 2, 0, 0, 0)
    ihdr = _chunk(b'IHDR', ihdr_data)

    # IDAT: single red pixel, filter byte 0
    raw_data = b'\x00\xff\x00\x00'  # filter=0, R=255, G=0, B=0
    compressed = zlib.compress(raw_data)
    idat = _chunk(b'IDAT', compressed)

    # IEND
    iend = _chunk(b'IEND', b'')

    return signature + ihdr + idat + iend


class TestVision:
    """Tests for Vision class."""

    def test_init_without_api_client(self, tmp_path):
        v = Vision(api_client=None, data_dir=str(tmp_path))
        assert v.client is None
        assert os.path.isdir(v.perceptions_dir)

    def test_encode_image_with_real_png(self, tmp_path):
        """Test _encode_image with a real 1x1 pixel PNG."""
        png_path = str(tmp_path / "pixel.png")
        png_bytes = _make_minimal_png()
        with open(png_path, "wb") as f:
            f.write(png_bytes)

        v = Vision(api_client=None, data_dir=str(tmp_path))
        encoded, mime = v._encode_image(png_path)

        # Verify base64 round-trip
        decoded = base64.standard_b64decode(encoded)
        assert decoded == png_bytes
        assert mime == "image/png"

    def test_encode_image_unknown_extension(self, tmp_path):
        """Unknown extension defaults to image/jpeg."""
        file_path = str(tmp_path / "image.qzx")
        with open(file_path, "wb") as f:
            f.write(b"\x00\x01\x02")

        v = Vision(api_client=None, data_dir=str(tmp_path))
        _, mime = v._encode_image(file_path)
        assert mime == "image/jpeg"


class TestPerceptionSystem:
    """Tests for PerceptionSystem."""

    def test_describe_capabilities_returns_string(self, tmp_path):
        ps = PerceptionSystem(api_client=None, data_dir=str(tmp_path))
        desc = ps.describe_capabilities()
        assert isinstance(desc, str)
        assert "VISION" in desc
        assert "HEARING" in desc

    def test_detect_capabilities_returns_expected_keys(self, tmp_path):
        ps = PerceptionSystem(api_client=None, data_dir=str(tmp_path))
        caps = ps._detect_capabilities()
        for key in ("vision", "hearing_files", "hearing_microphone", "audio_conversion", "image_processing"):
            assert key in caps
        # All values should be booleans
        for v in caps.values():
            assert isinstance(v, bool)
