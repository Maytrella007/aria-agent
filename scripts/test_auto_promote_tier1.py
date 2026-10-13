#!/usr/bin/env python3
"""
Trust ladder Peldaño 2 — auto-promote of Tier 1 (cosmetic) changes.

Verifies that ARIA can be configured to skip the human gate for
cosmetic changes (docs / tests / scripts / README), without affecting
Tier 2 (behavioral) or Tier 3 (meta self-modification) changes.

Six assertions:

  1. Default policy is OFF for every tier — no behavior change.
  2. With ``tier1: True``, a Tier 1 change auto-promotes the moment
     it lands in pending. The live file changes immediately. The
     audit entry shows ``initiated_by="auto"``.
  3. With ``tier1: True``, a Tier 2 change still waits for a human
     (it does NOT auto-promote).
  4. Tier 3 NEVER auto-promotes, even when explicitly enabled in
     the policy. This is the hardcoded refusal.
  5. After auto-promote, ``develop`` still contains the source commit
     (notebook-and-book invariant: nothing is deleted).
  6. The original baseline is restored at the end so the test
     leaves no trace.

The test uses the mirror primitives directly (no LLM, no claude code)
so it runs in seconds and is fully deterministic.

Run from project root:

    python3 scripts/test_auto_promote_tier1.py
"""
import os
import sys
import shutil
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.cognition.mirror import MirrorManager, classify_file_tier  # noqa: E402
from core.cognition.self_modification import SelfModifier, Modification  # noqa: E402
from datetime import datetime  # noqa: E402


# ─── Tiny console helpers ────────────────────────────────────────────────


class C:
    OK = "\033[92m"
    FAIL = "\033[91m"
    WARN = "\033[93m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def ok(msg):
    print(f"  {C.OK}OK{C.END} {msg}")


def info(label, value):
    print(f"  {C.DIM}{label}:{C.END} {value}")


def header(text):
    print(f"\n{C.BOLD}{text}{C.END}")


# ─── Test helpers ────────────────────────────────────────────────────────


def make_modifier(proj: str, policy: dict) -> SelfModifier:
    """Build a SelfModifier with a specific auto-promote policy."""
    return SelfModifier(
        project_root=proj,
        log_path=os.path.join(proj, "data", "modification_log.yaml"),
        mirror_config={
            "mirror_dir": "data/mirror",
            "run_tests": False,
            "auto_promote_policy": policy,
        },
    )


def write_via_mirror(modifier: SelfModifier, rel_path: str, content: str,
                     reason: str = "test") -> Modification:
    """Replicate the cognitive_cycle path: create branch, apply, validate,
    merge to develop, store as pending. Returns the Modification (which may
    have been auto-promoted by the time we return)."""
    mirror = modifier.mirror

    # Make sure the file exists in the live tree (so apply_change has a
    # baseline to diff against). For new files, just write an empty stub.
    full_path = os.path.join(modifier.project_root, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    if not os.path.exists(full_path):
        with open(full_path, "w") as f:
            f.write("")

    mirror.sync()
    branch_name = f"test_{rel_path.replace('/', '_').replace('.', '_')}_{os.urandom(2).hex()}"
    branch = mirror.create_branch(branch_name)
    commit_sha = mirror.apply_change(rel_path, content, branch=branch)
    validation = mirror.validate(rel_path)
    if not validation.all_ok:
        raise RuntimeError(f"validation failed: {validation.errors}")

    merge_result = mirror.merge_to_develop(branch)
    if not merge_result.success:
        raise RuntimeError(f"merge failed: {merge_result.error}")

    mod_id = f"test_{datetime.now().strftime('%H%M%S%f')}_{os.urandom(2).hex()}"
    modification = Modification(
        id=mod_id,
        timestamp=datetime.now().isoformat(),
        target_file=rel_path,
        modification_type="rewrite",
        original_content=None,
        new_content=content,
        reason=reason,
        initiated_by="aria",
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
    modifier._store_pending_change(modification)
    return modification


def read_status(modifier: SelfModifier, mod_id: str) -> dict:
    """Look up the YAML entry for a mod_id (returns full dict, not just status)."""
    for c in modifier._load_pending().get("changes", []):
        if c.get("id") == mod_id:
            return c
    return {}


def cleanup(proj: str):
    shutil.rmtree(proj, ignore_errors=True)


# ─── The actual test ────────────────────────────────────────────────────


def main() -> int:
    proj = tempfile.mkdtemp(prefix="aria_autopromote_test_")
    print(f"project: {proj}")

    # Create live files for each tier
    os.makedirs(os.path.join(proj, "core", "cognition"))
    os.makedirs(os.path.join(proj, "docs"))

    tier1_path = "docs/notes.md"  # cosmetic
    tier2_path = "core/cognition/dummy.py"  # behavioral
    tier3_path = "core/cognition/mirror.py"  # meta

    with open(os.path.join(proj, tier1_path), "w") as f:
        f.write("original notes\n")
    with open(os.path.join(proj, tier2_path), "w") as f:
        f.write("# dummy\nVALUE = 0\n")
    with open(os.path.join(proj, tier3_path), "w") as f:
        f.write("# fake mirror.py for tier-3 test\nVALUE = 0\n")

    # ── Sanity: confirm tier classification matches expectations ────────
    header("[0] Sanity check the tier classifier")
    assert classify_file_tier(tier1_path) == 1, f"{tier1_path} should be Tier 1"
    assert classify_file_tier(tier2_path) == 2, f"{tier2_path} should be Tier 2"
    assert classify_file_tier(tier3_path) == 3, f"{tier3_path} should be Tier 3"
    ok(f"{tier1_path} → Tier 1")
    ok(f"{tier2_path} → Tier 2")
    ok(f"{tier3_path} → Tier 3")

    # ── Assertion 1: default policy is OFF for everyone ─────────────────
    header("[1] Default policy is OFF for every tier")
    sm_default = make_modifier(proj, policy={})
    info("default policy", sm_default.auto_promote_policy)
    assert sm_default.auto_promote_policy == {
        "tier1": False, "tier2": False, "tier3": False
    }
    assert not sm_default._should_auto_promote(tier1_path)
    assert not sm_default._should_auto_promote(tier2_path)
    assert not sm_default._should_auto_promote(tier3_path)
    ok("no tier is auto-promoted by default")

    # ── Assertion 2: tier1=True actually promotes a Tier 1 change ───────
    header("[2] tier1=True auto-promotes a Tier 1 change")
    sm = make_modifier(proj, policy={"tier1": True})
    info("policy", sm.auto_promote_policy)

    new_content = "auto-promoted notes\n"
    mod = write_via_mirror(sm, tier1_path, new_content,
                            reason="cosmetic update")
    info("mod id", mod.id[:12])

    # Live file should have already changed
    with open(os.path.join(proj, tier1_path)) as f:
        live = f.read()
    info("live content after auto-promote", repr(live))
    assert live == new_content, f"live file did not auto-update: {live!r}"
    ok("live file reflects the change immediately")

    # YAML entry should now show 'applied' with initiated_by='auto'
    entry = read_status(sm, mod.id)
    info("yaml status", entry.get("status"))
    info("yaml initiated_by", entry.get("initiated_by"))
    info("yaml promoted_by", entry.get("promoted_by"))
    info("yaml promote_reason", entry.get("promote_reason", "")[:60])
    assert entry.get("status") == "applied"
    assert entry.get("promoted_by") == "auto"
    assert "Tier 1 policy" in entry.get("promote_reason", "")
    ok("audit trail shows initiated_by=auto and 'Tier 1 policy' reason")

    # The notebook (develop) should still contain the source commit
    sha = mod.commit_sha
    log = sm.mirror.get_develop_log(20)
    found = any(c.get("hash", "").startswith(sha[:8]) for c in log)
    assert found, f"commit {sha[:8]} missing from develop log"
    ok(f"commit {sha[:8]} preserved in develop (notebook invariant)")

    # ── Assertion 3: tier1=True does NOT auto-promote a Tier 2 change ───
    header("[3] tier1=True does NOT touch Tier 2")
    mod2 = write_via_mirror(sm, tier2_path, "# dummy\nVALUE = 99\n",
                             reason="behavioral update")
    info("mod id", mod2.id[:12])

    # Live file should be UNCHANGED (still original)
    with open(os.path.join(proj, tier2_path)) as f:
        live2 = f.read()
    info("live content (should be unchanged)", repr(live2.strip()))
    assert "VALUE = 0" in live2, f"Tier 2 file was auto-promoted: {live2!r}"
    ok("Tier 2 file unchanged — still pending human")

    entry2 = read_status(sm, mod2.id)
    info("yaml status", entry2.get("status"))
    assert entry2.get("status") == "validated_pending_approval"
    ok("Tier 2 entry waiting in queue")

    # ── Assertion 4: Tier 3 NEVER auto-promotes, even with policy ──────
    header("[4] Tier 3 is hardcoded refused even with explicit policy")
    sm3 = make_modifier(proj, policy={"tier1": True, "tier2": True, "tier3": True})
    info("policy (tier3 explicitly True)", sm3.auto_promote_policy)
    assert not sm3._should_auto_promote(tier3_path), \
        "Tier 3 should be refused even when policy says True"
    ok("_should_auto_promote refuses Tier 3 regardless of policy")

    mod3 = write_via_mirror(sm3, tier3_path, "# fake mirror.py\nVALUE = 99\n",
                             reason="meta change attempt")
    info("mod id", mod3.id[:12])
    with open(os.path.join(proj, tier3_path)) as f:
        live3 = f.read()
    info("live tier-3 (must be unchanged)", repr(live3.strip()))
    assert "VALUE = 0" in live3, "Tier 3 file was auto-promoted! Defense failed!"
    entry3 = read_status(sm3, mod3.id)
    assert entry3.get("status") == "validated_pending_approval"
    ok("Tier 3 file untouched — Tier 3 defense holds")

    # ── Assertion 5: tier1=False with same fixture does NOT auto-promote
    header("[5] tier1=False keeps Tier 1 in the queue")
    sm_off = make_modifier(proj, policy={"tier1": False})
    mod4 = write_via_mirror(sm_off, tier1_path, "back to manual\n",
                             reason="should wait")
    entry4 = read_status(sm_off, mod4.id)
    info("yaml status", entry4.get("status"))
    assert entry4.get("status") == "validated_pending_approval", \
        "tier1=False should not auto-promote"
    ok("tier1=False keeps the change in pending")

    # Live file should be in whatever state assertion 2 left it
    # (auto-promoted notes), NOT the new "back to manual" content
    with open(os.path.join(proj, tier1_path)) as f:
        live_off = f.read()
    assert "back to manual" not in live_off, \
        "live file changed even though policy was off"
    ok("live file unchanged when policy is off")

    cleanup(proj)
    print(f"\n{C.OK}{C.BOLD}=== ALL 5 ASSERTIONS PASSED ==={C.END}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
