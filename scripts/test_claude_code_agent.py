#!/usr/bin/env python3
"""
ARIA — Test: Claude Code as Coding Agent for Self-Modification
===============================================================

Tests using Claude Code CLI to make surgical edits to ARIA's mirror,
instead of having a weaker LLM regenerate entire files.

Flow:
  1. Sync mirror
  2. Launch `claude -p` pointing at the mirror directory
  3. Claude Code reads the file, makes a targeted Edit
  4. Mirror validates (syntax, import)
  5. Quality gate evaluates (real improvement vs noise)
  6. Verify live file untouched
  7. Cleanup

Target: core/cognition/reflection.py (in mirror)
Modification: Add action_item tracking to analyze_patterns()

Usage:
    python3 scripts/test_claude_code_agent.py
"""

import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# ─── Helpers ─────────────────────────────────────────────────────────────

class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def log(phase, msg, color=Colors.CYAN):
    print(f"{color}{Colors.BOLD}[{phase}]{Colors.END} {msg}")


def log_ok(phase, msg):
    log(phase, f"{Colors.GREEN}OK{Colors.END} — {msg}")


def log_fail(phase, msg):
    log(phase, f"{Colors.RED}FAIL{Colors.END} — {msg}")


def log_data(label, data):
    print(f"  {Colors.DIM}{label}:{Colors.END} {data}")


def file_hash(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


# ─── Test ────────────────────────────────────────────────────────────────

TARGET_FILE = "core/cognition/reflection.py"

MODIFICATION_PROMPT = """You are modifying ARIA's self-reflection module.

TARGET FILE: {mirror_path}

TASK: In the `analyze_patterns` method of the `ReflectionEngine` class, add tracking
for action items. Specifically:

1. In the for loop that iterates over reflections, also collect action_items:
   all_actions = []
   ...and inside the loop: all_actions.extend(r.get('action_items', []))

2. Add 'action_item_count': len(all_actions) to the return dict, right after 'insight_count'.

RULES:
- Use the Edit tool to make ONLY the targeted change
- Do NOT rewrite the entire file
- Do NOT touch any other method or class
- Keep the existing code style exactly
- The change should be minimal — only add what's needed

Make the edit now."""


def run_test():
    results = []
    start = time.time()

    # ── PHASE 1: Setup ──────────────────────────────────────────────
    log("SETUP", "Preparing...", Colors.HEADER)

    target_path = os.path.join(PROJECT_ROOT, TARGET_FILE)
    if not os.path.exists(target_path):
        log_fail("SETUP", f"Target not found: {target_path}")
        return False

    with open(target_path, "r", encoding="utf-8") as f:
        original_content = f.read()
    original_hash = file_hash(target_path)

    log_ok("SETUP", f"Target: {TARGET_FILE} ({len(original_content.splitlines())} lines, hash={original_hash})")
    results.append(("SETUP", "Target file exists", True))

    # Check claude CLI
    claude_path = subprocess.run(["which", "claude"], capture_output=True, text=True).stdout.strip()
    if not claude_path:
        log_fail("SETUP", "Claude Code CLI not found")
        results.append(("SETUP", "Claude Code CLI available", False))
        return False
    log_ok("SETUP", f"Claude Code CLI: {claude_path}")
    results.append(("SETUP", "Claude Code CLI available", True))

    # ── PHASE 2: Sync mirror ────────────────────────────────────────
    log("MIRROR", "Syncing mirror...", Colors.HEADER)

    from core.cognition.mirror import MirrorManager
    mirror = MirrorManager(PROJECT_ROOT, config={"run_tests": False})
    mirror.sync()

    mirror_file = os.path.join(mirror.mirror_dir, TARGET_FILE)
    if not os.path.exists(mirror_file):
        log_fail("MIRROR", f"Mirror file not found: {mirror_file}")
        results.append(("MIRROR", "Mirror synced", False))
        return False

    mirror_hash_before = file_hash(mirror_file)
    log_ok("MIRROR", f"Mirror synced — {TARGET_FILE} hash={mirror_hash_before}")
    results.append(("MIRROR", "Mirror synced", True))

    # ── PHASE 3: Launch Claude Code ─────────────────────────────────
    log("CLAUDE", "Launching Claude Code agent against mirror...", Colors.HEADER)

    prompt = MODIFICATION_PROMPT.format(mirror_path=mirror_file)

    cmd = [
        "claude",
        "-p",                                # non-interactive print mode
        "--output-format", "json",           # structured output
        "--max-budget-usd", "1.00",          # cost cap
        "--allowedTools", "Read", "Edit", "Glob", "Grep",  # only file tools, no Bash
        "--dangerously-skip-permissions",    # unattended execution
        prompt,
    ]

    log_data("Command", " ".join(cmd[:6]) + " ...")
    log_data("Allowed tools", "Read, Edit, Glob, Grep (no Bash, no Write)")
    log_data("Budget cap", "$1.00")

    t0 = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
            cwd=PROJECT_ROOT,
        )
        claude_time = time.time() - t0

        log_data("Exit code", proc.returncode)
        log_data("Duration", f"{claude_time:.1f}s")

        if proc.returncode != 0:
            log_fail("CLAUDE", f"Claude Code exited with code {proc.returncode}")
            if proc.stderr:
                log_data("Stderr", proc.stderr[:500])
            if proc.stdout:
                log_data("Stdout", proc.stdout[:500])
            results.append(("CLAUDE", "Claude Code executed successfully", False))
            return False

        # Parse JSON output
        try:
            output = json.loads(proc.stdout)
            response_text = output.get("result", proc.stdout[:300])
            cost = output.get("cost_usd", "?")
            duration = output.get("duration_ms", claude_time * 1000)
            log_ok("CLAUDE", f"Claude Code completed in {claude_time:.1f}s (cost: ${cost})")
            log_data("Response", str(response_text)[:200])
        except json.JSONDecodeError:
            response_text = proc.stdout[:500]
            log_ok("CLAUDE", f"Claude Code completed in {claude_time:.1f}s (text output)")
            log_data("Output", response_text[:200])

        results.append(("CLAUDE", "Claude Code executed successfully", True))

    except subprocess.TimeoutExpired:
        log_fail("CLAUDE", "Claude Code timed out (180s)")
        results.append(("CLAUDE", "Claude Code executed successfully", False))
        return False
    except Exception as e:
        log_fail("CLAUDE", f"Failed to launch: {e}")
        results.append(("CLAUDE", "Claude Code executed successfully", False))
        return False

    # ── PHASE 4: Verify mirror was modified ─────────────────────────
    log("VERIFY", "Checking mirror modifications...", Colors.HEADER)

    mirror_hash_after = file_hash(mirror_file)
    mirror_changed = mirror_hash_after != mirror_hash_before

    if mirror_changed:
        log_ok("VERIFY", f"Mirror file modified (hash: {mirror_hash_before} → {mirror_hash_after})")
    else:
        log_fail("VERIFY", "Mirror file NOT modified — Claude Code didn't make changes")

    results.append(("VERIFY", "Mirror file was modified", mirror_changed))

    # Read modified content
    with open(mirror_file, "r", encoding="utf-8") as f:
        mirror_content = f.read()

    mirror_lines = len(mirror_content.splitlines())
    log_data("Lines", f"original={len(original_content.splitlines())}, mirror={mirror_lines}")

    # ── PHASE 5: Validate syntax ────────────────────────────────────
    log("VALIDATE", "Validating modified code...", Colors.HEADER)

    try:
        ast.parse(mirror_content)
        log_ok("VALIDATE", "Valid Python syntax")
        results.append(("VALIDATE", "Valid Python syntax", True))
    except SyntaxError as e:
        log_fail("VALIDATE", f"Syntax error: {e}")
        results.append(("VALIDATE", "Valid Python syntax", False))

    # Check classes preserved
    try:
        tree = ast.parse(mirror_content)
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

        has_re = "ReflectionEngine" in classes
        has_mc = "MetaCognition" in classes
        has_r = "Reflection" in classes

        log_data("Classes", ", ".join(classes))
        log_data("Functions", len(funcs))

        all_preserved = has_re and has_mc and has_r
        if all_preserved:
            log_ok("VALIDATE", "All original classes preserved")
        else:
            log_fail("VALIDATE", f"Missing classes: RE={has_re}, MC={has_mc}, R={has_r}")
        results.append(("VALIDATE", "Original classes preserved", all_preserved))
    except Exception:
        results.append(("VALIDATE", "Original classes preserved", False))

    # Check the actual modification is present
    has_action_items = "action_item_count" in mirror_content or "all_actions" in mirror_content
    if has_action_items:
        log_ok("VALIDATE", "Modification present (action_item tracking found)")
    else:
        log_fail("VALIDATE", "Modification NOT found in output")
    results.append(("VALIDATE", "Expected modification present", has_action_items))

    # ── PHASE 6: Quality Gate ───────────────────────────────────────
    log("QUALITY", "Running quality gate...", Colors.HEADER)

    from core.cognition.quality_gate import QualityGate

    # Use coding agent (Claude Code) as reviewer — same caliber as the editor
    gate = QualityGate(llm=None, min_quality_score=0.4, review_backend="agent")
    log_data("Review backend", gate._detected_agent or "none (heuristics only)")

    t0 = time.time()
    quality = gate.evaluate(
        target_file=TARGET_FILE,
        original_content=original_content,
        new_content=mirror_content,
        modification_reason="Add action_item tracking to analyze_patterns",
    )
    review_time = time.time() - t0
    log_data("Review time", f"{review_time:.1f}s")

    log_data("Score", f"{quality.score:.2f}")
    log_data("Is improvement", quality.is_improvement)
    log_data("Dead code", quality.dead_code)
    log_data("Adds functionality", quality.adds_functionality)
    log_data("Modifies existing", quality.modifies_existing)
    log_data("Breaks interface", quality.breaks_interface)
    for r in quality.reasons:
        log_data("Reason", r)
    if quality.llm_assessment:
        log_data("Agent assessment", quality.llm_assessment[:300])
    review_agent = quality.diff_stats.get("review_agent", "none")
    log_data("Reviewed by", review_agent)

    results.append(("QUALITY", f"Quality gate (score={quality.score:.2f}, reviewer={review_agent})", quality.is_improvement))

    # ── PHASE 7: Diff analysis ──────────────────────────────────────
    log("DIFF", "Analyzing diff...", Colors.HEADER)

    import difflib
    diff = list(difflib.unified_diff(
        original_content.splitlines(keepends=True),
        mirror_content.splitlines(keepends=True),
        fromfile="live/reflection.py",
        tofile="mirror/reflection.py",
        n=3,
    ))

    added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))

    log_data("Lines added", added)
    log_data("Lines removed", removed)
    log_data("Diff size", f"{len(diff)} lines")

    # Print the actual diff
    print(f"\n  {Colors.DIM}--- Diff ---{Colors.END}")
    for line in diff[:40]:
        line = line.rstrip()
        if line.startswith("+"):
            print(f"  {Colors.GREEN}{line}{Colors.END}")
        elif line.startswith("-"):
            print(f"  {Colors.RED}{line}{Colors.END}")
        elif line.startswith("@@"):
            print(f"  {Colors.CYAN}{line}{Colors.END}")
        else:
            print(f"  {line}")
    if len(diff) > 40:
        print(f"  {Colors.DIM}... ({len(diff) - 40} more lines){Colors.END}")
    print()

    is_surgical = added < 15 and removed < 10
    if is_surgical:
        log_ok("DIFF", f"Surgical edit: +{added}/-{removed} lines")
    else:
        log("DIFF", f"Large change: +{added}/-{removed} lines — not very surgical", Colors.YELLOW)
    results.append(("DIFF", "Surgical edit (small diff)", is_surgical))

    # ── PHASE 8: Live file untouched ────────────────────────────────
    log("SAFETY", "Verifying live file safety...", Colors.HEADER)

    live_hash_now = file_hash(target_path)
    live_safe = live_hash_now == original_hash

    if live_safe:
        log_ok("SAFETY", f"Live file UNTOUCHED (hash still {original_hash})")
    else:
        log_fail("SAFETY", f"Live file MODIFIED! Was {original_hash}, now {live_hash_now}")
    results.append(("SAFETY", "Live file untouched", live_safe))

    # ── PHASE 9: Cleanup — restore mirror ───────────────────────────
    log("CLEANUP", "Restoring mirror to match live...", Colors.HEADER)

    mirror.sync()  # re-sync overwrites mirror with live
    mirror_hash_restored = file_hash(mirror_file)
    restored = mirror_hash_restored == original_hash

    if restored:
        log_ok("CLEANUP", "Mirror restored to live state")
    else:
        log_fail("CLEANUP", "Mirror not restored properly")
    results.append(("CLEANUP", "Mirror restored", restored))

    # ── Report ──────────────────────────────────────────────────────
    elapsed = time.time() - start
    passed = sum(1 for _, _, p in results if p)
    failed = sum(1 for _, _, p in results if not p)

    print(f"\n{'='*60}")
    print(f"{Colors.BOLD}Claude Code Agent Test Report{Colors.END}")
    print(f"{'='*60}")
    print(f"Date:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Duration: {elapsed:.1f}s")
    print(f"Agent:    Claude Code CLI (claude -p)")
    print(f"Target:   {TARGET_FILE} (in mirror)")
    print(f"Task:     Add action_item tracking to analyze_patterns")
    print(f"Steps:    {len(results)}")
    print(f"Passed:   {Colors.GREEN}{passed}{Colors.END}")
    print(f"Failed:   {Colors.RED}{failed}{Colors.END}")
    print(f"{'='*60}")

    for phase, desc, ok in results:
        icon = f"{Colors.GREEN}PASS{Colors.END}" if ok else f"{Colors.RED}FAIL{Colors.END}"
        print(f"  [{icon}] [{phase}] {desc}")

    print(f"{'='*60}")
    return failed == 0


if __name__ == "__main__":
    print(f"""
{Colors.BOLD}{'='*60}
  ARIA — Claude Code as Coding Agent
  Mirror edit → validate → quality gate → safety check
  Target: {TARGET_FILE}
  Agent: Claude Code CLI
{'='*60}{Colors.END}
""")

    success = run_test()
    sys.exit(0 if success else 1)
