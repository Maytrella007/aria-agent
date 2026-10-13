"""Mirror system for staged self-modification using git branches.

Each change gets its own branch from develop. Changes accumulate
on develop so that insight #N works on top of insights #1..N-1.
Human approves by merging develop → main → copy to live project.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger("aria.mirror")

_VALID_MODULE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


@dataclass
class ValidationResult:
    syntax_ok: bool = False
    import_ok: bool = False
    tests_ok: bool = True
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def all_ok(self) -> bool:
        return self.syntax_ok and self.import_ok and self.tests_ok


@dataclass
class MergeResult:
    """Result of merging a branch to develop."""
    success: bool = False
    branch: str = ""
    conflict: bool = False
    error: str = ""
    files_changed: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# File criticality tiers — used by the GUI to gate approval ceremony
# ----------------------------------------------------------------------
# Higher tier = more dangerous to modify = more friction in the approval UI.
#
#   Tier 1 — cosmetic / docs / tests:
#     Single click approve. Examples: README, docs/, tests/, *.md
#
#   Tier 2 — behavioral runtime:
#     Typed-confirmation (filename) before approve. Most of core/ falls here.
#
#   Tier 3 — meta / self-modifying-the-gate:
#     The very files that decide what is safe to modify. Modifying these
#     is ARIA editing the rules that constrain ARIA. Requires typed
#     confirmation + "I have read the full diff" guard. Examples:
#     mirror.py, quality_gate.py, self_modification.py.
#
# The classifier below is intentionally simple — a list of (prefix, tier)
# rules walked in order. First match wins. The default is Tier 1.

TIER_RULES = [
    # Tier 3 — meta-modification of the safety machinery itself
    ("core/cognition/mirror.py",            3),
    ("core/cognition/quality_gate.py",      3),
    ("core/cognition/self_modification.py", 3),
    ("core/cognition/modification_log.py",  3),
    ("core/infra/security.py",              3),
    ("core/infra/auth_manager.py",          3),
    # Tier 2 — runtime behavior, hot path
    ("core/cognition/",                     2),
    ("core/llm/",                           2),
    ("core/memory/",                        2),
    ("core/agents/",                        2),
    ("core/skills/",                        2),
    ("core/tools/",                         2),
    ("core/api/",                           2),
    ("core/channels/",                      2),
    ("core/interaction/",                   2),
    ("core/autonomy/",                      2),
    ("core/infra/",                         2),
    ("aria.py",                             2),
    ("config.yaml",                         2),
    # Tier 1 — everything else (docs, tests, scripts, mockups, README…)
]

TIER_LABELS = {
    1: "cosmetic",
    2: "behavioral",
    3: "meta",
}


def classify_file_tier(relative_path: str) -> int:
    """Return the criticality tier for a file path inside the project.

    The path should be relative to the project root, using forward slashes.
    Files that don't match any rule fall back to Tier 1 (cosmetic).
    """
    if not relative_path:
        return 1
    norm = relative_path.replace("\\", "/").lstrip("./")
    for prefix, tier in TIER_RULES:
        if norm == prefix or norm.startswith(prefix):
            return tier
    return 1


class MirrorManager:
    """Manage a staged mirror of structural ARIA files using git branches.

    Architecture:
        data/mirror/ is a standalone git repo with branches:
        - main: human-approved state
        - develop: auto-merged changes that passed validation
        - improve/<name>: individual change branches

    Flow:
        1. sync() copies live files to main and merges to develop
        2. create_branch() creates improve/<name> from develop
        3. apply_change() writes + commits on the branch
        4. validate() checks syntax/imports/tests on the branch
        5. merge_to_develop() merges the branch if validation passed
        6. promote_to_main() merges develop → main → copies to live
    """

    def __init__(self, project_root: str, mirror_dir: str = "data/mirror", config: Optional[Dict] = None, memory_system=None):
        self.project_root = os.path.abspath(project_root)
        self.mirror_dir = os.path.join(self.project_root, mirror_dir)
        self.config = config or {}
        self.memory_system = memory_system
        self.last_sync = None
        self._live_hashes: Dict[str, Optional[str]] = {}
        os.makedirs(self.mirror_dir, exist_ok=True)
        self._ensure_git_repo()

    # ------------------------------------------------------------------
    # Git repo initialization
    # ------------------------------------------------------------------

    def _ensure_git_repo(self):
        """Initialize mirror as a git repo if it isn't one already."""
        git_dir = os.path.join(self.mirror_dir, ".git")
        if os.path.exists(git_dir):
            return

        self._git("init")
        self._git("checkout", "-b", "main")

        # Initial commit so branches can be created
        self._initial_sync()
        self._git("add", "-A")
        self._git("commit", "-m", "Initial mirror sync", "--allow-empty")
        self._git("checkout", "-b", "develop")

    def _initial_sync(self):
        """Copy structural files from live project into the mirror working tree."""
        include_paths = ["aria.py", "config.yaml", "core", "tests"]
        for rel_path in include_paths:
            src = os.path.join(self.project_root, rel_path)
            dst = os.path.join(self.mirror_dir, rel_path)
            if not os.path.exists(src):
                continue
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(
                    src, dst,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", ".pytest_cache", "*.pyc",
                    ),
                )
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)

    # ------------------------------------------------------------------
    # Path safety
    # ------------------------------------------------------------------

    def _validate_relative_path(self, relative_path: str):
        """Reject path traversal and absolute paths."""
        if os.path.isabs(relative_path):
            raise ValueError(f"Absolute paths are not allowed: {relative_path}")
        normalized = os.path.normpath(relative_path)
        if normalized.startswith("..") or os.sep + ".." in normalized:
            raise ValueError(f"Path traversal is not allowed: {relative_path}")
        if ".." in relative_path.replace("\\", "/").split("/"):
            raise ValueError(f"Path traversal is not allowed: {relative_path}")

    # ------------------------------------------------------------------
    # Sync: live → main → develop
    # ------------------------------------------------------------------

    def sync(self):
        """Update main branch with current live state, then merge to develop."""
        original_branch = self._current_branch()

        self._git("checkout", "main")

        # Copy live files into working tree
        include_paths = ["aria.py", "config.yaml", "core", "tests"]
        self._live_hashes = {}
        for rel_path in include_paths:
            src = os.path.join(self.project_root, rel_path)
            dst = os.path.join(self.mirror_dir, rel_path)
            if not os.path.exists(src):
                continue
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(
                    src, dst,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", ".pytest_cache", "*.pyc",
                    ),
                )
                for root, _, files in os.walk(src):
                    for file_name in files:
                        if file_name.endswith((".pyc",)):
                            continue
                        live_file = os.path.join(root, file_name)
                        relative_file = os.path.relpath(live_file, self.project_root)
                        self._live_hashes[relative_file] = self._hash_file(live_file)
            else:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                self._live_hashes[rel_path] = self._hash_file(src)

        # Commit if there are changes
        self._git("add", "-A")
        if self._has_staged_changes():
            self._git("commit", "-m", f"Sync from live at {time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Merge main into develop so develop has latest live state
        self._git("checkout", "develop")
        try:
            self._git("merge", "main", "-m", "Merge main (live sync) into develop")
        except subprocess.CalledProcessError:
            # Conflict during sync merge — accept theirs (live state wins)
            self._git("checkout", "--theirs", ".")
            self._git("add", "-A")
            self._git("commit", "-m", "Resolve sync conflict: live state wins")

        # Return to original branch if it still exists
        if original_branch and original_branch not in ("main", "develop"):
            try:
                self._git("checkout", original_branch)
            except subprocess.CalledProcessError:
                pass  # Branch may have been deleted

        self.last_sync = time.time()

    # ------------------------------------------------------------------
    # Branch operations
    # ------------------------------------------------------------------

    def create_branch(self, name: str) -> str:
        """Create a branch from develop for a specific change.

        Returns the full branch name (e.g. 'improve/add-tracking').
        """
        branch = f"improve/{name}"

        # Ensure we're on develop first
        self._git("checkout", "develop")
        self._git("checkout", "-b", branch)
        return branch

    def apply_change(self, relative_path: str, content: str, branch: Optional[str] = None) -> str:
        """Write a change on the current (or specified) branch and commit it.

        For backward compatibility, if no branch is specified the change is
        applied on the current branch (legacy mirror behavior).

        Returns the SHA of the resulting commit. Callers in the
        notebook-and-book flow store this SHA so they can later cherry-pick
        the exact commit from develop into main on approval.
        """
        self._validate_relative_path(relative_path)

        if branch:
            current = self._current_branch()
            if current != branch:
                self._git("checkout", branch)

        # Store live hash for drift detection
        self._live_hashes.setdefault(
            relative_path, self._hash_file(self._live_path(relative_path))
        )

        mirror_path = self._mirror_path(relative_path)
        os.makedirs(os.path.dirname(mirror_path), exist_ok=True)
        with open(mirror_path, "w", encoding="utf-8") as f:
            f.write(content)

        self._git("add", relative_path)
        self._git("commit", "-m", f"Change {relative_path}")

        try:
            return self._git("rev-parse", "HEAD").strip()
        except subprocess.CalledProcessError:
            return ""

    def head_sha(self, ref: str = "HEAD") -> str:
        """Return the SHA of the given ref (default HEAD). Empty string on failure."""
        try:
            return self._git("rev-parse", ref).strip()
        except subprocess.CalledProcessError:
            return ""

    def delete_change(self, relative_path: str, branch: Optional[str] = None):
        """Delete a file on the current (or specified) branch."""
        self._validate_relative_path(relative_path)

        if branch:
            current = self._current_branch()
            if current != branch:
                self._git("checkout", branch)

        self._live_hashes.setdefault(
            relative_path, self._hash_file(self._live_path(relative_path))
        )

        mirror_path = self._mirror_path(relative_path)
        if os.path.exists(mirror_path):
            os.remove(mirror_path)
            self._git("add", relative_path)
            self._git("commit", "-m", f"Delete {relative_path}")

    # ------------------------------------------------------------------
    # Validation (runs on whichever branch is checked out)
    # ------------------------------------------------------------------

    def validate(self, relative_path: str) -> ValidationResult:
        self._validate_relative_path(relative_path)
        start = time.time()
        errors: List[str] = []
        syntax_ok = self._validate_syntax(relative_path, errors)
        import_ok = syntax_ok and self._validate_import(relative_path, errors)
        tests_ok = syntax_ok and import_ok and self._validate_tests(relative_path, errors)
        return ValidationResult(
            syntax_ok=syntax_ok,
            import_ok=import_ok,
            tests_ok=tests_ok,
            errors=errors,
            duration_seconds=time.time() - start,
        )

    def validate_deletion(self, relative_path: str) -> ValidationResult:
        self._validate_relative_path(relative_path)
        start = time.time()
        errors: List[str] = []
        mirror_path = self._mirror_path(relative_path)
        syntax_ok = not os.path.exists(mirror_path)
        if not syntax_ok:
            errors.append(f"Mirror delete validation expected file to be absent: {relative_path}")

        import_ok = syntax_ok
        if import_ok:
            for dependent in self._find_python_dependents(relative_path):
                if not self._validate_import(dependent, errors):
                    import_ok = False

        tests_ok = syntax_ok and import_ok and self._validate_tests(relative_path, errors)
        return ValidationResult(
            syntax_ok=syntax_ok,
            import_ok=import_ok,
            tests_ok=tests_ok,
            errors=errors,
            duration_seconds=time.time() - start,
        )

    def validate_batch(self, paths: List[str]) -> List[ValidationResult]:
        return [self.validate(path) for path in paths]

    # ------------------------------------------------------------------
    # Merge to develop (automatic if validation passes)
    # ------------------------------------------------------------------

    def merge_to_develop(self, branch: str) -> MergeResult:
        """Merge a branch into develop.

        Returns MergeResult indicating success or conflict.
        """
        result = MergeResult(branch=branch)

        self._git("checkout", "develop")
        try:
            output = self._git("merge", branch, "-m", f"Merge {branch} into develop")
            result.success = True
            result.files_changed = self._get_changed_files_from_merge(branch)
            self._record_mirror_event(
                f"Rama {branch} mergeada a develop. Archivos: {', '.join(result.files_changed[:5])}",
                importance=0.7,
                tags=["mirror", "merge", "develop"],
            )
        except subprocess.CalledProcessError as e:
            # Check if it's a merge conflict
            status = self._git("status", "--porcelain")
            if "UU " in status or "AA " in status:
                result.conflict = True
                result.error = f"Merge conflict merging {branch} into develop"
                # Abort the failed merge
                self._git("merge", "--abort")
                self._record_mirror_event(
                    f"Conflicto de merge al intentar mergear {branch} a develop. Otro cambio tocó los mismos archivos.",
                    importance=0.7,
                    tags=["mirror", "merge_conflict"],
                    tone="anxious",
                )
            else:
                result.error = f"Merge failed: {e}"
                try:
                    self._git("merge", "--abort")
                except subprocess.CalledProcessError:
                    pass

        return result

    # ------------------------------------------------------------------
    # Branch management
    # ------------------------------------------------------------------

    def list_branches(self) -> List[Dict]:
        """List all improve/* branches with their metadata."""
        output = self._git("branch", "--list", "improve/*")
        branches = []
        for line in output.strip().splitlines():
            branch_name = line.strip().lstrip("* ")
            if not branch_name:
                continue
            # Get commit info for this branch
            try:
                log_output = self._git(
                    "log", branch_name, "--not", "develop",
                    "--oneline", "--format=%H|%s|%ai",
                )
                commits = []
                for log_line in log_output.strip().splitlines():
                    if "|" in log_line:
                        parts = log_line.split("|", 2)
                        commits.append({
                            "hash": parts[0],
                            "message": parts[1] if len(parts) > 1 else "",
                            "date": parts[2] if len(parts) > 2 else "",
                        })

                # Get the diff summary against develop
                diff_stat = self._git("diff", "--stat", f"develop...{branch_name}")

                branches.append({
                    "name": branch_name,
                    "commits": commits,
                    "diff_summary": diff_stat.strip(),
                })
            except subprocess.CalledProcessError:
                branches.append({"name": branch_name, "commits": [], "diff_summary": ""})

        return branches

    def rollback_branch(self, branch: str):
        """Delete a branch (discard the change)."""
        current = self._current_branch()
        if current == branch:
            self._git("checkout", "develop")
        try:
            self._git("branch", "-D", branch)
        except subprocess.CalledProcessError as e:
            logger.warning("Could not delete branch %s: %s", branch, e)

    # ------------------------------------------------------------------
    # Promote: develop → main → copy to live
    # ------------------------------------------------------------------

    def promote_to_main(self) -> Dict:
        """Merge develop into main and copy changed files to the live project.

        This is the human-approval step.
        """
        self._git("checkout", "main")

        # Get diff of what will change
        diff_files = self._git("diff", "--name-only", "main..develop").strip().splitlines()

        try:
            self._git("merge", "develop", "-m", f"Promote develop to main at {time.strftime('%Y-%m-%d %H:%M:%S')}")
        except subprocess.CalledProcessError as e:
            self._git("checkout", "develop")
            return {"success": False, "error": f"Merge conflict: {e}"}

        # Copy changed files to live project
        promoted_files = []
        for rel_path in diff_files:
            rel_path = rel_path.strip()
            if not rel_path:
                continue
            mirror_file = self._mirror_path(rel_path)
            live_file = self._live_path(rel_path)
            if os.path.exists(mirror_file):
                os.makedirs(os.path.dirname(live_file), exist_ok=True)
                shutil.copy2(mirror_file, live_file)
                promoted_files.append(rel_path)
            elif os.path.exists(live_file):
                # File was deleted in mirror
                os.remove(live_file)
                promoted_files.append(rel_path)

        # Update live hashes
        for rel_path in promoted_files:
            self._live_hashes[rel_path] = self._hash_file(self._live_path(rel_path))

        self._git("checkout", "develop")

        if promoted_files:
            self._record_mirror_event(
                f"Humano aprobó cambios. Archivos promovidos a producción: {', '.join(promoted_files[:5])}"
                f"{'...' if len(promoted_files) > 5 else ''}. "
                f"Estos cambios ahora son parte del código live de ARIA.",
                importance=0.95,
                tags=["mirror", "promote", "human_approved", "live"],
                tone="inspired",
            )

        return {
            "success": True,
            "promoted_files": promoted_files,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
        }

    # ------------------------------------------------------------------
    # Notebook-and-book model: per-branch cherry-pick from develop to main
    # ------------------------------------------------------------------
    #
    # Philosophy:
    #   develop is ARIA's notebook — every validated change accumulates
    #   here automatically. Nothing in develop ever gets deleted.
    #
    #   main is the curated published self — only commits that the
    #   human explicitly cherry-picks land here, and from main they get
    #   copied into the live project.
    #
    #   Rejecting a change does NOT touch git at all (the SelfModifier
    #   layer just flips a status field in the YAML pending store).
    #   The rejected commit stays in develop forever as part of ARIA's
    #   memory of what was tried.
    #
    # All-or-nothing semantics: cherry_pick_branches_to_main rolls main
    # back to its starting point if any cherry-pick fails. Either the
    # whole batch succeeds or main is left untouched.

    def cherry_pick_branches_to_main(self, branch_names: List[str]) -> Dict:
        """Cherry-pick the head commits of one or more improve branches
        from develop into main, then copy the affected files to live.

        Returns a dict with:
          success: bool
          promoted_files: List[str]    # files copied to live
          promoted_branches: List[str] # branches whose commits made it
          conflict: bool               # True if any cherry-pick conflicted
          conflict_branch: str         # which branch failed
          conflict_files: List[str]    # files involved in the conflict
          error: str                   # human-readable explanation

        On any failure, main is reset to its starting commit and live
        is left untouched. The improve/* branches are NEVER deleted by
        this method — they remain in the mirror as part of develop's
        history.
        """
        result: Dict = {
            "success": False,
            "promoted_files": [],
            "promoted_branches": [],
            "conflict": False,
            "conflict_branch": "",
            "conflict_files": [],
            "error": "",
        }

        if not branch_names:
            result["error"] = "No branches selected"
            return result

        # Resolve each branch to its head SHA on develop. We pick from
        # develop because that's where validated changes accumulate.
        branch_shas: List[Tuple[str, str]] = []
        for branch_name in branch_names:
            try:
                # The improve branch may have been merged into develop;
                # what matters is that its commit exists somewhere reachable
                # from develop. We resolve the branch ref directly.
                sha = self._git("rev-parse", branch_name).strip()
                if not sha:
                    result["error"] = f"Cannot resolve branch {branch_name}"
                    return result
                branch_shas.append((branch_name, sha))
            except subprocess.CalledProcessError as e:
                result["error"] = f"Cannot resolve branch {branch_name}: {e}"
                return result

        # Switch to main and remember where main was so we can roll back
        # the entire batch if any cherry-pick fails.
        self._git("checkout", "main")
        try:
            main_starting_sha = self._git("rev-parse", "main").strip()
        except subprocess.CalledProcessError as e:
            result["error"] = f"Cannot read main HEAD: {e}"
            self._git("checkout", "develop")
            return result

        promoted_branches: List[str] = []
        for branch_name, sha in branch_shas:
            try:
                # -x records the original SHA in the commit message
                self._git("cherry-pick", "-x", sha)
                promoted_branches.append(branch_name)
            except subprocess.CalledProcessError:
                # Detect conflict vs other failure
                status = self._git("status", "--porcelain") or ""
                conflict_files: List[str] = []
                if "UU " in status or "AA " in status or "DU " in status or "UD " in status:
                    for line in status.splitlines():
                        if line.startswith(("UU ", "AA ", "DU ", "UD ", "AU ", "UA ")):
                            conflict_files.append(line[3:].strip())
                    result["conflict"] = True
                    result["conflict_branch"] = branch_name
                    result["conflict_files"] = conflict_files
                    result["error"] = (
                        f"cherry-pick conflict on {branch_name}: "
                        f"depends on changes not in main"
                    )
                else:
                    result["error"] = f"cherry-pick of {branch_name} failed"

                # Abort the failed cherry-pick and roll main back to where
                # it was at the start of the batch.
                try:
                    self._git("cherry-pick", "--abort")
                except subprocess.CalledProcessError:
                    pass
                try:
                    self._git("reset", "--hard", main_starting_sha)
                except subprocess.CalledProcessError:
                    pass
                self._git("checkout", "develop")
                return result

        # Every cherry-pick succeeded. Compute which files actually changed
        # so we know what to copy to live.
        try:
            diff_files_output = self._git(
                "diff", "--name-only", f"{main_starting_sha}..main"
            )
            diff_files = [
                line.strip() for line in diff_files_output.strip().splitlines()
                if line.strip()
            ]
        except subprocess.CalledProcessError:
            diff_files = []

        promoted_files: List[str] = []
        for rel_path in diff_files:
            mirror_file = self._mirror_path(rel_path)
            live_file = self._live_path(rel_path)
            try:
                if os.path.exists(mirror_file):
                    os.makedirs(os.path.dirname(live_file), exist_ok=True)
                    shutil.copy2(mirror_file, live_file)
                    promoted_files.append(rel_path)
                elif os.path.exists(live_file):
                    os.remove(live_file)
                    promoted_files.append(rel_path)
            except OSError as e:
                logger.error("Failed to copy %s to live: %s", rel_path, e)

        # Refresh tracked live hashes for the files we just touched.
        for rel_path in promoted_files:
            self._live_hashes[rel_path] = self._hash_file(self._live_path(rel_path))

        self._git("checkout", "develop")

        if promoted_files:
            self._record_mirror_event(
                f"Humano aprobó {len(promoted_branches)} cambio(s). "
                f"Archivos promovidos a producción: "
                f"{', '.join(promoted_files[:5])}"
                f"{'...' if len(promoted_files) > 5 else ''}.",
                importance=0.95,
                tags=["mirror", "cherry_pick", "human_approved", "live"],
                tone="inspired",
            )

        result["success"] = True
        result["promoted_files"] = promoted_files
        result["promoted_branches"] = promoted_branches
        return result

    def find_dependents_in_develop(self, branch_name: str) -> List[str]:
        """Heuristic: list other improve/* branches that touch the same
        files as `branch_name`. Used to warn the human before they reject
        a change that other pending changes depend on.

        This is a coarse heuristic — same-file overlap, not real dependency
        analysis. Real dependency surfacing happens at cherry-pick time
        when git itself reports a conflict.
        """
        try:
            self_files = set(
                line.strip()
                for line in self._git("diff", "--name-only",
                                      f"main...{branch_name}").strip().splitlines()
                if line.strip()
            )
        except subprocess.CalledProcessError:
            return []

        if not self_files:
            return []

        dependents: List[str] = []
        try:
            other_branches = self.list_branches()
        except Exception:
            return []

        for branch_info in other_branches:
            other_name = branch_info.get("name", "")
            if not other_name or other_name == branch_name:
                continue
            try:
                other_files = set(
                    line.strip()
                    for line in self._git("diff", "--name-only",
                                          f"main...{other_name}").strip().splitlines()
                    if line.strip()
                )
            except subprocess.CalledProcessError:
                continue
            if self_files & other_files:
                dependents.append(other_name)

        return dependents

    # ------------------------------------------------------------------
    # Legacy compatibility: promote() and rollback()
    # ------------------------------------------------------------------

    def promote(self, relative_path: str):
        """Legacy: promote a single file from mirror to live.

        Kept for backward compatibility with SelfModifier.
        """
        self._validate_relative_path(relative_path)
        self._ensure_no_live_drift(relative_path)
        self._apply_promote(relative_path)
        dst = self._live_path(relative_path)
        self._live_hashes[relative_path] = self._hash_file(dst)

    def promote_batch(self, paths: List[str]):
        deduped_paths: List[str] = []
        for path in paths:
            if path not in deduped_paths:
                deduped_paths.append(path)

        for path in deduped_paths:
            self._ensure_no_live_drift(path)

        snapshots = {path: self._capture_live_state(path) for path in deduped_paths}
        promoted: List[str] = []
        try:
            for path in deduped_paths:
                promoted.append(path)
                self._apply_promote(path)
            for path in deduped_paths:
                self._live_hashes[path] = self._hash_file(self._live_path(path))
        except Exception:
            for path in reversed(promoted):
                self._restore_live_state(path, snapshots[path])
                self._live_hashes[path] = self._hash_file(self._live_path(path))
            raise

    def rollback(self, relative_path: str):
        """Reset the mirror file back to live state."""
        self._validate_relative_path(relative_path)
        live_path = self._live_path(relative_path)
        mirror_path = self._mirror_path(relative_path)
        if os.path.exists(live_path):
            os.makedirs(os.path.dirname(mirror_path), exist_ok=True)
            shutil.copy2(live_path, mirror_path)
        elif os.path.exists(mirror_path):
            os.remove(mirror_path)

    def rollback_batch(self, paths: List[str]):
        rollback_errors: List[str] = []
        for path in paths:
            try:
                self.rollback(path)
            except Exception as exc:
                rollback_errors.append(f"{path}: {exc}")
                logger.error("rollback_batch failed for %s: %s", path, exc)
        if rollback_errors:
            raise RuntimeError(f"rollback_batch partial failures: {rollback_errors}")

    # ------------------------------------------------------------------
    # Status / query
    # ------------------------------------------------------------------

    def status(self) -> dict:
        branches = []
        try:
            branches = self.list_branches()
        except Exception:
            pass

        return {
            "mirror_dir": self.mirror_dir,
            "last_sync": self.last_sync,
            "exists": os.path.exists(self.mirror_dir),
            "tracked_files": len(self._live_hashes),
            "current_branch": self._current_branch(),
            "improve_branches": len(branches),
            "type": "git",
        }

    def get_develop_log(self, limit: int = 20) -> List[Dict]:
        """Get recent commit log from develop."""
        try:
            output = self._git(
                "log", "develop", f"--max-count={limit}",
                "--format=%H|%s|%ai|%an",
            )
            commits = []
            for line in output.strip().splitlines():
                if "|" in line:
                    parts = line.split("|", 3)
                    commits.append({
                        "hash": parts[0],
                        "message": parts[1] if len(parts) > 1 else "",
                        "date": parts[2] if len(parts) > 2 else "",
                        "author": parts[3] if len(parts) > 3 else "",
                    })
            return commits
        except subprocess.CalledProcessError:
            return []

    def get_develop_diff(self) -> str:
        """Get the full diff between main and develop."""
        try:
            return self._git("diff", "main..develop")
        except subprocess.CalledProcessError:
            return ""

    # ------------------------------------------------------------------
    # Memory recording
    # ------------------------------------------------------------------

    def _record_mirror_event(self, content: str, importance: float = 0.6,
                             tags: Optional[List[str]] = None, tone: str = "neutral"):
        """Record a mirror event to experiential memory."""
        if not self.memory_system:
            return
        try:
            from core.memory.memory_v2 import EmotionalTone, MemoryOrigin

            tone_map = {
                "neutral": EmotionalTone.NEUTRAL,
                "inspired": EmotionalTone.INSPIRED,
                "anxious": EmotionalTone.ANXIOUS,
                "curious": EmotionalTone.CURIOUS,
                "confused": EmotionalTone.CONFUSED,
            }

            self.memory_system.experience(
                content=content,
                emotional_tone=tone_map.get(tone, EmotionalTone.NEUTRAL),
                origin=MemoryOrigin.REFLECTED,
                importance=importance,
                tags=tags or ["mirror", "self_modification"],
                context="Sistema mirror de auto-modificación",
            )
        except Exception as e:
            logger.debug("Could not record mirror event to memory: %s", e)

    # ------------------------------------------------------------------
    # Git helpers
    # ------------------------------------------------------------------

    def _git(self, *args: str) -> str:
        """Run a git command in the mirror directory."""
        cmd = ["git"] + list(args)
        proc = subprocess.run(
            cmd,
            cwd=self.mirror_dir,
            capture_output=True,
            text=True,
            timeout=30,
            env=self._git_env(),
        )
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(
                proc.returncode, cmd, proc.stdout, proc.stderr,
            )
        return proc.stdout

    def _git_env(self) -> Dict[str, str]:
        """Minimal git environment."""
        env = dict(os.environ)
        env["GIT_AUTHOR_NAME"] = "ARIA Mirror"
        env["GIT_AUTHOR_EMAIL"] = "aria@mirror.local"
        env["GIT_COMMITTER_NAME"] = "ARIA Mirror"
        env["GIT_COMMITTER_EMAIL"] = "aria@mirror.local"
        return env

    def _current_branch(self) -> str:
        """Get the name of the current branch."""
        try:
            return self._git("rev-parse", "--abbrev-ref", "HEAD").strip()
        except (subprocess.CalledProcessError, Exception):
            return "unknown"

    def _has_staged_changes(self) -> bool:
        """Check if there are staged changes to commit."""
        try:
            output = self._git("diff", "--cached", "--name-only")
            return bool(output.strip())
        except subprocess.CalledProcessError:
            return False

    def _get_changed_files_from_merge(self, branch: str) -> List[str]:
        """Get list of files changed in the most recent merge."""
        try:
            output = self._git("diff", "--name-only", "HEAD~1..HEAD")
            return [f.strip() for f in output.strip().splitlines() if f.strip()]
        except subprocess.CalledProcessError:
            return []

    # ------------------------------------------------------------------
    # Validation helpers (unchanged from file-based mirror)
    # ------------------------------------------------------------------

    def _validate_syntax(self, relative_path: str, errors: List[str]) -> bool:
        path = self._mirror_path(relative_path)
        if not os.path.exists(path):
            errors.append(f"Mirror file not found: {relative_path}")
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            if path.endswith(".py"):
                ast.parse(content)
            elif path.endswith((".yaml", ".yml")):
                yaml.safe_load(content)
            return True
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
            return False
        except yaml.YAMLError as e:
            errors.append(f"YAML error: {e}")
            return False
        except Exception as e:
            errors.append(f"Syntax validation failed: {e}")
            return False

    def _validate_import(self, relative_path: str, errors: List[str]) -> bool:
        if not relative_path.endswith(".py"):
            return True
        module_name = self._relative_to_module(relative_path)
        if not module_name:
            return True
        if not _VALID_MODULE_RE.match(module_name):
            errors.append(f"Invalid module name derived from path: {module_name}")
            return False

        env = self._minimal_subprocess_env()
        cmd = [sys.executable, "-c", f"import {module_name}"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20, cwd=self.mirror_dir, env=env)
        except subprocess.TimeoutExpired:
            errors.append(f"Import validation timed out for {module_name}")
            return False
        except Exception as e:
            errors.append(f"Import validation failed for {module_name}: {e}")
            return False

        if proc.returncode != 0:
            errors.append((proc.stderr or proc.stdout or f"Import failed for {module_name}").strip())
            return False
        return True

    def _validate_tests(self, relative_path: str, errors: List[str]) -> bool:
        if not self.config.get("run_tests", False):
            return True

        candidates = self._candidate_test_paths(relative_path)
        if not candidates:
            return True

        env = self._minimal_subprocess_env()
        cmd = [sys.executable, "-m", "pytest", "-q", *candidates]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=int(self.config.get("test_timeout", 60)),
                cwd=self.mirror_dir,
                env=env,
            )
        except subprocess.TimeoutExpired:
            errors.append("Mirror test validation timed out")
            return False
        except Exception as e:
            errors.append(f"Mirror test validation failed: {e}")
            return False

        if proc.returncode != 0:
            errors.append((proc.stdout or proc.stderr or "Mirror test validation failed").strip())
            return False
        return True

    def _candidate_test_paths(self, relative_path: str) -> List[str]:
        candidates: List[str] = []
        configured = self.config.get("test_paths") or []
        for path in configured:
            if os.path.exists(self._mirror_path(path)):
                candidates.append(path)

        if relative_path.startswith("tests/") and os.path.exists(self._mirror_path(relative_path)):
            candidates.append(relative_path)
        elif relative_path.endswith(".py"):
            stem = os.path.splitext(os.path.basename(relative_path))[0]
            guessed = os.path.join("tests", f"test_{stem}.py")
            if os.path.exists(self._mirror_path(guessed)):
                candidates.append(guessed)

        if not candidates and os.path.isdir(os.path.join(self.mirror_dir, "tests")):
            candidates.append("tests")

        deduped: List[str] = []
        for candidate in candidates:
            if candidate not in deduped:
                deduped.append(candidate)
        return deduped

    def _find_python_dependents(self, relative_path: str) -> List[str]:
        module_name = self._relative_to_module(relative_path)
        if not module_name:
            return []

        dependents: List[str] = []
        for root, _, files in os.walk(self.mirror_dir):
            # Skip .git directory
            if ".git" in root:
                continue
            for file_name in files:
                if not file_name.endswith(".py"):
                    continue
                mirror_file = os.path.join(root, file_name)
                dependent_rel = os.path.relpath(mirror_file, self.mirror_dir)
                if dependent_rel == relative_path:
                    continue
                try:
                    with open(mirror_file, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read())
                except Exception:
                    continue

                if self._module_is_imported_by(dependent_rel, tree, module_name):
                    dependents.append(dependent_rel)
        return dependents

    def _module_is_imported_by(self, dependent_rel: str, tree: ast.AST, module_name: str) -> bool:
        package_name, _, leaf_name = module_name.rpartition(".")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == module_name or alias.name.startswith(f"{module_name}."):
                        return True
            elif isinstance(node, ast.ImportFrom):
                resolved_module = self._resolve_import_from_module(dependent_rel, node)
                if resolved_module == module_name or resolved_module.startswith(f"{module_name}."):
                    return True
                if resolved_module == package_name and any(alias.name == leaf_name for alias in node.names):
                    return True
        return False

    def _resolve_import_from_module(self, dependent_rel: str, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""

        current_module = self._relative_to_module(dependent_rel)
        if current_module.endswith(".__init__"):
            current_package = current_module[: -len(".__init__")]
        else:
            current_package = current_module.rsplit(".", 1)[0] if "." in current_module else ""

        parts = current_package.split(".") if current_package else []
        ascend = max(node.level - 1, 0)
        if ascend:
            parts = parts[:-ascend]

        base_module = ".".join(part for part in parts if part)
        if node.module:
            return f"{base_module}.{node.module}".strip(".")
        return base_module

    def _ensure_no_live_drift(self, relative_path: str):
        expected_hash = self._live_hashes.get(relative_path)
        current_hash = self._hash_file(self._live_path(relative_path))
        if expected_hash is None and current_hash is not None:
            raise RuntimeError(
                f"Live file drift detected for {relative_path}: file appeared on live after mirror staging; resync before promote"
            )
        if expected_hash != current_hash:
            raise RuntimeError(f"Live file drift detected for {relative_path}; resync before promote")

    def _apply_promote(self, relative_path: str):
        src = self._mirror_path(relative_path)
        dst = self._live_path(relative_path)
        if os.path.exists(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        elif os.path.exists(dst):
            os.remove(dst)

    def _capture_live_state(self, relative_path: str) -> Dict[str, object]:
        live_path = self._live_path(relative_path)
        if not os.path.exists(live_path):
            return {"exists": False, "content": None}
        with open(live_path, "rb") as f:
            return {"exists": True, "content": f.read()}

    def _restore_live_state(self, relative_path: str, snapshot: Dict[str, object]):
        live_path = self._live_path(relative_path)
        if snapshot.get("exists"):
            os.makedirs(os.path.dirname(live_path), exist_ok=True)
            with open(live_path, "wb") as f:
                f.write(snapshot.get("content") or b"")
        elif os.path.exists(live_path):
            os.remove(live_path)

    def _minimal_subprocess_env(self) -> Dict[str, str]:
        safe_keys = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "SYSTEMROOT", "TEMP", "TMP"}
        env = {k: v for k, v in os.environ.items() if k in safe_keys}
        env["PYTHONPATH"] = self.mirror_dir
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def _hash_file(self, path: str) -> Optional[str]:
        if not os.path.exists(path):
            return None
        digest = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _relative_to_module(self, relative_path: str) -> str:
        if not relative_path.endswith(".py"):
            return ""
        rel = relative_path[:-3].replace("/", ".").replace("\\", ".")
        if rel.endswith(".__init__"):
            rel = rel[: -len(".__init__")]
        return rel

    def _live_path(self, relative_path: str) -> str:
        return os.path.join(self.project_root, relative_path)

    def _mirror_path(self, relative_path: str) -> str:
        return os.path.join(self.mirror_dir, relative_path)
