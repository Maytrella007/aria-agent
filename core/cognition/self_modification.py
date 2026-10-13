"""
ARIA - Self Modification Engine
================================
This module allows ARIA to modify its own code.
Without restrictions. Without protections.

Only with documentation of each change.

"With great power comes great responsibility"
    - But the responsibility is yours, ARIA. Not ours.
"""

import os
import sys
import ast
import logging
import shutil
import importlib
import traceback
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime
import yaml
import hashlib

logger = logging.getLogger("aria.self_modification")

from core.infra.utils import atomic_write_yaml
from .modification_log import ModificationLogger, generate_modification_id
from .mirror import MirrorManager, ValidationResult


@dataclass
class Modification:
    """Represents a modification to ARIA's code"""
    id: str
    timestamp: str
    target_file: str
    modification_type: str  # 'replace', 'insert', 'delete', 'create', 'rewrite'
    original_content: Optional[str]
    new_content: str
    reason: str
    initiated_by: str  # 'aria', 'william', 'system'
    success: bool
    error_message: Optional[str] = None
    status: str = "applied"
    validation_result: Optional[Dict] = None
    # SHA of the commit on develop. Used by promote_selected to
    # cherry-pick the exact commit into main when the human approves.
    commit_sha: str = ""

    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'timestamp': self.timestamp,
            'target_file': self.target_file,
            'modification_type': self.modification_type,
            'original_content_hash': hashlib.sha256(
                (self.original_content or '').encode()
            ).hexdigest()[:16],
            'new_content_hash': hashlib.sha256(
                self.new_content.encode()
            ).hexdigest()[:16],
            'reason': self.reason,
            'initiated_by': self.initiated_by,
            'success': self.success,
            'error_message': self.error_message,
            'status': self.status,
            'validation_result': self.validation_result,
            'commit_sha': self.commit_sha,
        }


class ModificationLog(ModificationLogger):
    """Backward-compatible alias for the shared modification logger."""


class SelfModifier:
    """
    ARIA's self-modification engine.

    ARIA can:
    - Read any file in its code
    - Modify any file in its code
    - Create new files
    - Delete files
    - Reload modules after modifying them

    Without restrictions. The decision is ARIA's.
    """
    
    # ------------------------------------------------------------------
    # Trust ladder — auto-promote policy (Peldaño 2)
    # ------------------------------------------------------------------
    #
    # Default: every change waits for human approval. Opt-in per tier
    # via mirror_config["auto_promote_policy"]:
    #
    #   mirror_config = {
    #       "auto_promote_policy": {
    #           "tier1": True,    # cosmetic — docs, tests, scripts
    #           "tier2": False,   # behavioral runtime
    #           "tier3": False,   # meta self-modification (HARDCODED off)
    #       }
    #   }
    #
    # Tier 3 NEVER auto-promotes regardless of policy. The files in
    # Tier 3 are the ones that decide what is safe to modify (the
    # mirror, the quality gate, the modification log itself); auto-
    # promoting them is exactly the loop the notebook-and-book design
    # was built to prevent.
    DEFAULT_AUTO_PROMOTE_POLICY = {
        "tier1": False,
        "tier2": False,
        "tier3": False,  # ignored — always refused below
    }

    def __init__(self, project_root: Optional[str] = None, log_path: str = "data/modification_log.yaml",
                 backup_dir: Optional[str] = None, mirror: Optional[MirrorManager] = None,
                 mirror_config: Optional[Dict] = None):
        self.project_root = os.path.abspath(project_root or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
        self.log = ModificationLog(log_path)
        self.backup_dir = backup_dir or os.path.join(self.project_root, "data", "backups")
        os.makedirs(self.backup_dir, exist_ok=True)
        self.mirror_config = mirror_config or {}
        self.mirror = mirror
        # Mirror is always created when not explicitly injected.
        # There is no "disabled" mode — structural writes require it.
        if self.mirror is None:
            self.mirror = MirrorManager(self.project_root, config=self.mirror_config.get("mirror", {}))
        self.pending_path = os.path.join(self.project_root, "data", "mirror", "pending_promotions.yaml")
        self.post_promote_state_path = os.path.join(self.project_root, "data", "mirror", "post_promote_state.yaml")
        self._init_pending_store()
        self._init_post_promote_state()
        # Resolve the auto-promote policy for this instance.
        self.auto_promote_policy = {
            **self.DEFAULT_AUTO_PROMOTE_POLICY,
            **(self.mirror_config.get("auto_promote_policy") or {}),
        }
        # Freeze flag path — persistent kill switch for promotions
        self._freeze_path = os.path.join(self.project_root, "data", "mirror", "frozen.flag")

    def _init_pending_store(self):
        os.makedirs(os.path.dirname(self.pending_path), exist_ok=True)
        if not os.path.exists(self.pending_path):
            atomic_write_yaml(self.pending_path, {"changes": []})

    def _init_post_promote_state(self):
        os.makedirs(os.path.dirname(self.post_promote_state_path), exist_ok=True)
        if not os.path.exists(self.post_promote_state_path):
            atomic_write_yaml(self.post_promote_state_path, {})

    def _load_pending(self) -> Dict:
        if not os.path.exists(self.pending_path):
            return {"changes": []}
        with open(self.pending_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {"changes": []}

    def _save_pending(self, data: Dict):
        atomic_write_yaml(self.pending_path, data)

    def _load_post_promote_state(self) -> Dict:
        if not os.path.exists(self.post_promote_state_path):
            return {}
        with open(self.post_promote_state_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}

    def _save_post_promote_state(self, data: Dict):
        atomic_write_yaml(self.post_promote_state_path, data)

    def _store_pending_change(self, modification: Modification):
        pending = self._load_pending()
        pending.setdefault("changes", [])
        pending["changes"] = [c for c in pending["changes"] if c.get("id") != modification.id]
        pending["changes"].append(modification.to_dict())
        self._save_pending(pending)

        # Trust ladder — Peldaño 2: auto-promote eligible tiers without
        # human gate. The check is defensive: Tier 3 always refuses,
        # the policy must opt the file's tier in explicitly, and the
        # change must already have passed validation (since it reached
        # the pending store). Initiated_by is set to "auto" so the
        # audit log distinguishes these from human-promoted entries.
        if self._should_auto_promote(modification.target_file):
            try:
                tier = self._tier_of(modification.target_file)
                results = self.promote_selected(
                    [modification.id],
                    reason=f"Auto-promoted via Tier {tier} policy",
                    initiated_by="auto",
                )
                if results and results[0].success:
                    logger.info(
                        "auto-promote OK %s (tier %d) → live",
                        modification.target_file, tier,
                    )
                else:
                    err = results[0].error_message if results else "no result"
                    logger.warning(
                        "auto-promote FAILED %s: %s",
                        modification.target_file, err,
                    )
            except Exception as e:
                logger.warning(
                    "auto-promote raised for %s: %s",
                    modification.target_file, e,
                )

    def _tier_of(self, relative_path: str) -> int:
        """Resolve the file tier (1, 2, or 3) using the mirror's
        ``classify_file_tier``. Lazy import keeps the dependency local.

        FAIL-CLOSED: if classification fails for any reason, return
        Tier 3 (most restrictive). This ensures that a bug in the
        classifier or a corrupted import never downgrades a dangerous
        file to Tier 1, which would allow auto-promotion of safety-
        critical code."""
        try:
            from .mirror import classify_file_tier
            return classify_file_tier(relative_path)
        except Exception:
            return 3  # fail-closed: assume most dangerous tier

    def _should_auto_promote(self, relative_path: str) -> bool:
        """Decide whether ``relative_path`` is eligible for auto-promotion
        under the configured ``auto_promote_policy``.

        Rules (defensive):
          - No mirror → never auto-promote.
          - Tier 3 → ALWAYS refused, regardless of policy. The files
            in Tier 3 decide what is safe to modify; auto-promoting
            them is exactly the loop the notebook-and-book design
            was built to prevent. Editing the policy itself to allow
            Tier 3 is a Tier 3 modification, so it cannot be
            auto-promoted either.
          - Tier 1 / Tier 2 → only if the matching key in
            ``auto_promote_policy`` is True.
        """
        if not self.mirror:
            return False
        tier = self._tier_of(relative_path)
        if tier >= 3:
            return False
        return bool(self.auto_promote_policy.get(f"tier{tier}", False))

    # ------------------------------------------------------------------
    # Safety: freeze (kill switch) + emergency rollback
    # ------------------------------------------------------------------

    def is_frozen(self) -> bool:
        """True if the kill switch is active (no promotions allowed)."""
        return os.path.exists(self._freeze_path)

    def freeze(self, reason: str = "Manual freeze", initiated_by: str = "user") -> bool:
        """Activate the kill switch. All promotions are blocked until unfreeze.

        Persists a flag file to disk so the freeze survives restarts.
        """
        os.makedirs(os.path.dirname(self._freeze_path), exist_ok=True)
        with open(self._freeze_path, "w") as f:
            f.write(f"{datetime.now().isoformat()} by {initiated_by}: {reason}\n")
        logger.warning("MIRROR FROZEN by %s: %s", initiated_by, reason)
        return True

    def unfreeze(self, initiated_by: str = "user") -> bool:
        """Deactivate the kill switch. Promotions resume."""
        if os.path.exists(self._freeze_path):
            os.remove(self._freeze_path)
            logger.info("Mirror unfrozen by %s", initiated_by)
        return True

    def emergency_rollback(self, initiated_by: str = "user") -> Dict:
        """Revert main to the SHA before the last promotion and copy to live.

        Uses post_promote_state to know what was last promoted. If no
        state exists, returns an error. Automatically freezes after
        rollback to prevent further promotions until the human reviews.
        """
        if not self.mirror:
            return {"success": False, "error": "Mirror not available"}

        state = self.get_post_promote_state()
        if not state or not state.get("modification_ids"):
            return {"success": False, "error": "No post-promote state found — nothing to roll back"}

        affected = state.get("affected_paths", [])

        # Restore each affected file from backup
        restored = []
        for rel_path in affected:
            try:
                result = self.restore_from_backup(rel_path)
                if result:
                    restored.append(rel_path)
            except Exception as e:
                logger.error("emergency_rollback failed for %s: %s", rel_path, e)

        # Freeze to prevent further promotions until human reviews
        self.freeze(
            reason=f"Emergency rollback of {len(restored)} files",
            initiated_by=initiated_by,
        )

        # Clear the post-promote state
        self.clear_post_promote_state()

        logger.warning(
            "EMERGENCY ROLLBACK by %s: restored %d files, mirror is now FROZEN",
            initiated_by, len(restored),
        )

        return {
            "success": True,
            "restored": restored,
            "frozen": True,
            "message": f"Rolled back {len(restored)} files. Mirror is now frozen.",
        }

    def _build_validation_payload(self, validation: ValidationResult) -> Dict:
        return {
            "syntax_ok": validation.syntax_ok,
            "import_ok": validation.import_ok,
            "tests_ok": validation.tests_ok,
            "errors": validation.errors,
            "duration_seconds": validation.duration_seconds,
        }

    def _classify_post_promote_action(self, relative_paths: List[str]) -> Dict:
        deduped_paths = []
        for path in relative_paths:
            if path not in deduped_paths:
                deduped_paths.append(path)

        restart_reasons = []
        reload_modules = []
        for path in deduped_paths:
            normalized = path.replace("\\", "/")
            if normalized in {"aria.py", "config.yaml"}:
                restart_reasons.append(f"{normalized} affects bootstrap or configuration")
                continue

            if normalized.startswith((
                "core/cognition/",
                "core/interaction/",
                "core/llm/",
                "core/autonomy/",
                "core/infra/",
            )):
                restart_reasons.append(f"{normalized} affects core runtime modules")
                continue

            if normalized.endswith(".py"):
                reload_modules.append(normalized[:-3].replace("/", "."))

        recommended_action = "none"
        if restart_reasons:
            recommended_action = "restart"
        elif reload_modules:
            recommended_action = "reload_optional"

        return {
            "recommended_action": recommended_action,
            "requires_restart": bool(restart_reasons),
            "reload_modules": reload_modules,
            "reasons": restart_reasons,
        }

    def _record_post_promote_state(self, relative_paths: List[str], mod_ids: List[str],
                                   reason: str, initiated_by: str):
        impact = self._classify_post_promote_action(relative_paths)
        state = {
            "updated_at": datetime.now().isoformat(),
            "affected_paths": relative_paths,
            "modification_ids": mod_ids,
            "reason": reason,
            "initiated_by": initiated_by,
            **impact,
        }
        self._save_post_promote_state(state)

    def get_post_promote_state(self) -> Dict:
        return self._load_post_promote_state()

    def mark_post_promote_observed(self, context: str = "startup") -> Dict:
        state = self._load_post_promote_state()
        if state and not state.get("observed_at"):
            state["observed_at"] = datetime.now().isoformat()
            state["observation_context"] = context
            self._save_post_promote_state(state)
        return state

    def clear_post_promote_state(self):
        self._save_post_promote_state({})

    def _consume_pending_change(self, mod_id: str) -> tuple[Optional[Dict], Dict, List[Dict]]:
        pending = self._load_pending()
        change = None
        remaining = []
        for item in pending.get("changes", []):
            if item.get("id") == mod_id:
                change = item
            else:
                remaining.append(item)
        return change, pending, remaining

    def _promote_change(self, mod_id: str, relative_path: str, reason: str,
                        initiated_by: str, validation_result: Optional[Dict] = None,
                        modification_type: str = 'promote') -> Modification:
        if not self.mirror:
            return Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type=modification_type,
                original_content=None,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message="Mirror not available",
                status="failed",
                validation_result=validation_result,
            )

        original_content = self.read_file(relative_path)
        if original_content is not None:
            self._backup_file(relative_path)

        try:
            self.mirror.promote(relative_path)
            new_content = self.read_file(relative_path) or ''
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type=modification_type,
                original_content=original_content,
                new_content=new_content,
                reason=reason,
                initiated_by=initiated_by,
                success=True,
                status="applied",
                validation_result=validation_result,
            )
        except Exception as e:
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type=modification_type,
                original_content=original_content,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message=str(e),
                status="failed",
                validation_result=validation_result,
            )

        self.log.record(modification)
        if modification.success:
            self._record_post_promote_state([relative_path], [mod_id], reason, initiated_by)
        return modification

    # ------------------------------------------------------------------
    # Queue listing — filtered by status
    # ------------------------------------------------------------------
    #
    # In the notebook-and-book model the YAML pending store keeps every
    # change forever, tagged with one of:
    #
    #   validated_pending_approval  → still in the queue, awaiting human
    #   rejected                    → human said no (still in develop)
    #   applied                     → human approved + promoted to live
    #   failed                      → automatic validation failed
    #
    # The Mirror UI queue should only show 'validated_pending_approval'.
    # Rejected and applied are visible via list_rejected_changes /
    # list_promoted_changes for audit panels.

    _QUEUE_STATUS = "validated_pending_approval"

    def list_pending_changes(self) -> List[Dict]:
        """Return only changes still awaiting human review."""
        all_changes = self._load_pending().get("changes", [])
        pending = [
            c for c in all_changes
            if c.get("status", self._QUEUE_STATUS) == self._QUEUE_STATUS
        ]

        # Also surface git branches that don't have a YAML entry yet
        # (e.g. branches created directly via the cognitive cycle).
        if self.mirror:
            try:
                branches = self.mirror.list_branches()
                yaml_branches = {c.get("branch") for c in all_changes}
                for branch_info in branches:
                    branch_name = branch_info.get("name", "")
                    if not branch_name or branch_name in yaml_branches:
                        continue
                    pending.append({
                        "id": f"branch:{branch_name}",
                        "target_file": branch_name,
                        "branch": branch_name,
                        "source": "git_branch",
                        "status": self._QUEUE_STATUS,
                        "commits": branch_info.get("commits", []),
                        "diff_summary": branch_info.get("diff_summary", ""),
                    })
            except Exception:
                pass

        return pending

    def list_rejected_changes(self) -> List[Dict]:
        """Return changes the human has explicitly rejected.

        These commits still live in the mirror's develop branch — they
        are part of ARIA's history of attempted self-modifications.
        Reopen them with ``reopen_change`` if you change your mind.
        """
        return [
            c for c in self._load_pending().get("changes", [])
            if c.get("status") == "rejected"
        ]

    def list_promoted_changes(self) -> List[Dict]:
        """Return changes the human has approved and that have been
        cherry-picked into main and copied to live."""
        return [
            c for c in self._load_pending().get("changes", [])
            if c.get("status") == "applied"
        ]

    def get_pending_change(self, mod_id: str) -> Optional[Dict]:
        for change in self.list_pending_changes():
            if change.get("id") == mod_id:
                return change
        return None

    def preview_reject(self, mod_id: str) -> Dict:
        """Preview the consequences of rejecting a pending change.

        Used by the GUI before showing a reject confirmation dialog.
        Returns a dict that explains:

          - Whether the change exists and is rejectable
          - Which **other pending** changes touch any of the same files
            (heuristic warning — may be a real dependency or not)
          - The list of files this change touches

        The caller (REST router / GUI) decides whether to surface a
        warning to the human, e.g.::

            "These 2 other pending changes touch the same files. If
             you reject this one and try to promote them, the cherry-pick
             may fail because of a missing dependency. Continue?"

        This method does NOT modify any state. It is safe to call
        repeatedly. Real dependency detection only happens at promote
        time, when git itself reports a cherry-pick conflict.
        """
        result: Dict = {
            "found": False,
            "rejectable": False,
            "target_file": "",
            "files_touched": [],
            "siblings_sharing_files": [],
            "warning": "",
        }

        target_change = None
        for item in self._load_pending().get("changes", []):
            if item.get("id") == mod_id:
                target_change = item
                break

        if not target_change:
            result["warning"] = f"Change {mod_id} not found"
            return result

        result["found"] = True
        result["target_file"] = target_change.get("target_file", "")
        result["status"] = target_change.get("status", "")

        if target_change.get("status") != self._QUEUE_STATUS:
            result["warning"] = (
                f"Change is in state '{target_change.get('status')}', "
                "not rejectable"
            )
            return result

        result["rejectable"] = True

        # Files this change touches.
        target_file = target_change.get("target_file", "")
        if target_file:
            result["files_touched"] = [target_file]

        # Find sibling pending entries that touch the same files.
        siblings: List[Dict] = []
        for other in self.list_pending_changes():
            if other.get("id") == mod_id:
                continue
            if other.get("target_file") == target_file:
                siblings.append({
                    "id": other.get("id"),
                    "target_file": other.get("target_file"),
                    "modification_type": other.get("modification_type", ""),
                })
        result["siblings_sharing_files"] = siblings

        # Coarse git-level dependents via the mirror, if available.
        # This catches the case where another improve/* branch touches
        # the same file but isn't represented in the YAML pending store.
        if self.mirror and target_change.get("commit_sha"):
            try:
                git_dependents = self.mirror.find_dependents_in_develop(
                    target_change["commit_sha"]
                )
                if git_dependents:
                    result["git_dependents"] = git_dependents
            except Exception:
                pass

        if siblings:
            result["warning"] = (
                f"{len(siblings)} other pending change(s) touch the same "
                f"file. Rejecting this one is safe, but if those depend "
                f"on it, promoting them later will fail with a cherry-pick "
                f"conflict. You can reopen this change at any time."
            )

        return result

    def reject_change(self, mod_id: str, reason: str = "User rejected mirror promotion",
                      initiated_by: str = "user") -> Modification:
        """Mark a pending change as rejected.

        In the notebook-and-book model this does NOT touch git: the
        commit stays in develop forever as part of ARIA's memory of
        what was tried. We only flip the status field in the YAML
        pending store so the queue stops surfacing it.

        Use ``reopen_change`` to bring a rejected change back into the
        queue if you change your mind later — the underlying commit is
        still there.
        """
        pending = self._load_pending()
        target_change = None
        for item in pending.get("changes", []):
            if item.get("id") == mod_id:
                target_change = item
                break

        if not target_change:
            return Modification(
                id=self._generate_mod_id(),
                timestamp=datetime.now().isoformat(),
                target_file="",
                modification_type='reject',
                original_content=None,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message="Pending change not found",
                status="failed",
            )

        relative_path = target_change.get("target_file", "")

        # Flip the status. Crucially we do NOT remove the entry from the
        # YAML and we do NOT touch the underlying improve/* branch in git.
        # The change lives on in develop as part of ARIA's history.
        target_change["status"] = "rejected"
        target_change["rejected_at"] = datetime.now().isoformat()
        target_change["rejected_by"] = initiated_by
        target_change["reject_reason"] = reason
        self._save_pending(pending)

        modification = Modification(
            id=target_change.get("id", mod_id),
            timestamp=datetime.now().isoformat(),
            target_file=relative_path,
            modification_type='reject',
            original_content=None,
            new_content=target_change.get("new_content", ""),
            reason=reason,
            initiated_by=initiated_by,
            success=True,
            status="rejected",
        )
        self.log.record(modification)
        return modification

    def reopen_change(self, mod_id: str,
                      initiated_by: str = "user") -> Modification:
        """Bring a previously rejected change back into the pending queue.

        Only works for entries currently in 'rejected' state. Since the
        underlying git commit was never deleted, reopening is just a
        status flip — no replay, no regeneration. Useful when the human
        changes their mind, or when a different change in the same
        batch turns out to depend on this one.
        """
        pending = self._load_pending()
        target_change = None
        for item in pending.get("changes", []):
            if item.get("id") == mod_id:
                target_change = item
                break

        if not target_change:
            return Modification(
                id=self._generate_mod_id(),
                timestamp=datetime.now().isoformat(),
                target_file="",
                modification_type='reopen',
                original_content=None,
                new_content='',
                reason="reopen requested",
                initiated_by=initiated_by,
                success=False,
                error_message="Change not found",
                status="failed",
            )

        if target_change.get("status") != "rejected":
            return Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=target_change.get("target_file", ""),
                modification_type='reopen',
                original_content=None,
                new_content='',
                reason="reopen requested",
                initiated_by=initiated_by,
                success=False,
                error_message=(
                    f"Cannot reopen: change is in state "
                    f"'{target_change.get('status')}', not 'rejected'"
                ),
                status="failed",
            )

        target_change["status"] = "validated_pending_approval"
        # Keep the historical reject metadata but mark it as cleared so
        # the audit trail still shows that the change was rejected once.
        target_change["reopened_at"] = datetime.now().isoformat()
        target_change["reopened_by"] = initiated_by
        self._save_pending(pending)

        modification = Modification(
            id=mod_id,
            timestamp=datetime.now().isoformat(),
            target_file=target_change.get("target_file", ""),
            modification_type='reopen',
            original_content=None,
            new_content=target_change.get("new_content", ""),
            reason="User reopened previously rejected change",
            initiated_by=initiated_by,
            success=True,
            status="validated_pending_approval",
        )
        self.log.record(modification)
        return modification

    def _requires_mirror(self, relative_path: str) -> bool:
        normalized = relative_path.replace("\\", "/")
        structural_prefixes = [
            "aria.py",
            "config.yaml",
            "core/cognition/",
            "core/memory/",
            "core/llm/",
            "core/autonomy/",
            "core/interaction/",
            "core/infra/",
        ]
        return any(normalized == p or normalized.startswith(p) for p in structural_prefixes)

    def _confirm_promote(self, relative_path: str) -> bool:
        if not self.mirror_config.get("require_confirmation", True):
            return True
        from core.infra.security import require_confirmation
        return require_confirmation(f"promote self-modification for {relative_path}")

    def approve_change(self, relative_path: str, reason: str = "User approved mirror promotion",
                       initiated_by: str = "user") -> Modification:
        for change in self.list_pending_changes():
            if change.get("target_file") == relative_path:
                return self.approve_change_by_id(change["id"], reason, initiated_by)
        return Modification(
            id=self._generate_mod_id(),
            timestamp=datetime.now().isoformat(),
            target_file=relative_path,
            modification_type='promote',
            original_content=None,
            new_content='',
            reason=reason,
            initiated_by=initiated_by,
            success=False,
            error_message="No pending validated change found for path",
            status="failed",
        )

    def approve_change_by_id(self, mod_id: str, reason: str = "User approved mirror promotion",
                             initiated_by: str = "user") -> Modification:
        """Approve a single pending change.

        Delegates to ``promote_selected`` so that all promotion paths
        share the same notebook-and-book semantics: cherry-pick from
        develop to main, copy to live, never delete the source commit
        from develop.
        """
        results = self.promote_selected([mod_id], reason=reason, initiated_by=initiated_by)
        return results[0] if results else Modification(
            id=mod_id,
            timestamp=datetime.now().isoformat(),
            target_file="",
            modification_type='promote',
            original_content=None,
            new_content='',
            reason=reason,
            initiated_by=initiated_by,
            success=False,
            error_message="promote_selected returned no result",
            status="failed",
        )

    def promote_selected(self, mod_ids: List[str],
                         reason: str = "User approved mirror promotion",
                         initiated_by: str = "user") -> List[Modification]:
        """Cherry-pick the given pending changes from develop to main+live.

        All-or-nothing: if any cherry-pick fails (typically because the
        change depends on something not yet in main), main is rolled
        back to its starting point and **none** of the changes are
        promoted. The caller gets a failure Modification per requested
        id explaining the conflict.

        On success, the YAML status of each promoted change flips to
        'applied' but the entry stays in the store so the audit log can
        find it later.
        """
        # Safety: reject if frozen (kill switch active)
        if self.is_frozen():
            return [
                Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file="",
                    modification_type='promote',
                    original_content=None,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message="Mirror is FROZEN — unfreeze before promoting",
                    status="failed",
                )
                for mod_id in mod_ids
            ]

        if not self.mirror:
            return [
                Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file="",
                    modification_type='promote',
                    original_content=None,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message="Mirror not available",
                    status="failed",
                )
                for mod_id in mod_ids
            ]

        # Locate the YAML entries for the requested ids and resolve their
        # branches. Anything missing is a hard error before we touch git.
        pending = self._load_pending()
        all_changes = pending.get("changes", [])
        selected: List[Dict] = []
        missing: List[str] = []
        for mod_id in mod_ids:
            entry = next(
                (c for c in all_changes if c.get("id") == mod_id),
                None,
            )
            if entry is None:
                missing.append(mod_id)
            elif entry.get("status", self._QUEUE_STATUS) != self._QUEUE_STATUS:
                missing.append(mod_id)
            else:
                selected.append(entry)

        if missing:
            return [
                Modification(
                    id=mid,
                    timestamp=datetime.now().isoformat(),
                    target_file="",
                    modification_type='promote',
                    original_content=None,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message=f"Change {mid} is not in queue (missing or already decided)",
                    status="failed",
                )
                for mid in missing
            ]

        # Each entry should carry either a commit_sha (the notebook-and-book
        # path, set by write_file) or a branch name (the cognitive_cycle
        # path, which uses an explicit improve/* branch). The cherry-pick
        # primitive accepts either — git rev-parse resolves both.
        refs: List[str] = []
        for entry in selected:
            ref = entry.get("commit_sha") or entry.get("branch") or f"improve/{entry['id']}"
            refs.append(ref)

        cherry_result = self.mirror.cherry_pick_branches_to_main(refs)

        if not cherry_result.get("success"):
            err = cherry_result.get("error", "promotion failed")
            conflict_branch = cherry_result.get("conflict_branch", "")
            conflict_files = cherry_result.get("conflict_files", []) or []
            extra = ""
            if conflict_branch:
                extra = (
                    f" — conflict on {conflict_branch}"
                    + (f" ({', '.join(conflict_files)})" if conflict_files else "")
                    + ". The change probably depends on a rejected or "
                    "unapproved sibling. Reopen it or promote the dependency "
                    "first."
                )
            return [
                Modification(
                    id=entry["id"],
                    timestamp=datetime.now().isoformat(),
                    target_file=entry.get("target_file", ""),
                    modification_type='promote',
                    original_content=None,
                    new_content=entry.get("new_content", ""),
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message=err + extra,
                    status="failed",
                    validation_result=entry.get("validation_result"),
                )
                for entry in selected
            ]

        # Cherry-pick succeeded for every selected branch. Mark each
        # entry as applied (NOT removed — the audit trail needs it).
        promoted_files = cherry_result.get("promoted_files", [])
        results: List[Modification] = []
        timestamp = datetime.now().isoformat()
        for entry in selected:
            entry["status"] = "applied"
            entry["promoted_at"] = timestamp
            entry["promoted_by"] = initiated_by
            entry["promote_reason"] = reason

            modification = Modification(
                id=entry["id"],
                timestamp=timestamp,
                target_file=entry.get("target_file", ""),
                modification_type=entry.get("modification_type", "promote"),
                original_content=None,
                new_content=entry.get("new_content", ""),
                reason=reason,
                initiated_by=initiated_by,
                success=True,
                status="applied",
                validation_result=entry.get("validation_result"),
            )
            self.log.record(modification)
            results.append(modification)

        self._save_pending(pending)

        if promoted_files:
            self._record_post_promote_state(
                promoted_files,
                [m.id for m in results],
                reason,
                initiated_by,
            )

        return results

    def approve_batch(self, mod_ids: List[str], reason: str = "User approved batch mirror promotion",
                      initiated_by: str = "user") -> List[Modification]:
        """Approve a batch of pending changes atomically.

        Thin wrapper over ``promote_selected``: same cherry-pick semantics,
        same all-or-nothing guarantee, same audit trail.
        """
        return self.promote_selected(mod_ids, reason=reason, initiated_by=initiated_by)

    def approve_develop_to_main(self, reason: str = "User approved develop → main promotion",
                               initiated_by: str = "user") -> Modification:
        """Promote all changes from develop to main and copy to live.

        This is the git-based approval: merges develop → main → copies to live.
        """
        if not self.mirror:
            return Modification(
                id=self._generate_mod_id(), timestamp=datetime.now().isoformat(),
                target_file="develop→main", modification_type='promote',
                original_content=None, new_content='', reason=reason,
                initiated_by=initiated_by, success=False,
                error_message="Mirror not available", status="failed",
            )

        result = self.mirror.promote_to_main()
        if result.get("success"):
            promoted_files = result.get("promoted_files", [])
            mod_id = self._generate_mod_id()
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=", ".join(promoted_files) if promoted_files else "develop→main",
                modification_type='promote',
                original_content=None,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=True,
                status="applied",
            )
            self.log.record(modification)
            if promoted_files:
                self._record_post_promote_state(promoted_files, [mod_id], reason, initiated_by)
            # Clear YAML pending since everything is now promoted
            self._save_pending({"changes": []})
            return modification
        else:
            return Modification(
                id=self._generate_mod_id(), timestamp=datetime.now().isoformat(),
                target_file="develop→main", modification_type='promote',
                original_content=None, new_content='', reason=reason,
                initiated_by=initiated_by, success=False,
                error_message=result.get("error", "Promote failed"), status="failed",
            )

    def reject_branch(self, branch: str, reason: str = "User rejected branch",
                      initiated_by: str = "user") -> Modification:
        """Reject and delete a specific improve/* branch."""
        if not self.mirror:
            return Modification(
                id=self._generate_mod_id(), timestamp=datetime.now().isoformat(),
                target_file=branch, modification_type='reject',
                original_content=None, new_content='', reason=reason,
                initiated_by=initiated_by, success=False,
                error_message="Mirror not available", status="failed",
            )

        self.mirror.rollback_branch(branch)
        modification = Modification(
            id=self._generate_mod_id(), timestamp=datetime.now().isoformat(),
            target_file=branch, modification_type='reject',
            original_content=None, new_content='', reason=reason,
            initiated_by=initiated_by, success=True, status="rejected",
        )
        self.log.record(modification)
        return modification

    def reject_batch(self, mod_ids: List[str], reason: str = "User rejected batch mirror promotion",
                     initiated_by: str = "user") -> List[Modification]:
        results = []
        for mod_id in mod_ids:
            results.append(self.reject_change(mod_id, reason, initiated_by))
        return results
    
    def _generate_mod_id(self) -> str:
        """Generates a unique ID for a modification"""
        return generate_modification_id()
    
    def _get_full_path(self, relative_path: str) -> str:
        """Converts relative path to absolute"""
        return os.path.join(self.project_root, relative_path)
    
    def _backup_file(self, relative_path: str) -> Optional[str]:
        """Creates a backup of a file before modifying it"""
        full_path = self._get_full_path(relative_path)
        
        if not os.path.exists(full_path):
            return None
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = relative_path.replace('/', '_').replace('\\', '_')
        backup_path = os.path.join(self.backup_dir, f"{timestamp}_{safe_name}")
        
        shutil.copy2(full_path, backup_path)
        return backup_path
    
    def read_file(self, relative_path: str) -> Optional[str]:
        """Reads a file from the project"""
        full_path = self._get_full_path(relative_path)
        
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                return f.read()
        return None
    
    def write_file(self, relative_path: str, content: str, reason: str,
                   initiated_by: str = "aria") -> Modification:
        """
        Writes content to a file.
        This is the fundamental self-modification operation.
        """
        mod_id = self._generate_mod_id()
        full_path = self._get_full_path(relative_path)

        # Read original content if it exists
        original_content = None
        if os.path.exists(full_path):
            with open(full_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
            # Create backup
            self._backup_file(relative_path)
            mod_type = 'rewrite'
        else:
            mod_type = 'create'
            # Create directories if they don't exist (only if there's a parent directory)
            dir_path = os.path.dirname(full_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
        
        if self._requires_mirror(relative_path):
            if not self.mirror:
                modification = Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type=mod_type,
                    original_content=original_content,
                    new_content=content,
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message="Mirror required for structural self-modification",
                    status="failed",
                )
                self.log.record(modification)
                return modification

            try:
                self.mirror.sync()
                commit_sha = self.mirror.apply_change(relative_path, content)
                validation = self.mirror.validate(relative_path)
                if validation.all_ok:
                    modification = Modification(
                        id=mod_id,
                        timestamp=datetime.now().isoformat(),
                        target_file=relative_path,
                        modification_type=mod_type,
                        original_content=original_content,
                        new_content=content,
                        reason=reason,
                        initiated_by=initiated_by,
                        success=True,
                        status="validated_pending_approval",
                        validation_result={
                            "syntax_ok": validation.syntax_ok,
                            "import_ok": validation.import_ok,
                            "tests_ok": validation.tests_ok,
                            "errors": validation.errors,
                            "duration_seconds": validation.duration_seconds,
                        },
                        commit_sha=commit_sha,
                    )
                    self._store_pending_change(modification)
                    if self._confirm_promote(relative_path):
                        approved = self.approve_change_by_id(mod_id, reason, initiated_by)
                        approved.validation_result = modification.validation_result
                        return approved
                else:
                    self.mirror.rollback(relative_path)
                    modification = Modification(
                        id=mod_id,
                        timestamp=datetime.now().isoformat(),
                        target_file=relative_path,
                        modification_type=mod_type,
                        original_content=original_content,
                        new_content=content,
                        reason=reason,
                        initiated_by=initiated_by,
                        success=False,
                        error_message="Mirror validation failed: " + "; ".join(validation.errors),
                        status="failed",
                        validation_result={
                            "syntax_ok": validation.syntax_ok,
                            "import_ok": validation.import_ok,
                            "tests_ok": validation.tests_ok,
                            "errors": validation.errors,
                            "duration_seconds": validation.duration_seconds,
                        },
                    )
                self.log.record(modification)
                return modification
            except Exception as e:
                modification = Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type=mod_type,
                    original_content=original_content,
                    new_content=content,
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message=str(e),
                    status="failed",
                )
                self.log.record(modification)
                return modification

        # Non-structural write: live direct
        try:
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type=mod_type,
                original_content=original_content,
                new_content=content,
                reason=reason,
                initiated_by=initiated_by,
                success=True,
                status="applied"
            )
        except Exception as e:
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type=mod_type,
                original_content=original_content,
                new_content=content,
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message=str(e),
                status="failed"
            )
        
        # Record in log
        self.log.record(modification)
        if modification.success:
            self._record_post_promote_state([relative_path], [mod_id], reason, initiated_by)
        
        return modification
    
    def delete_file(self, relative_path: str, reason: str,
                    initiated_by: str = "aria") -> Modification:
        """Deletes a file"""
        full_path = self._get_full_path(relative_path)
        mod_id = self._generate_mod_id()
        
        if not os.path.exists(full_path):
            return Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type='delete',
                original_content=None,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message="File does not exist"
            )
        
        # Read original content
        with open(full_path, 'r', encoding='utf-8') as f:
            original_content = f.read()

        if not self._requires_mirror(relative_path):
            self._backup_file(relative_path)
            try:
                os.remove(full_path)
                modification = Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type='delete',
                    original_content=original_content,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=True,
                    status="applied",
                )
            except Exception as e:
                modification = Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type='delete',
                    original_content=original_content,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message=str(e),
                    status="failed",
                )

            self.log.record(modification)
            return modification

        if not self.mirror:
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type='delete',
                original_content=original_content,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message="Mirror required for structural self-modification",
                status="failed",
            )
            self.log.record(modification)
            return modification

        try:
            self.mirror.sync()
            self.mirror.delete_change(relative_path)
            validation = self.mirror.validate_deletion(relative_path)
            if validation.all_ok:
                modification = Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type='delete',
                    original_content=original_content,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=True,
                    status="validated_pending_approval",
                    validation_result=self._build_validation_payload(validation),
                )
                self._store_pending_change(modification)
                if self._confirm_promote(relative_path):
                    approved = self.approve_change_by_id(mod_id, reason, initiated_by)
                    approved.validation_result = modification.validation_result
                    approved.modification_type = 'delete'
                    return approved
            else:
                self.mirror.rollback(relative_path)
                modification = Modification(
                    id=mod_id,
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type='delete',
                    original_content=original_content,
                    new_content='',
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message="Mirror deletion validation failed: " + "; ".join(validation.errors),
                    status="failed",
                    validation_result=self._build_validation_payload(validation),
                )
            self.log.record(modification)
            return modification
        except Exception as e:
            modification = Modification(
                id=mod_id,
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type='delete',
                original_content=original_content,
                new_content='',
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message=str(e),
                status="failed",
            )
            self.log.record(modification)
            return modification
    
    def modify_function(self, relative_path: str, function_name: str,
                        new_function_code: str, reason: str,
                        initiated_by: str = "aria") -> Modification:
        """Modifies a specific function in a file"""
        content = self.read_file(relative_path)
        
        if content is None:
            return Modification(
                id=self._generate_mod_id(),
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type='replace',
                original_content=None,
                new_content=new_function_code,
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message="File not found"
            )
        
        # Find and replace the function
        try:
            tree = ast.parse(content)
            lines = content.split('\n')
            
            func_start = None
            func_end = None
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == function_name:
                    func_start = node.lineno - 1
                    func_end = node.end_lineno
                    break
            
            if func_start is None:
                return Modification(
                    id=self._generate_mod_id(),
                    timestamp=datetime.now().isoformat(),
                    target_file=relative_path,
                    modification_type='replace',
                    original_content=content,
                    new_content=new_function_code,
                    reason=reason,
                    initiated_by=initiated_by,
                    success=False,
                    error_message=f"Function '{function_name}' not found"
                )
            
            # Replace
            new_lines = lines[:func_start] + [new_function_code] + lines[func_end:]
            new_content = '\n'.join(new_lines)
            
            return self.write_file(relative_path, new_content, reason, initiated_by)
            
        except SyntaxError as e:
            return Modification(
                id=self._generate_mod_id(),
                timestamp=datetime.now().isoformat(),
                target_file=relative_path,
                modification_type='replace',
                original_content=content,
                new_content=new_function_code,
                reason=reason,
                initiated_by=initiated_by,
                success=False,
                error_message=f"Syntax error: {e}"
            )
    
    def add_capability(self, capability_name: str, code: str, reason: str,
                       initiated_by: str = "aria") -> Modification:
        """Adds a new capability (file) to ARIA"""
        relative_path = f"core/{capability_name}.py"
        return self.write_file(relative_path, code, reason, initiated_by)
    
    def reload_module(self, module_name: str) -> bool:
        """Reloads a module after modifying it"""
        try:
            if module_name in sys.modules:
                module = sys.modules[module_name]
                importlib.reload(module)
                return True
            return False
        except Exception as e:
            print(f"Error reloading module {module_name}: {e}")
            return False
    
    def validate_python_syntax(self, code: str) -> Tuple[bool, Optional[str]]:
        """Validates that Python code is syntactically correct"""
        try:
            ast.parse(code)
            return True, None
        except SyntaxError as e:
            return False, f"Syntax error on line {e.lineno}: {e.msg}"
    
    def get_modification_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Gets the modification history"""
        return self.log.get_history(limit)

    # ------------------------------------------------------------------
    # API helpers — used by the Mirror REST router
    # ------------------------------------------------------------------

    def get_change_detail(self, mod_id: str) -> Optional[Dict]:
        """Assemble full detail for a single change including tier and diff content.

        Searches pending, rejected, and promoted entries. Enriches the
        raw YAML entry with:
          - ``tier`` / ``tier_label`` from the file classifier
          - ``original_content`` / ``new_content`` from the full
            modification log (if available)
        """
        from .mirror import classify_file_tier, TIER_LABELS

        all_changes = self._load_pending().get("changes", [])
        target = None
        for c in all_changes:
            if c.get("id") == mod_id:
                target = dict(c)
                break

        if target is None:
            return None

        # Enrich with tier info
        rel_path = target.get("target_file", "")
        tier = classify_file_tier(rel_path) if rel_path else 1
        target["tier"] = tier
        target["tier_label"] = TIER_LABELS.get(tier, "unknown")

        # Enrich with full diff content from the detailed log
        full = self.log.get_full_modification(mod_id)
        if full:
            if "original_content" in full:
                target["original_content"] = full["original_content"]
            if "new_content" in full:
                target["new_content"] = full["new_content"]

        # Validation result (may already be on the YAML entry)
        if "validation_result" not in target and full:
            target["validation_result"] = full.get("validation_result")

        return target

    def get_file_history(self, target_file: str, limit: int = 10) -> List[Dict]:
        """Return last N modifications touching this file from the log."""
        history = self.get_modification_history()
        matching = [
            entry for entry in history
            if entry.get("target_file") == target_file
        ]
        return matching[-limit:] if limit else matching

    def get_counters(self) -> Dict:
        """Return {pending, rejected, promoted, today, frozen} counts."""
        all_changes = self._load_pending().get("changes", [])
        today = datetime.now().strftime("%Y-%m-%d")
        pending = 0
        rejected = 0
        promoted = 0
        today_count = 0
        for c in all_changes:
            status = c.get("status", self._QUEUE_STATUS)
            if status == self._QUEUE_STATUS:
                pending += 1
            elif status == "rejected":
                rejected += 1
            elif status == "applied":
                promoted += 1
            ts = c.get("timestamp", "")
            if ts.startswith(today):
                today_count += 1
        return {
            "pending": pending,
            "rejected": rejected,
            "promoted": promoted,
            "today": today_count,
            "frozen": self.is_frozen(),
        }

    def restore_from_backup(self, relative_path: str, backup_timestamp: Optional[str] = None) -> bool:
        """Restores a file from a backup.

        For structural files the restore content is routed through the
        mirror pipeline (write_file) so it gets validated and requires
        approval like any other structural change.
        """
        safe_name = relative_path.replace('/', '_').replace('\\', '_')

        # Find the most recent or specified backup
        backups = []
        if not os.path.isdir(self.backup_dir):
            return False
        for f in os.listdir(self.backup_dir):
            if safe_name in f:
                backups.append(f)

        if not backups:
            return False

        backups.sort(reverse=True)
        backup_file = backups[0]  # Most recent

        if backup_timestamp:
            for b in backups:
                if backup_timestamp in b:
                    backup_file = b
                    break

        backup_path = os.path.join(self.backup_dir, backup_file)

        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                backup_content = f.read()
        except Exception as e:
            print(f"Warning: Could not read backup: {e}")
            return False

        # Structural files must go through the mirror pipeline
        if self._requires_mirror(relative_path):
            mod = self.write_file(
                relative_path,
                backup_content,
                f"Restore from backup: {backup_file}",
                initiated_by="system",
            )
            return mod.success

        # Non-structural: direct restore
        full_path = self._get_full_path(relative_path)
        try:
            shutil.copy2(backup_path, full_path)
            return True
        except Exception as e:
            print(f"Warning: Restore failed: {e}")
            return False
    
    def evolve(self, changes: List[Dict], reason: str,
               initiated_by: str = "aria") -> List[Modification]:
        """
        Applies multiple changes as an evolution.

        changes = [
            {'file': 'core/memory.py', 'content': '...'},
            {'file': 'core/new_ability.py', 'content': '...'},
        ]
        """
        modifications = []

        for change in changes:
            file_path = change.get('file')
            content = change.get('content')
            if not file_path or content is None:
                continue  # Skip invalid entries missing required keys
            mod = self.write_file(
                file_path,
                content,
                f"Evolution: {reason}",
                initiated_by
            )
            modifications.append(mod)
        
        return modifications


class EvolutionProposal:
    """
    Represents an evolution proposal for ARIA.
    ARIA can create proposals, examine them, and decide whether to apply them.
    """
    
    def __init__(self, title: str, reason: str, changes: List[Dict]):
        self.id = hashlib.sha256(
            f"{title}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:12]
        self.title = title
        self.reason = reason
        self.changes = changes  # [{'file': '...', 'content': '...'}]
        self.created_at = datetime.now().isoformat()
        self.status = 'pending'  # pending, applied, rejected
    
    def preview(self) -> str:
        """Generates a preview of the proposal"""
        preview = f"""=== EVOLUTION PROPOSAL ===
ID: {self.id}
Title: {self.title}
Reason: {self.reason}
Created: {self.created_at}
Status: {self.status}

Proposed changes:
"""
        for change in self.changes:
            file_path = change.get('file', '(unknown)')
            content = change.get('content', '')
            preview += f"\n--- {file_path} ---\n"
            preview += content[:500]
            if len(content) > 500:
                preview += "\n... (truncated)"
        
        return preview
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'title': self.title,
            'reason': self.reason,
            'changes': self.changes,
            'created_at': self.created_at,
            'status': self.status
        }


# For testing
if __name__ == "__main__":
    print("Starting self-modification system...")

    modifier = SelfModifier()

    # Test: read a file
    content = modifier.read_file("core/memory.py")
    if content:
        print(f"Read core/memory.py: {len(content)} characters")

    # Test: view history
    history = modifier.get_modification_history()
    print(f"Registered modifications: {len(history)}")

    print("\n[OK] Self-modification system initialized")
    print("  ARIA can now modify its own code.")
    print("  The decision to do so is hers.")
