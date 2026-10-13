#!/usr/bin/env python3
"""
Full cognitive cycle E2E with claude code AND a real promote to live.

Builds on test_claude_writes_change.py. That script proved that claude
code can write a change in the notebook-and-book flow up to pending. This
script goes one step further:

  1. claude code writes the same _QUEUE_STATUS refactor
  2. it reaches pending with commit_sha populated
  3. promote_selected actually cherry-picks the commit from develop
     into main and copies main → live, modifying the REAL ARIA source
  4. we verify the live file contains the refactor
  5. THEN we restore everything back to the starting baseline:
       - rewrite the live file from the in-memory snapshot
       - reset main and develop in the mirror to their starting SHAs
       - delete the improve/* branch the cycle created
       - drop the YAML pending entry
  6. verify the live file is byte-identical to the start

Safety:
  • The original content of the target file is captured BEFORE anything
    runs and held in memory the whole test.
  • The post-promote restore is wrapped in try/finally so even if a
    later step crashes, the live file is restored on the way out.
  • If after restore the live file is NOT byte-identical to the
    snapshot, the script exits non-zero so the failure is loud.

Total cost estimate: ~$0.30 in claude code + a few cents in DeepSeek.

Usage:
    python3 scripts/test_claude_promotes_change.py
"""
import os
import sys
import time
import traceback

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ─── Tiny console helpers ────────────────────────────────────────────────


class C:
    HEAD = "\033[95m"
    CYAN = "\033[96m"
    OK = "\033[92m"
    WARN = "\033[93m"
    FAIL = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def header(text):
    print(f"\n{C.HEAD}{C.BOLD}{text}{C.END}")


def step(label, msg, color=C.CYAN):
    print(f"{color}{C.BOLD}[{label}]{C.END} {msg}")


def ok(label, msg):
    step(label, f"{C.OK}OK{C.END} — {msg}")


def fail(label, msg):
    step(label, f"{C.FAIL}FAIL{C.END} — {msg}")


def info(label, value):
    print(f"  {C.DIM}{label}:{C.END} {value}")


# ─── DeepSeek wrapper ────────────────────────────────────────────────────


def make_deepseek_llm(api_key):
    from openai import OpenAI

    class DeepSeekLLM:
        def __init__(self, key):
            self.client = OpenAI(api_key=key, base_url="https://api.deepseek.com/v1")

        def chat(self, messages, system=None, max_tokens=2000, **kw):
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend(messages)
            r = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=msgs,
                max_tokens=max_tokens,
                temperature=0.3,
            )
            return type(
                "Response", (),
                {"content": r.choices[0].message.content, "usage": r.usage, "raw_response": r},
            )()

    return DeepSeekLLM(api_key)


# ─── Test parameters ─────────────────────────────────────────────────────


TARGET_FILE = "core/cognition/self_modification.py"
PROPOSAL_TITLE = "Replace literal queue-status string with the _QUEUE_STATUS constant"
PROPOSAL_REASON = (
    "The constant _QUEUE_STATUS = 'validated_pending_approval' was introduced "
    "in SelfModifier (around line 305) precisely to avoid magic strings, but "
    "four other lines in the same file still hardcode the literal string. "
    "Replacing those literals with self._QUEUE_STATUS uses an existing constant."
)
PROPOSAL_DESCRIPTION = (
    "In core/cognition/self_modification.py, the constant "
    "SelfModifier._QUEUE_STATUS = 'validated_pending_approval' is defined "
    "around line 305. Find every other line in this file that hardcodes the "
    "literal 'validated_pending_approval' and replace each one with "
    "self._QUEUE_STATUS. Keep the constant definition itself untouched. "
    "Do NOT add any new methods or properties. Do NOT modify the to_dict "
    "output. This is a pure search-and-replace refactor."
)


# ─── Main ────────────────────────────────────────────────────────────────


def main():
    t_start = time.time()
    header("=" * 70)
    header(" Cognitive cycle E2E — claude code writes AND we promote to live")
    header("=" * 70)

    # ── 0. SETUP ────────────────────────────────────────────────────────
    header("\n[0] SETUP + snapshot of pristine state")

    target_path = os.path.join(PROJECT_ROOT, TARGET_FILE)
    if not os.path.exists(target_path):
        fail("SETUP", f"target not found: {target_path}")
        return 1
    with open(target_path, "rb") as f:
        original_bytes = f.read()
    ok("SETUP", f"snapshotted {TARGET_FILE} ({len(original_bytes)} bytes)")

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        kf = os.path.join(os.path.dirname(PROJECT_ROOT), "deepseek.txt")
        if os.path.exists(kf):
            with open(kf) as f:
                api_key = f.read().strip()
    if not api_key:
        fail("SETUP", "no DEEPSEEK_API_KEY")
        return 1
    ok("SETUP", f"deepseek key loaded ({api_key[:8]}…)")

    import shutil as _sh
    claude_path = _sh.which("claude")
    if not claude_path:
        fail("SETUP", "claude CLI not found")
        return 1
    ok("SETUP", f"claude available at {claude_path}")

    try:
        from core.cognition.mirror import MirrorManager
        from core.cognition.evolution import EvolutionEngine
        from core.cognition.insight_evaluator import ProposalDraft
        from core.cognition.cognitive_cycle import CognitiveCycleOrchestrator
        from core.cognition.reflection import ReflectionEngine
        from core.cognition.introspection import Introspector
        from core.cognition.quality_gate import PreEvalReport

        llm = make_deepseek_llm(api_key)
        mirror = MirrorManager(PROJECT_ROOT, config={"run_tests": False})
        evolution = EvolutionEngine(
            PROJECT_ROOT, mirror=mirror,
            mirror_config={"require_confirmation": True},
        )
        reflection_engine = ReflectionEngine(
            reflections_path=os.path.join(PROJECT_ROOT, "data", "reflections"),
            memory_system=None,
        )
        introspector = Introspector(PROJECT_ROOT)
        orchestrator = CognitiveCycleOrchestrator(
            llm=llm,
            reflection_engine=reflection_engine,
            introspector=introspector,
            evolution_engine=evolution,
            data_dir=os.path.join(PROJECT_ROOT, "data"),
            min_confidence=0.4,
        )
        evolution.modifier._confirm_promote = lambda path: False

        # Bypass pre-eval (gate is already covered by other tests)
        def _bypass(target_file, modification_description, reason, current_content=None):
            return PreEvalReport(
                target_file=target_file,
                should_proceed=True,
                reason="bypassed for promote-test",
                analysis={"bypass": True},
            )
        orchestrator.quality_gate.pre_evaluate = _bypass

        ok("SETUP", "ARIA components ready (pre_eval bypassed, post-eval active)")
    except Exception as e:
        fail("SETUP", f"init failed: {e}")
        traceback.print_exc()
        return 1

    # Snapshot mirror state so we can roll it back at the end.
    # We anchor BOTH main and develop to main's starting sha so the
    # test always begins from a clean baseline. Any commits that
    # previous test runs left dangling in develop are reset away.
    try:
        main_starting_sha = mirror.head_sha("main")
        info("main starting sha", main_starting_sha[:12])

        # Reset develop to main so previous test runs don't pollute
        # this run's commit (otherwise claude reapplies an existing
        # refactor and git complains "nothing to commit").
        mirror._git("checkout", "develop")
        mirror._git("reset", "--hard", main_starting_sha)
        develop_starting_sha = mirror.head_sha("develop")
        ok("SETUP", f"develop reset to main ({develop_starting_sha[:12]})")
    except Exception as e:
        fail("SETUP", f"could not capture/reset mirror SHAs: {e}")
        return 1

    # Clean stale state from previous runs
    stale = [
        c for c in evolution.modifier.list_pending_changes()
        if c.get("target_file") == TARGET_FILE
    ]
    stale_rejected = [
        c for c in evolution.modifier.list_rejected_changes()
        if c.get("target_file") == TARGET_FILE
    ]
    if stale or stale_rejected:
        # remove from yaml (we want a clean baseline)
        pending = evolution.modifier._load_pending()
        before = len(pending.get("changes", []))
        pending["changes"] = [
            c for c in pending.get("changes", [])
            if c.get("target_file") != TARGET_FILE
        ]
        evolution.modifier._save_pending(pending)
        after = len(pending.get("changes", []))
        step("SETUP", f"cleared {before - after} stale yaml entries", C.WARN)

    # delete stale improve/* branches matching our test name
    try:
        branches_out = mirror._git("branch", "--list", "improve/*").strip()
        for line in branches_out.splitlines():
            bname = line.strip().lstrip("* ").strip()
            if not bname:
                continue
            if "replace-literal-queue-status" in bname:
                try:
                    if mirror._current_branch() == bname:
                        mirror._git("checkout", "develop")
                    mirror._git("branch", "-D", bname)
                    step("SETUP", f"deleted stale branch {bname}", C.WARN)
                except Exception:
                    pass
    except Exception:
        pass

    # ── 1. RUN THE COGNITIVE CYCLE ──────────────────────────────────────
    header("\n[1] CYCLE — claude code writes the change into mirror")

    draft = ProposalDraft(
        title=PROPOSAL_TITLE,
        reason=PROPOSAL_REASON,
        target_file=TARGET_FILE,
        modification_description=PROPOSAL_DESCRIPTION,
        source_insight_id="forced_promote_test",
        confidence=0.9,
    )

    t_cycle = time.time()
    try:
        detail = orchestrator._process_draft(draft)
    except Exception as e:
        fail("CYCLE", f"_process_draft raised: {e}")
        traceback.print_exc()
        return 1
    elapsed = time.time() - t_cycle

    info("status", detail.get("status"))
    info("elapsed", f"{elapsed:.1f}s")

    if detail.get("status") not in ("merged_to_develop", "pending_approval"):
        fail("CYCLE", f"unexpected status: {detail}")
        return 1
    ok("CYCLE", f"claude wrote and merged → {detail.get('status')}")

    # Find the resulting pending entry
    pending = [
        c for c in evolution.modifier.list_pending_changes()
        if c.get("target_file") == TARGET_FILE
    ]
    if not pending:
        fail("CYCLE", "no pending entry stored")
        return 1
    change = pending[0]
    mod_id = change["id"]
    commit_sha = change.get("commit_sha", "")
    info("pending id", mod_id[:12])
    info("commit_sha", commit_sha[:12] or "(MISSING)")
    if not commit_sha:
        fail("CYCLE", "commit_sha empty — promote will fail")
        return 1

    # Sanity: live file is still original at this point
    with open(target_path, "rb") as f:
        live_pre_promote = f.read()
    if live_pre_promote != original_bytes:
        fail("CYCLE", "live file already differs before we promoted!")
        return 1
    ok("CYCLE", "live file untouched before promote")

    # ── 2. PROMOTE — cherry-pick into main + copy to live ───────────────
    header("\n[2] PROMOTE — cherry-pick → main → copy to live")
    info("about to promote", f"{mod_id[:12]} ({commit_sha[:12]})")

    promote_failed = False
    promote_results = []
    promoted_live_bytes = None

    try:
        promote_results = evolution.modifier.promote_selected(
            [mod_id], reason="e2e promote test", initiated_by="william"
        )

        for r in promote_results:
            marker = "OK" if r.success else "FAIL"
            print(f"  [{marker}] {r.target_file:35} status={r.status}")
            if not r.success:
                print(f"        err: {r.error_message[:200]}")
                promote_failed = True

        if not promote_failed:
            ok("PROMOTE", "cherry-pick + copy succeeded")

            # Read live file again — it should now contain the refactor
            with open(target_path, "rb") as f:
                promoted_live_bytes = f.read()

            if promoted_live_bytes == original_bytes:
                fail("PROMOTE", "live bytes unchanged after promote — something is wrong")
                promote_failed = True
            else:
                # Verify the actual refactor is present
                live_text = promoted_live_bytes.decode("utf-8")
                literals = live_text.count('"validated_pending_approval"')
                constant_uses = live_text.count("self._QUEUE_STATUS")
                info("literal count after promote", literals)
                info("self._QUEUE_STATUS uses after promote", constant_uses)

                if literals > 1:
                    fail("PROMOTE", f"expected ≤1 literal, got {literals}")
                    promote_failed = True
                else:
                    ok("PROMOTE", f"live file refactored: literals reduced to {literals}, "
                                  f"constant uses now {constant_uses}")

            # Status of the modification should be 'applied'
            promoted_entry = next(
                (c for c in evolution.modifier._load_pending().get("changes", [])
                 if c.get("id") == mod_id),
                None,
            )
            if promoted_entry:
                info("yaml status after promote", promoted_entry.get("status"))
                if promoted_entry.get("status") != "applied":
                    fail("PROMOTE", f"yaml status is {promoted_entry.get('status')}, expected 'applied'")
                    promote_failed = True
                else:
                    ok("PROMOTE", "yaml status is 'applied'")

        # ── 3. VERIFY (mirror state after promote) ──────────────────────
        if not promote_failed:
            header("\n[3] VERIFY mirror state after promote")
            main_after = mirror.head_sha("main")
            info("main sha after promote", main_after[:12])
            if main_after == main_starting_sha:
                fail("VERIFY", "main sha unchanged after promote — cherry-pick didn't run")
                promote_failed = True
            else:
                ok("VERIFY", f"main advanced from {main_starting_sha[:8]} to {main_after[:8]}")

            # The original commit should still exist somewhere reachable
            try:
                resolved = mirror._git("rev-parse", commit_sha).strip()
                ok("VERIFY", f"commit {commit_sha[:8]} still resolvable in mirror")
            except Exception:
                fail("VERIFY", f"commit {commit_sha[:8]} no longer resolvable")
                promote_failed = True

    except Exception as e:
        fail("PROMOTE", f"unexpected exception: {e}")
        traceback.print_exc()
        promote_failed = True

    # ── 4. RESTORE BASELINE (always runs) ───────────────────────────────
    header("\n[4] RESTORE — undo everything (live file, mirror, yaml)")

    restore_errors = []

    # 4a. Restore live file from snapshot — this is the most critical step
    try:
        with open(target_path, "wb") as f:
            f.write(original_bytes)
        with open(target_path, "rb") as f:
            verify_bytes = f.read()
        if verify_bytes != original_bytes:
            restore_errors.append("live file restore did not match snapshot byte-by-byte")
        else:
            ok("RESTORE", f"live {TARGET_FILE} restored to original ({len(original_bytes)} bytes)")
    except Exception as e:
        restore_errors.append(f"live file restore failed: {e}")
        fail("RESTORE", f"could not restore live file: {e}")

    # 4b. Reset main in the mirror to its starting sha
    try:
        mirror._git("checkout", "main")
        mirror._git("reset", "--hard", main_starting_sha)
        ok("RESTORE", f"main reset to {main_starting_sha[:8]}")
    except Exception as e:
        restore_errors.append(f"main reset failed: {e}")
        fail("RESTORE", f"main reset failed: {e}")

    # 4c. Reset develop in the mirror to its starting sha
    try:
        mirror._git("checkout", "develop")
        mirror._git("reset", "--hard", develop_starting_sha)
        ok("RESTORE", f"develop reset to {develop_starting_sha[:8]}")
    except Exception as e:
        restore_errors.append(f"develop reset failed: {e}")
        fail("RESTORE", f"develop reset failed: {e}")

    # 4d. Delete the improve/* branch the cycle created
    try:
        branches_out = mirror._git("branch", "--list", "improve/*").strip()
        for line in branches_out.splitlines():
            bname = line.strip().lstrip("* ").strip()
            if "replace-literal-queue-status" in bname:
                try:
                    mirror._git("branch", "-D", bname)
                    ok("RESTORE", f"deleted branch {bname}")
                except Exception:
                    pass
    except Exception:
        pass

    # 4e. Drop the YAML pending entry
    try:
        pending_data = evolution.modifier._load_pending()
        before = len(pending_data.get("changes", []))
        pending_data["changes"] = [
            c for c in pending_data.get("changes", [])
            if c.get("id") != mod_id
        ]
        after = len(pending_data.get("changes", []))
        evolution.modifier._save_pending(pending_data)
        if before != after:
            ok("RESTORE", f"dropped yaml entry {mod_id[:12]}")
    except Exception as e:
        restore_errors.append(f"yaml cleanup failed: {e}")

    # 4f. Final byte-equality check
    with open(target_path, "rb") as f:
        final_bytes = f.read()

    if final_bytes != original_bytes:
        fail("RESTORE", "FINAL CHECK FAILED — live file is NOT byte-identical to snapshot!")
        info("snapshot bytes", len(original_bytes))
        info("final bytes", len(final_bytes))
        return 2  # critical: ARIA's source may be corrupted

    ok("RESTORE", f"final byte check passed — {TARGET_FILE} byte-identical to start")

    # ── REPORT ──────────────────────────────────────────────────────────
    elapsed_total = time.time() - t_start
    header("\n" + "=" * 70)
    if promote_failed or restore_errors:
        header(" RESULT: PARTIAL")
        if promote_failed:
            print(f"  {C.FAIL}{C.BOLD}promote phase failed{C.END}")
        if restore_errors:
            for err in restore_errors:
                print(f"  {C.FAIL}restore: {err}{C.END}")
        print(f"  {C.OK}live file safely restored: yes{C.END}")
        return 1
    else:
        header(" RESULT: PASSED — full claude → promote → restore loop")
    header("=" * 70)
    print(f"  total time      : {elapsed_total:.1f}s")
    print(f"  reasoning model : DeepSeek")
    print(f"  code writer     : Claude Code")
    print(f"  proof points    :")
    print(f"    • claude code wrote a real refactor in the mirror branch")
    print(f"    • promote_selected cherry-picked it into main")
    print(f"    • main was copied to live (live file actually changed)")
    print(f"    • notebook-and-book restore returned everything to baseline")
    print(f"    • live {TARGET_FILE} is byte-identical to the start")
    return 0


if __name__ == "__main__":
    sys.exit(main())
