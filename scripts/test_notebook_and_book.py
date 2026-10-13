"""End-to-end smoke test for the notebook-and-book self-modification model.

Spins up a throwaway project with mirror, has ARIA write 4 changes through
the legacy write_file path, then exercises:

  1. Pending queue listing — only 'validated_pending_approval' status shown
  2. reject_change — flips status, does NOT touch git
  3. develop log — rejected commit is still there
  4. promote_selected — cherry-picks selected SHAs to main and copies to live
  5. live state after promote — only approved files changed
  6. reopen_change — brings rejected back to the queue without replay
  7. promote of reopened — final state has all changes applied

Run from the project root:

    python3 scripts/test_notebook_and_book.py
"""
import os
import sys
import shutil
import tempfile

# Allow running from anywhere — find the project root by walking up
_here = os.path.dirname(os.path.abspath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, _root)

from core.cognition.self_modification import SelfModifier  # noqa: E402


def main() -> int:
    proj = tempfile.mkdtemp(prefix="aria_notebook_test_")
    print(f"project: {proj}")

    # Create 4 fake structural files (must be under core/ to trigger
    # the mirror branch flow in _requires_mirror).
    os.makedirs(os.path.join(proj, "core", "cognition"))
    for fname in ["file_a.py", "file_b.py", "file_c.py", "file_d.py"]:
        with open(os.path.join(proj, "core", "cognition", fname), "w") as fh:
            fh.write(f"# {fname}\nVALUE = 1\n")

    sm = SelfModifier(
        project_root=proj,
        log_path=os.path.join(proj, "data", "modification_log.yaml"),
        mirror_config={
            "enabled": True,
            "mirror_dir": "data/mirror",
            "run_tests": False,
        },
    )
    # Block the auto-promote inside write_file so changes stay in the
    # pending queue waiting for explicit human action.
    sm._confirm_promote = lambda path: False

    print("\n--- ARIA writes 4 changes ---")
    ids = []
    for i, fname in enumerate(["file_a.py", "file_b.py", "file_c.py", "file_d.py"], 1):
        rel = f"core/cognition/{fname}"
        mod = sm.write_file(
            rel, f"# {fname}\nVALUE = {100 + i}\n", f"Change #{i}", "aria"
        )
        sha = mod.commit_sha[:8] if mod.commit_sha else "?"
        print(f"  #{i} {rel}: status={mod.status} sha={sha}")
        if mod.status == "validated_pending_approval":
            ids.append(mod.id)

    assert len(ids) == 4, f"expected 4 pending, got {len(ids)}"
    assert len(sm.list_pending_changes()) == 4

    # Live should still be untouched
    for fname in ["file_a.py", "file_b.py", "file_c.py", "file_d.py"]:
        with open(os.path.join(proj, "core", "cognition", fname)) as fh:
            line = [l for l in fh if "VALUE" in l][0].strip()
            assert "= 1" in line, f"{fname} live state changed prematurely: {line}"

    # Reject change #2 — should NOT touch git
    print(f"\n--- reject #2 (id={ids[1][:8]}) ---")
    r = sm.reject_change(ids[1], reason="too aggressive", initiated_by="william")
    assert r.success
    assert len(sm.list_pending_changes()) == 3
    assert len(sm.list_rejected_changes()) == 1

    # The rejected commit is still on develop
    print("\n--- develop log (4 ARIA commits should remain) ---")
    aria_commits = 0
    for c in sm.mirror.get_develop_log(20):
        if "Change " in c.get("message", ""):
            aria_commits += 1
            print(f"  {c['hash'][:8]} {c['message']}")
    assert aria_commits == 4, f"develop should still have 4 ARIA commits, got {aria_commits}"

    # Promote 1, 3, 4 (skipping the rejected #2)
    print("\n--- promote_selected for ids 1, 3, 4 ---")
    results = sm.promote_selected(
        [ids[0], ids[2], ids[3]], reason="looks good", initiated_by="william"
    )
    for r in results:
        assert r.success, f"promote failed: {r.error_message}"
        print(f"  [OK] {r.target_file}")

    # Live state should reflect 1, _, 3, 4
    expected = {"file_a.py": "101", "file_b.py": "1", "file_c.py": "103", "file_d.py": "104"}
    for fname, want in expected.items():
        with open(os.path.join(proj, "core", "cognition", fname)) as fh:
            content = fh.read()
            assert f"VALUE = {want}" in content, f"{fname} expected {want}, got {content!r}"
    print("\n  live state OK: 101, 1, 103, 104")

    # Reopen the rejected #2
    print("\n--- reopen #2 ---")
    ro = sm.reopen_change(ids[1], initiated_by="william")
    assert ro.success
    assert len(sm.list_pending_changes()) == 1
    assert len(sm.list_rejected_changes()) == 0

    # Promote the reopened one
    print("\n--- promote reopened ---")
    fr = sm.promote_selected([ids[1]], reason="changed mind", initiated_by="william")
    assert fr[0].success, f"reopen promote failed: {fr[0].error_message}"
    print("  [OK]")

    # Final live state should have all 4 changes applied
    expected_final = {"file_a.py": "101", "file_b.py": "102", "file_c.py": "103", "file_d.py": "104"}
    for fname, want in expected_final.items():
        with open(os.path.join(proj, "core", "cognition", fname)) as fh:
            content = fh.read()
            assert f"VALUE = {want}" in content, f"{fname} expected {want}, got {content!r}"
    print("\n  final live state OK: 101, 102, 103, 104")

    shutil.rmtree(proj)

    # ------------------------------------------------------------------
    # Second pass: dependency surfacing via preview_reject
    # ------------------------------------------------------------------
    print("\n\n=== preview_reject: 2 changes touching the same file ===")

    proj2 = tempfile.mkdtemp(prefix="aria_notebook_dep_")
    print(f"project: {proj2}")
    os.makedirs(os.path.join(proj2, "core", "cognition"))
    with open(os.path.join(proj2, "core", "cognition", "shared.py"), "w") as fh:
        fh.write("# shared.py\nVALUE = 1\n")

    sm2 = SelfModifier(
        project_root=proj2,
        log_path=os.path.join(proj2, "data", "modification_log.yaml"),
        mirror_config={
            "enabled": True,
            "mirror_dir": "data/mirror",
            "run_tests": False,
        },
    )
    sm2._confirm_promote = lambda path: False

    # ARIA writes change A to shared.py
    mod_a = sm2.write_file(
        "core/cognition/shared.py",
        "# shared.py\nVALUE = 100\n",
        "first edit",
        "aria",
    )
    assert mod_a.status == "validated_pending_approval"
    print(f"  change A: id={mod_a.id[:8]} sha={mod_a.commit_sha[:8]}")

    # ARIA writes change B to the same file
    mod_b = sm2.write_file(
        "core/cognition/shared.py",
        "# shared.py\nVALUE = 200\n",
        "second edit",
        "aria",
    )
    assert mod_b.status == "validated_pending_approval"
    print(f"  change B: id={mod_b.id[:8]} sha={mod_b.commit_sha[:8]}")

    # preview_reject on A should warn about B
    print("\n--- preview_reject(A) ---")
    preview = sm2.preview_reject(mod_a.id)
    print(f"  found       : {preview['found']}")
    print(f"  rejectable  : {preview['rejectable']}")
    print(f"  target_file : {preview['target_file']}")
    print(f"  siblings    : {len(preview['siblings_sharing_files'])}")
    for s in preview["siblings_sharing_files"]:
        print(f"     → {s['id'][:8]} {s['target_file']}")
    print(f"  warning     : {preview['warning'][:80]}…")

    assert preview["found"], "preview should find the change"
    assert preview["rejectable"], "change should be rejectable"
    assert len(preview["siblings_sharing_files"]) == 1, "should warn about change B"
    assert preview["siblings_sharing_files"][0]["id"] == mod_b.id
    assert "touch the same" in preview["warning"]

    # preview_reject on a non-existent id
    print("\n--- preview_reject('nonexistent') ---")
    bogus = sm2.preview_reject("nonexistent")
    assert not bogus["found"]
    print(f"  found: False (correct)")

    # Reject A, then preview_reject on A again should say not rejectable
    print("\n--- reject A then preview_reject(A) ---")
    sm2.reject_change(mod_a.id, reason="testing", initiated_by="william")
    after = sm2.preview_reject(mod_a.id)
    assert after["found"]
    assert not after["rejectable"]
    print(f"  rejectable after reject: {after['rejectable']} (correct)")

    shutil.rmtree(proj2)

    print("\n=== ALL ASSERTIONS PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
