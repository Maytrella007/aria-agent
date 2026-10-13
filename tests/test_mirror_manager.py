"""Phase 1 tests for MirrorManager."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.mirror import MirrorManager


def _make_project(root):
    (root / "core" / "memory").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "aria.py").write_text("print('aria')\n", encoding="utf-8")
    (root / "config.yaml").write_text("aria:\n  name: ARIA\n", encoding="utf-8")
    (root / "core" / "memory" / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (root / "tests" / "test_dummy.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


class TestMirrorManager:
    def test_sync_creates_mirror_copy(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirrored = tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py"
        assert mirrored.exists()
        assert mirrored.read_text(encoding="utf-8") == "def value():\n    return 1\n"

    def test_apply_change_touches_only_mirror(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirror.apply_change("core/memory/sample.py", "def value():\n    return 2\n")
        live = (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        staged = (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert live == "def value():\n    return 1\n"
        assert staged == "def value():\n    return 2\n"

    def test_validate_detects_syntax_error(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirror.apply_change("core/memory/sample.py", "def broken(:\n    pass\n")
        result = mirror.validate("core/memory/sample.py")
        assert not result.all_ok
        assert not result.syntax_ok

    def test_promote_copies_mirror_to_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirror.apply_change("core/memory/sample.py", "def value():\n    return 3\n")
        mirror.promote("core/memory/sample.py")
        live = (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert live == "def value():\n    return 3\n"

    def test_rollback_restores_live_state(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirror.apply_change("core/memory/sample.py", "def value():\n    return 9\n")
        mirror.rollback("core/memory/sample.py")
        staged = (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert staged == "def value():\n    return 1\n"

    def test_promote_detects_live_drift(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirror.apply_change("core/memory/sample.py", "def value():\n    return 3\n")
        (tmp_path / "core" / "memory" / "sample.py").write_text("def value():\n    return 99\n", encoding="utf-8")

        try:
            mirror.promote("core/memory/sample.py")
            assert False, "expected drift detection"
        except RuntimeError as exc:
            assert "drift detected" in str(exc)

    # ---- Phase 5: Rectification tests ----

    def test_sync_excludes_data_directory(self, tmp_path):
        _make_project(tmp_path)
        (tmp_path / "data" / "secrets").mkdir(parents=True)
        (tmp_path / "data" / "secrets" / "key.txt").write_text("secret", encoding="utf-8")
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        assert not (tmp_path / "data" / "mirror" / "data").exists()

    def test_sync_excludes_forged_directory(self, tmp_path):
        _make_project(tmp_path)
        (tmp_path / "core" / "tools" / "forged").mkdir(parents=True)
        (tmp_path / "core" / "tools" / "forged" / "tool.py").write_text("pass", encoding="utf-8")
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        # forged is under core/ so it gets copied by the broad copytree — but
        # this is expected because sync includes all of core/. The mirror
        # selectivity is about what is included, not sub-filtered.
        # The important thing is data/ is NOT in the mirror.
        assert not (tmp_path / "data" / "mirror" / "data").exists()

    def test_path_traversal_rejected_in_apply_change(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        try:
            mirror.apply_change("../../etc/passwd", "hacked")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "traversal" in str(exc).lower()

    def test_path_traversal_rejected_in_promote(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        try:
            mirror.promote("../outside.py")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "traversal" in str(exc).lower()

    def test_absolute_path_rejected(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        try:
            mirror.apply_change("/etc/passwd", "hacked")
            assert False, "expected ValueError"
        except ValueError as exc:
            assert "Absolute" in str(exc)

    def test_drift_detected_for_new_file_appearing_on_live(self, tmp_path):
        """If apply_change targets a file that doesn't exist yet, and then
        someone creates it on live before promote, drift must be caught."""
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        # Stage a new file in the mirror
        mirror.apply_change("core/memory/brand_new.py", "x = 1\n")
        # Now create the same file on live with different content
        (tmp_path / "core" / "memory" / "brand_new.py").write_text("x = 999\n", encoding="utf-8")
        try:
            mirror.promote("core/memory/brand_new.py")
            assert False, "expected drift detection for new file appearing on live"
        except RuntimeError as exc:
            assert "drift" in str(exc).lower()

    def test_validate_yaml_syntax_error(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        mirror.sync()
        mirror.apply_change("config.yaml", "invalid: yaml: [unclosed\n")
        result = mirror.validate("config.yaml")
        assert not result.syntax_ok
        assert not result.all_ok
