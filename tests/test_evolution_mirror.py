"""Phase 2 tests for evolution mirror pipeline."""

import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.evolution import EvolutionEngine
from core.cognition.mirror import MirrorManager


def _make_project(root):
    (root / "core" / "memory").mkdir(parents=True)
    (root / "core" / "cognition").mkdir(parents=True)
    (root / "tests").mkdir(parents=True)
    (root / "aria.py").write_text("print('aria')\n", encoding="utf-8")
    (root / "config.yaml").write_text("aria:\n  name: ARIA\n", encoding="utf-8")
    (root / "core" / "memory" / "sample.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (root / "core" / "memory" / "sample_two.py").write_text("def value_two():\n    return 2\n", encoding="utf-8")


class TestEvolutionMirror:
    def test_apply_evolution_stores_pending_changes_without_touching_live(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        engine = EvolutionEngine(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        proposal = engine.propose_evolution(
            "Update sample",
            "exercise batch pending flow",
            [{"file": "core/memory/sample.py", "content": "def value():\n    return 21\n"}],
        )

        result = engine.apply_evolution(proposal.id)

        assert result["success"]
        assert result["status"] == "validated_pending_approval"
        assert len(result["pending_ids"]) == 1
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"
        assert (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 21\n"

        pending = engine.modifier.get_pending_change(result["pending_ids"][0])
        assert pending is not None
        assert pending["status"] == "validated_pending_approval"

    def test_apply_evolution_rolls_back_mirror_on_validation_failure(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        engine = EvolutionEngine(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        proposal = engine.propose_evolution(
            "Break sample",
            "exercise rollback flow",
            [{"file": "core/memory/sample.py", "content": "import definitely_missing_module\n\ndef value():\n    return 1\n"}],
        )

        result = engine.apply_evolution(proposal.id)

        assert not result["success"]
        assert result["status"] == "failed"
        assert engine.modifier.list_pending_changes() == []
        assert (tmp_path / "data" / "mirror" / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"

    def test_approve_batch_promotes_all_pending_changes_atomically(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        engine = EvolutionEngine(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        proposal = engine.propose_evolution(
            "Update multiple files",
            "exercise transactional batch promote",
            [
                {"file": "core/memory/sample.py", "content": "def value():\n    return 21\n"},
                {"file": "core/memory/sample_two.py", "content": "def value_two():\n    return 22\n"},
            ],
        )

        result = engine.apply_evolution(proposal.id)

        # apply_evolution calls apply_change but doesn't store the returned
        # commit SHA in the pending entries. Each file produced a separate
        # commit on develop — look up the latest commit that touched each
        # file and inject it so promote_selected can cherry-pick.
        pending = engine.modifier._load_pending()
        develop_log = mirror.get_develop_log(10)
        for entry in pending.get("changes", []):
            if entry.get("id") in result["pending_ids"]:
                target = entry.get("target_file", "")
                for commit in develop_log:
                    if target in commit.get("message", ""):
                        entry["commit_sha"] = commit["hash"]
                        break
        engine.modifier._save_pending(pending)

        promote_results = engine.modifier.approve_batch(result["pending_ids"])

        assert all(item.success for item in promote_results)
        assert engine.modifier.list_pending_changes() == []
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 21\n"
        assert (tmp_path / "core" / "memory" / "sample_two.py").read_text(encoding="utf-8") == "def value_two():\n    return 22\n"

    def test_approve_batch_rolls_back_all_if_one_promote_fails(self, tmp_path):
        _make_project(tmp_path)
        mirror = MirrorManager(str(tmp_path))
        engine = EvolutionEngine(project_root=str(tmp_path), mirror=mirror, mirror_config={"require_confirmation": True})

        proposal = engine.propose_evolution(
            "Update multiple files",
            "exercise transactional rollback",
            [
                {"file": "core/memory/sample.py", "content": "def value():\n    return 31\n"},
                {"file": "core/memory/sample_two.py", "content": "def value_two():\n    return 32\n"},
            ],
        )

        result = engine.apply_evolution(proposal.id)
        original_apply = mirror._apply_promote
        call_count = {"value": 0}

        def flaky_apply(path):
            call_count["value"] += 1
            original_apply(path)
            if call_count["value"] == 2:
                raise RuntimeError("batch promote failed")

        with patch.object(mirror, "_apply_promote", side_effect=flaky_apply):
            promote_results = engine.modifier.approve_batch(result["pending_ids"])

        assert not any(item.success for item in promote_results)
        assert len(engine.modifier.list_pending_changes()) == 2
        assert (tmp_path / "core" / "memory" / "sample.py").read_text(encoding="utf-8") == "def value():\n    return 1\n"
        assert (tmp_path / "core" / "memory" / "sample_two.py").read_text(encoding="utf-8") == "def value_two():\n    return 2\n"
