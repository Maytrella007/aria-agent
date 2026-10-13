"""Phase 1 tests for SelfModifier mirror pipeline."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.mirror import MirrorManager
from core.cognition.self_modification import SelfModifier


def _make_project(root):
    (root / "core" / "memory").mkdir(parents=True)
    (root / "core" / "cognition").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "aria.py").write_text("print('aria')\n", encoding="utf-8")
    (root / "config.yaml").write_text("aria:\n  name: ARIA\n", encoding="utf-8")
    (root / "core" / "memory" / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")


class TestSelfModifierMirror:
    def test_write_file_pending_approval_does_not_touch_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        with patch.object(modifier, "_confirm_promote", return_value=False):
            mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 2\n", "test")
        assert mod.success
        assert mod.status == "validated_pending_approval"
        live = (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        staged = (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert live == "def value():\n    return 1\n"
        assert staged == "def value():\n    return 2\n"

    def test_write_file_with_approval_promotes_to_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        with patch.object(modifier, "_confirm_promote", return_value=True):
            mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 5\n", "test")
        assert mod.success
        assert mod.status == "applied"
        live = (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert live == "def value():\n    return 5\n"

    def test_approve_change_by_id_promotes_matching_pending_change(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        with patch.object(modifier, "_confirm_promote", return_value=False):
            pending_mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 7\n", "test")

        approved = modifier.approve_change_by_id(pending_mod.id)

        assert approved.success
        assert approved.id == pending_mod.id
        assert approved.validation_result == pending_mod.validation_result
        assert modifier.get_pending_change(pending_mod.id) is None
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 7\n"

    def test_approve_change_by_id_keeps_pending_if_promote_fails(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        with patch.object(modifier, "_confirm_promote", return_value=False):
            pending_mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 8\n", "test")

        # approve_change_by_id delegates to promote_selected which uses
        # cherry_pick_branches_to_main — mock that to simulate failure.
        fail_result = {"success": False, "error": "boom", "promoted_files": [],
                       "promoted_branches": [], "conflict": False,
                       "conflict_branch": "", "conflict_files": []}
        with patch.object(mirror, "cherry_pick_branches_to_main", return_value=fail_result):
            approved = modifier.approve_change_by_id(pending_mod.id)

        assert not approved.success
        assert approved.id == pending_mod.id
        assert modifier.get_pending_change(pending_mod.id) is not None
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"

    def test_reject_change_removes_pending_and_rolls_back_mirror(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        with patch.object(modifier, "_confirm_promote", return_value=False):
            pending_mod = modifier.write_file("core/memory/sample.py", "def value():\n    return 11\n", "test")

        rejected = modifier.reject_change(pending_mod.id)

        assert rejected.success
        assert rejected.status == "rejected"
        # reject_change flips the YAML status so list_pending_changes no
        # longer surfaces the entry, but it remains in the store for audit.
        assert modifier.get_pending_change(pending_mod.id) is None
        # In the notebook-and-book model, rejected commits stay in develop
        # — the mirror file is NOT rolled back (the history is preserved).
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"

    def test_approve_change_requires_pending_entry_for_path(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        result = modifier.approve_change("core/memory/sample.py")

        assert not result.success
        assert result.status == "failed"

    def test_structural_delete_pending_approval_does_not_touch_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        with patch.object(modifier, "_confirm_promote", return_value=False):
            mod = modifier.delete_file("core/memory/sample.py", "delete test")

        assert mod.success
        assert mod.status == "validated_pending_approval"
        assert (tmp_path / "core" / "memory" / "sample.py").exists()
        assert not (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").exists()
        assert modifier.get_pending_change(mod.id) is not None

    def test_structural_delete_approval_removes_live_file(self, tmp_path):
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

    def test_structural_delete_blocked_when_dependent_import_breaks(self, tmp_path):
        _make_project(tmp_path)
        (tmp_path / "core" / "memory" / "consumer.py").write_text(
            "from core.memory.sample import value\n\ndef use():\n    return value()\n",
            encoding="utf-8",
        )
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        mod = modifier.delete_file("core/memory/sample.py", "delete test")

        assert not mod.success
        assert mod.status == "failed"
        assert (tmp_path / "core" / "memory" / "sample.py").exists()
        assert (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").exists()

    def test_write_file_invalid_syntax_rolls_back(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": False})
        mod = modifier.write_file("core/memory/sample.py", "def broken(:\n    pass\n", "bad test")
        assert not mod.success
        assert mod.status == "failed"
        live = (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        staged = (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert live == "def value():\n    return 1\n"
        assert staged == "def value():\n    return 1\n"

    def test_modify_function_uses_mirror_pipeline(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        with patch.object(modifier, "_confirm_promote", return_value=False):
            mod = modifier.modify_function("core/memory/sample.py", "value", "def value():\n    return 10", "update")
        assert mod.success
        assert mod.status == "validated_pending_approval"

    def test_non_structural_write_still_writes_live_directly(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})
        mod = modifier.write_file("notes.txt", "hello", "test")
        assert mod.success
        assert mod.status == "applied"
        assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"

    def test_post_promote_state_requires_restart_for_core_runtime_changes(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        with patch.object(modifier, "_confirm_promote", return_value=True):
            mod = modifier.write_file("core/cognition/runtime.py", "def boot():\n    return 'ok'\n", "runtime update")

        state = modifier.get_post_promote_state()

        assert mod.success
        assert state["recommended_action"] == "restart"
        assert state["requires_restart"] is True
        assert "core/cognition/runtime.py" in state["affected_paths"]

    def test_post_promote_state_marks_reload_optional_for_non_runtime_python(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        mod = modifier.write_file("core/helpers.py", "def helper():\n    return 'ok'\n", "helper update")
        state = modifier.get_post_promote_state()

        assert mod.success
        assert state["recommended_action"] == "reload_optional"
        assert state["requires_restart"] is False
        assert "core.helpers" in state["reload_modules"]

    def test_mark_post_promote_observed_sets_observation_metadata(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        mod = modifier.write_file("core/helpers.py", "def helper():\n    return 'ok'\n", "helper update")
        observed = modifier.mark_post_promote_observed("test")

        assert mod.success
        assert observed["observation_context"] == "test"
        assert observed.get("observed_at")

    # ---- Phase 5: Rectification tests ----

    def test_restore_from_backup_structural_goes_through_mirror(self, tmp_path):
        """restore_from_backup for structural files must route through mirror."""
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        # Create a backup manually
        backup_dir = tmp_path / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "20260101_000000_core_memory_sample.py").write_text(
            "def value():\n    return 999\n", encoding="utf-8"
        )

        with patch.object(modifier, "_confirm_promote", return_value=False):
            result = modifier.restore_from_backup("core/memory/sample.py")

        # Should succeed but NOT touch live — must be pending approval
        assert result is True
        live = (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8")
        assert live == "def value():\n    return 1\n"  # Live unchanged
        pending = modifier.list_pending_changes()
        assert len(pending) >= 1

    def test_restore_from_backup_non_structural_writes_directly(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        modifier = SelfModifier(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        # Write a non-structural file and create backup
        (tmp_path / "notes.txt").write_text("original", encoding="utf-8")
        backup_dir = tmp_path / "data" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        (backup_dir / "20260101_000000_notes.txt").write_text("restored", encoding="utf-8")

        result = modifier.restore_from_backup("notes.txt")

        assert result is True
        assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "restored"

    def test_mirror_always_created_even_without_explicit_injection(self, tmp_path):
        """SelfModifier must always have a mirror — no disabled mode."""
        _make_project(tmp_path)
        modifier = SelfModifier(project_root=str(tmp_path))
        assert modifier.mirror is not None
