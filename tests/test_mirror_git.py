"""Tests for the git-based mirror system."""

import os
import shutil
import subprocess
import tempfile

import pytest

from core.cognition.mirror import MirrorManager, ValidationResult, MergeResult
from core.cognition.quality_gate import QualityGate, PreEvalReport


@pytest.fixture
def temp_project(tmp_path):
    """Create a minimal project structure for testing."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "aria.py").write_text("# ARIA\nprint('hello')\n")
    (project / "config.yaml").write_text("aria:\n  name: ARIA\n")

    core_dir = project / "core" / "cognition"
    core_dir.mkdir(parents=True)
    (core_dir.parent / "__init__.py").write_text("")
    (core_dir / "__init__.py").write_text("")
    (core_dir / "example.py").write_text(
        "def existing_function():\n    return 42\n"
    )

    tests_dir = project / "tests"
    tests_dir.mkdir()
    (tests_dir / "__init__.py").write_text("")

    mirror_dir = project / "data" / "mirror"
    mirror_dir.mkdir(parents=True)

    return project


@pytest.fixture
def mirror(temp_project):
    """Create a MirrorManager instance with a fresh git mirror."""
    return MirrorManager(
        str(temp_project),
        mirror_dir="data/mirror",
        config={"run_tests": False},
    )


# ------------------------------------------------------------------
# Test 1: Init creates git repo with main and develop
# ------------------------------------------------------------------

class TestInitCreatesGitRepo:
    def test_git_dir_exists(self, mirror):
        assert os.path.exists(os.path.join(mirror.mirror_dir, ".git"))

    def test_main_branch_exists(self, mirror):
        output = _git(mirror, "branch", "--list", "main")
        assert "main" in output

    def test_develop_branch_exists(self, mirror):
        output = _git(mirror, "branch", "--list", "develop")
        assert "develop" in output

    def test_starts_on_develop(self, mirror):
        assert mirror._current_branch() == "develop"

    def test_has_initial_commit(self, mirror):
        log = _git(mirror, "log", "--oneline")
        assert "Initial mirror sync" in log


# ------------------------------------------------------------------
# Test 2: Create branch from develop
# ------------------------------------------------------------------

class TestCreateBranch:
    def test_creates_improve_branch(self, mirror):
        branch = mirror.create_branch("add-tracking")
        assert branch == "improve/add-tracking"
        assert mirror._current_branch() == "improve/add-tracking"

    def test_branch_is_based_on_develop(self, mirror):
        # Make a change on develop first
        mirror._git("checkout", "develop")
        marker = os.path.join(mirror.mirror_dir, "develop_marker.txt")
        with open(marker, "w") as f:
            f.write("from develop")
        mirror._git("add", "-A")
        mirror._git("commit", "-m", "develop marker")

        branch = mirror.create_branch("test-base")
        # The marker file should exist on the new branch
        assert os.path.exists(marker)


# ------------------------------------------------------------------
# Test 3: Apply change on branch
# ------------------------------------------------------------------

class TestApplyChangeOnBranch:
    def test_change_committed_on_branch(self, mirror):
        branch = mirror.create_branch("my-change")
        mirror.apply_change(
            "core/cognition/example.py",
            "def new_func():\n    return 99\n",
            branch=branch,
        )

        # Check commit exists
        log = _git(mirror, "log", "--oneline", branch)
        assert "Change core/cognition/example.py" in log

    def test_change_only_on_branch(self, mirror):
        branch = mirror.create_branch("isolated-change")
        mirror.apply_change(
            "core/cognition/example.py",
            "def branch_only():\n    return 'branch'\n",
            branch=branch,
        )

        # Switch to develop — file should have original content
        mirror._git("checkout", "develop")
        example = os.path.join(mirror.mirror_dir, "core", "cognition", "example.py")
        with open(example) as f:
            content = f.read()
        assert "existing_function" in content
        assert "branch_only" not in content


# ------------------------------------------------------------------
# Test 4: Merge to develop
# ------------------------------------------------------------------

class TestMergeToDevelop:
    def test_successful_merge(self, mirror):
        branch = mirror.create_branch("mergeable")
        mirror.apply_change(
            "core/cognition/example.py",
            "def existing_function():\n    return 42\n\ndef new_func():\n    return 99\n",
            branch=branch,
        )

        result = mirror.merge_to_develop(branch)
        assert result.success
        assert not result.conflict

        # Verify change is visible on develop
        example = os.path.join(mirror.mirror_dir, "core", "cognition", "example.py")
        with open(example) as f:
            content = f.read()
        assert "new_func" in content

    def test_merge_result_type(self, mirror):
        branch = mirror.create_branch("typed")
        mirror.apply_change(
            "core/cognition/example.py",
            "def typed():\n    pass\n",
            branch=branch,
        )
        result = mirror.merge_to_develop(branch)
        assert isinstance(result, MergeResult)


# ------------------------------------------------------------------
# Test 5: Concurrent branches, no conflict
# ------------------------------------------------------------------

class TestConcurrentBranchesNoConflict:
    def test_two_branches_different_files(self, mirror):
        # Create two files on develop first so branches can modify them
        mirror._git("checkout", "develop")
        file_a = os.path.join(mirror.mirror_dir, "core", "cognition", "file_a.py")
        file_b = os.path.join(mirror.mirror_dir, "core", "cognition", "file_b.py")
        with open(file_a, "w") as f:
            f.write("# file a\n")
        with open(file_b, "w") as f:
            f.write("# file b\n")
        mirror._git("add", "-A")
        mirror._git("commit", "-m", "Add files a and b")

        # Branch 1 modifies file_a
        branch1 = mirror.create_branch("change-a")
        mirror.apply_change(
            "core/cognition/file_a.py",
            "# file a modified by branch 1\ndef func_a():\n    pass\n",
            branch=branch1,
        )

        # Branch 2 modifies file_b
        mirror._git("checkout", "develop")
        branch2 = mirror.create_branch("change-b")
        mirror.apply_change(
            "core/cognition/file_b.py",
            "# file b modified by branch 2\ndef func_b():\n    pass\n",
            branch=branch2,
        )

        # Merge both to develop
        result1 = mirror.merge_to_develop(branch1)
        assert result1.success

        # Branch 2 needs to be on develop before merging
        result2 = mirror.merge_to_develop(branch2)
        assert result2.success

        # Develop should have both changes
        with open(file_a) as f:
            assert "func_a" in f.read()
        with open(file_b) as f:
            assert "func_b" in f.read()


# ------------------------------------------------------------------
# Test 6: Concurrent branches, same file → conflict
# ------------------------------------------------------------------

class TestConcurrentBranchesSameFileConflict:
    def test_conflicting_changes_detected(self, mirror):
        # Branch 1 modifies example.py one way
        branch1 = mirror.create_branch("change-1")
        mirror.apply_change(
            "core/cognition/example.py",
            "def version_one():\n    return 1\n",
            branch=branch1,
        )

        # Branch 2 modifies example.py differently
        mirror._git("checkout", "develop")
        branch2 = mirror.create_branch("change-2")
        mirror.apply_change(
            "core/cognition/example.py",
            "def version_two():\n    return 2\n",
            branch=branch2,
        )

        # Merge branch 1 first — should succeed
        result1 = mirror.merge_to_develop(branch1)
        assert result1.success

        # Merge branch 2 — should conflict (same file, different content)
        result2 = mirror.merge_to_develop(branch2)
        assert result2.conflict
        assert not result2.success


# ------------------------------------------------------------------
# Test 7: Promote to main
# ------------------------------------------------------------------

class TestPromoteToMain:
    def test_promote_copies_to_live(self, mirror, temp_project):
        # Make a change on develop
        branch = mirror.create_branch("promotable")
        mirror.apply_change(
            "core/cognition/example.py",
            "def promoted_func():\n    return 'live'\n",
            branch=branch,
        )
        mirror.merge_to_develop(branch)

        # Promote
        result = mirror.promote_to_main()
        assert result["success"]
        assert "core/cognition/example.py" in result["promoted_files"]

        # Verify live file has the change
        live_file = temp_project / "core" / "cognition" / "example.py"
        content = live_file.read_text()
        assert "promoted_func" in content


# ------------------------------------------------------------------
# Test 8: Rollback branch
# ------------------------------------------------------------------

class TestRollbackBranch:
    def test_branch_deleted(self, mirror):
        branch = mirror.create_branch("to-delete")
        mirror.apply_change(
            "core/cognition/example.py",
            "def will_be_deleted():\n    pass\n",
            branch=branch,
        )

        mirror.rollback_branch(branch)

        # Branch should no longer exist
        branches = _git(mirror, "branch")
        assert "to-delete" not in branches

    def test_develop_unaffected(self, mirror):
        branch = mirror.create_branch("throwaway")
        mirror.apply_change(
            "core/cognition/example.py",
            "def throwaway():\n    pass\n",
            branch=branch,
        )

        mirror.rollback_branch(branch)

        # Develop should still have original content
        mirror._git("checkout", "develop")
        example = os.path.join(mirror.mirror_dir, "core", "cognition", "example.py")
        with open(example) as f:
            content = f.read()
        assert "existing_function" in content
        assert "throwaway" not in content


# ------------------------------------------------------------------
# Test 9: Pre-eval skips useless change
# ------------------------------------------------------------------

class TestPreEvalSkipsUselessChange:
    def test_duplicate_detection(self, temp_project):
        """Pre-eval should flag a change that duplicates existing functionality."""
        gate = QualityGate(llm=None, review_backend=None)

        # The file has existing_function
        current = "def existing_function():\n    return 42\n"
        report = gate.pre_evaluate(
            target_file="core/cognition/example.py",
            modification_description="Add existing_function to handle data",
            reason="improve data handling",
            current_content=current,
        )

        assert isinstance(report, PreEvalReport)
        # Heuristic mode should detect the duplicate
        assert not report.should_proceed
        assert "duplicate" in report.reason.lower() or "existing" in report.reason.lower()


# ------------------------------------------------------------------
# Test 10: Pre-eval approves real improvement
# ------------------------------------------------------------------

class TestPreEvalApprovesRealImprovement:
    def test_new_functionality_approved(self, temp_project):
        """Pre-eval should approve a genuinely new addition."""
        gate = QualityGate(llm=None, review_backend=None)

        current = "def existing_function():\n    return 42\n"
        report = gate.pre_evaluate(
            target_file="core/cognition/example.py",
            modification_description="Add caching layer for performance optimization",
            reason="reduce API calls by caching results",
            current_content=current,
        )

        assert isinstance(report, PreEvalReport)
        assert report.should_proceed


# ------------------------------------------------------------------
# Additional: list_branches, get_develop_log, sync
# ------------------------------------------------------------------

class TestListBranches:
    def test_lists_improve_branches(self, mirror):
        mirror.create_branch("alpha")
        mirror.apply_change("core/cognition/example.py", "# alpha\n", branch="improve/alpha")
        mirror._git("checkout", "develop")
        mirror.create_branch("beta")
        mirror.apply_change("core/cognition/example.py", "# beta\n", branch="improve/beta")

        branches = mirror.list_branches()
        names = [b["name"] for b in branches]
        assert "improve/alpha" in names
        assert "improve/beta" in names


class TestDevelopLog:
    def test_log_shows_commits(self, mirror):
        branch = mirror.create_branch("logged")
        mirror.apply_change(
            "core/cognition/example.py",
            "def logged():\n    pass\n",
            branch=branch,
        )
        mirror.merge_to_develop(branch)

        log = mirror.get_develop_log(limit=10)
        assert len(log) > 0
        # At minimum, the merge or the change commit should appear
        all_messages = " ".join(c.get("message", "") for c in log).lower()
        assert "merge" in all_messages or "change" in all_messages or "initial" in all_messages


class TestSync:
    def test_sync_updates_main(self, mirror, temp_project):
        # Modify a live file directly
        live_file = temp_project / "core" / "cognition" / "example.py"
        live_file.write_text("def live_change():\n    return 'live'\n")

        mirror.sync()

        # Main should have the live change
        mirror._git("checkout", "main")
        mirror_file = os.path.join(mirror.mirror_dir, "core", "cognition", "example.py")
        with open(mirror_file) as f:
            content = f.read()
        assert "live_change" in content


class TestStatus:
    def test_status_includes_git_info(self, mirror):
        status = mirror.status()
        assert status["type"] == "git"
        assert "current_branch" in status
        assert "improve_branches" in status


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _git(mirror, *args):
    """Run git command on the mirror repo and return output."""
    return mirror._git(*args)
