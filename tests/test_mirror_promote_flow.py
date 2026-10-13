"""Integration tests for mirror promote and delete flows."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.mirror import MirrorManager
from core.cognition.self_modification import SelfModifier


def _make_project(root):
    (root / "core" / "memory").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "aria.py").write_text("print('aria')\n", encoding="utf-8")
    (root / "config.yaml").write_text("aria:\n  name: ARIA\n", encoding="utf-8")
    (root / "core" / "memory" / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")


class TestMirrorPromoteFlow:
    def test_promote_after_pending_write_changes_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        with patch.object(modifier, "_confirm_promote", return_value=False):
            mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 42\n", "test")

        approved = modifier.approve_change_by_id(mod.id)

        assert approved.success
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 42\n"

    def test_promote_refuses_when_live_has_drifted(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        with patch.object(modifier, "_confirm_promote", return_value=False):
            mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 42\n", "test")

        # Modify live file to simulate drift
        (tmp_path / "core" / "memory" / "sample.py").write_text("def value():\n    return 99\n", encoding="utf-8")

        # The legacy mirror.promote() method checks for live drift.
        # _promote_change calls mirror.promote() which calls _ensure_no_live_drift.
        approved = modifier._promote_change(mod.id, "core/memory/sample.py",
                                            "test", "user",
                                            modification_type='promote')

        assert not approved.success
        assert "drift detected" in (approved.error_message or "").lower()
        # Live file should remain at the drifted value
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 99\n"

    def test_delete_after_pending_approval_removes_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        with patch.object(modifier, "_confirm_promote", return_value=False):
            mod = modifier.delete_file("core/memory/sample.py", "delete test")

        # delete_change commits on develop but doesn't store the commit SHA
        # in the Modification. Inject it so promote_selected can cherry-pick.
        commit_sha = mirror.head_sha("develop")
        pending = modifier._load_pending()
        for entry in pending.get("changes", []):
            if entry.get("id") == mod.id:
                entry["commit_sha"] = commit_sha
        modifier._save_pending(pending)

        approved = modifier.approve_change_by_id(mod.id)

        assert approved.success
        assert not (tmp_path / "core" / "memory" / "sample.py").exists()
