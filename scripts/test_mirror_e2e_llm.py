#!/usr/bin/env python3
"""
ARIA Mirror System — End-to-End Test with LLM (REAL CODEBASE)
===============================================================

This test validates the COMPLETE self-modification pipeline against
ARIA's REAL code — not an isolated fake directory.

Target: core/cognition/introspection.py (ARIA's self-awareness system)
Safety net: git (all changes can be reverted with git checkout)

Pipeline tested:
  1. LLM (DeepSeek) receives ARIA's real introspection module
  2. LLM generates an improvement to the module
  3. SelfModifier routes the write through the mirror
  4. Mirror validates (syntax, import check)
  5. Change is stored as validated_pending_approval
  6. Live code is verified UNCHANGED during pending state
  7. User approves → change is promoted to live code
  8. Post-promote state is recorded
  9. Backup is verified
  10. Rejection flow tested with a second modification
  11. Live code restored to original via git

Usage:
    python3 scripts/test_mirror_e2e_llm.py

    API key is read from ../deepseek.txt or DEEPSEEK_API_KEY env var.
"""

import ast
import difflib
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import datetime

# Add project root to path
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


def show_diff(original, modified, filename):
    """Show a unified diff between original and modified content."""
    orig_lines = (original or "").splitlines(keepends=True)
    mod_lines = (modified or "").splitlines(keepends=True)
    diff = difflib.unified_diff(orig_lines, mod_lines,
                                fromfile=f"a/{filename}",
                                tofile=f"b/{filename}",
                                lineterm="")
    diff_text = ""
    for line in diff:
        if line.startswith("+") and not line.startswith("+++"):
            diff_text += f"  {Colors.GREEN}{line}{Colors.END}\n"
        elif line.startswith("-") and not line.startswith("---"):
            diff_text += f"  {Colors.RED}{line}{Colors.END}\n"
        else:
            diff_text += f"  {line}\n"
    if diff_text:
        print(diff_text)
    else:
        print(f"  {Colors.DIM}(no differences){Colors.END}")


# ─── Test Report ─────────────────────────────────────────────────────────

class TestReport:
    def __init__(self):
        self.steps = []
        self.start_time = time.time()

    def record(self, phase, description, passed, details=None):
        self.steps.append({
            "phase": phase,
            "description": description,
            "passed": passed,
            "details": details,
            "timestamp": datetime.now().isoformat(),
        })

    def summary(self):
        elapsed = time.time() - self.start_time
        passed = sum(1 for s in self.steps if s["passed"])
        failed = sum(1 for s in self.steps if not s["passed"])
        total = len(self.steps)

        print(f"\n{'='*60}")
        print(f"{Colors.BOLD}ARIA Mirror E2E Test Report — REAL CODEBASE{Colors.END}")
        print(f"{'='*60}")
        print(f"Date:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: {elapsed:.1f}s")
        print(f"Target:   core/cognition/introspection.py")
        print(f"LLM:      DeepSeek (deepseek-chat)")
        print(f"Steps:    {total}")
        print(f"Passed:   {Colors.GREEN}{passed}{Colors.END}")
        print(f"Failed:   {Colors.RED}{failed}{Colors.END}")
        print(f"{'='*60}")

        for step in self.steps:
            icon = f"{Colors.GREEN}PASS{Colors.END}" if step["passed"] else f"{Colors.RED}FAIL{Colors.END}"
            print(f"  [{icon}] [{step['phase']}] {step['description']}")
            if step["details"] and not step["passed"]:
                print(f"         {Colors.RED}{step['details']}{Colors.END}")

        print(f"{'='*60}")
        return failed == 0

    def to_dict(self):
        return {
            "date": datetime.now().isoformat(),
            "duration_seconds": time.time() - self.start_time,
            "target_module": "core/cognition/introspection.py",
            "llm_provider": "deepseek",
            "llm_model": "deepseek-chat",
            "real_codebase": True,
            "steps": self.steps,
            "all_passed": all(s["passed"] for s in self.steps),
        }


# ─── Main Test ───────────────────────────────────────────────────────────

TARGET_FILE = "core/cognition/introspection.py"


def run_e2e_test():
    report = TestReport()

    # ──────────────────────────────────────────────────────────────────
    # PHASE 0: Setup — Verify environment
    # ──────────────────────────────────────────────────────────────────
    log("SETUP", "Verifying environment...", Colors.HEADER)

    # Verify we're in the real ARIA project
    target_path = os.path.join(PROJECT_ROOT, TARGET_FILE)
    if not os.path.exists(target_path):
        log_fail("SETUP", f"Target file not found: {target_path}")
        report.record("SETUP", "Target file exists", False, "File not found")
        return report

    log_ok("SETUP", f"Target: {TARGET_FILE}")
    report.record("SETUP", "Target file exists", True)

    # Read original content (for restoration later)
    with open(target_path, "r", encoding="utf-8") as f:
        original_content = f.read()

    log_data("Original size", f"{len(original_content)} chars, {len(original_content.splitlines())} lines")

    # Verify git is available as safety net
    try:
        git_status = subprocess.run(
            ["git", "status", "--porcelain", TARGET_FILE],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        log_ok("SETUP", "Git available as safety net")
        if git_status.stdout.strip():
            log("SETUP", f"  Warning: target has uncommitted changes: {git_status.stdout.strip()}", Colors.YELLOW)
        report.record("SETUP", "Git safety net available", True)
    except Exception:
        log("SETUP", "Git not available — proceeding without safety net", Colors.YELLOW)
        report.record("SETUP", "Git safety net available", False, "Git not found")

    # Load API key
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        key_file = os.path.join(os.path.dirname(PROJECT_ROOT), "deepseek.txt")
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                api_key = f.read().strip()

    if not api_key:
        log_fail("SETUP", "No DEEPSEEK_API_KEY found. Set env var or place in ../deepseek.txt")
        report.record("SETUP", "API key available", False, "No key found")
        return report

    log_ok("SETUP", f"API key loaded ({api_key[:8]}...)")
    report.record("SETUP", "API key available", True)

    # Clean any stale pending changes for our target
    from core.cognition.self_modification import SelfModifier
    from core.cognition.mirror import MirrorManager

    # Clear stale mirror data to start fresh
    mirror_pending = os.path.join(PROJECT_ROOT, "data", "mirror", "pending_promotions.yaml")
    if os.path.exists(mirror_pending):
        import yaml
        with open(mirror_pending, "r") as f:
            existing_pending = yaml.safe_load(f) or {}
        stale = [c for c in existing_pending.get("changes", []) if c.get("target_file") == TARGET_FILE]
        if stale:
            log("SETUP", f"Clearing {len(stale)} stale pending changes for {TARGET_FILE}", Colors.YELLOW)
            existing_pending["changes"] = [c for c in existing_pending.get("changes", []) if c.get("target_file") != TARGET_FILE]
            from core.infra.utils import atomic_write_yaml
            atomic_write_yaml(mirror_pending, existing_pending)

    log_ok("SETUP", "Environment ready")

    # ──────────────────────────────────────────────────────────────────
    # PHASE 1: LLM generates a real improvement
    # ──────────────────────────────────────────────────────────────────
    log("LLM", "Asking DeepSeek to improve ARIA's introspection module...", Colors.HEADER)

    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1",
        )

        prompt = f"""You are ARIA, an AI system that can modify its own code.
You are improving your own introspection system — the module that lets you
examine and understand your own source code.

CURRENT FILE: {TARGET_FILE}
```python
{original_content}
```

YOUR TASK: Add a new method `get_module_stats` to the `Introspector` class that
returns a dictionary with statistics about a given module file. The method should:

1. Accept a `relative_path: str` parameter (the file path relative to project root)
2. Return a Dict with these keys:
   - "path": the relative path
   - "total_lines": total number of lines
   - "code_lines": non-empty, non-comment lines
   - "classes": number of class definitions
   - "functions": number of function definitions (top-level + methods)
   - "imports": number of import statements
   - "docstrings": number of docstrings found
   - "complexity_estimate": "low" if functions < 5, "medium" if 5-15, "high" if > 15
3. Return {{"path": relative_path, "error": "file not found"}} if the file doesn't exist
4. Use ast.parse to count classes, functions, and imports accurately
5. Include a proper docstring for the method

IMPORTANT RULES:
- Return ONLY the complete modified Python file content
- Keep ALL existing code intact — do not remove or change anything
- Add the new method inside the Introspector class, after find_modification_points()
- The code MUST be valid Python that passes ast.parse()
- Keep the same import style and coding conventions
- Do NOT wrap in markdown code blocks
- Do NOT include any explanation, just the raw Python code"""

        log_data("Model", "deepseek-chat")
        log_data("Prompt length", f"{len(prompt)} chars")

        t0 = time.time()
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4000,
            temperature=0.3,
        )
        llm_time = time.time() - t0

        llm_output = response.choices[0].message.content.strip()

        # Strip markdown code fences if the LLM wrapped it anyway
        if llm_output.startswith("```"):
            lines = llm_output.split("\n")
            lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            llm_output = "\n".join(lines)

        log_ok("LLM", f"Generated {len(llm_output)} chars in {llm_time:.1f}s")
        log_data("Usage", f"input={response.usage.prompt_tokens}, output={response.usage.completion_tokens}")

        # Verify it's valid Python
        try:
            tree = ast.parse(llm_output)
            log_ok("LLM", "Generated code passes ast.parse()")
            report.record("LLM", "Code generation", True)
            report.record("LLM", "Generated code is valid Python", True)
        except SyntaxError as e:
            log_fail("LLM", f"Generated code has syntax error: {e}")
            report.record("LLM", "Code generation", True)
            report.record("LLM", "Generated code is valid Python", False, str(e))

        # Verify the new method exists AND original classes are preserved
        all_classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        all_funcs = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                all_funcs.append(node.name)

        has_new_method = "get_module_stats" in all_funcs
        has_introspector = "Introspector" in all_classes
        has_self_awareness = "SelfAwareness" in all_classes
        has_code_component = "CodeComponent" in all_classes

        log_data("Classes found", ", ".join(all_classes))
        log_data("New method found", str(has_new_method))

        report.record("LLM", "New method get_module_stats generated", has_new_method)
        report.record("LLM", "Original classes preserved (Introspector, SelfAwareness, CodeComponent)",
                       has_introspector and has_self_awareness and has_code_component)

        # Verify key existing methods are preserved
        critical_methods = ["_map_self", "get_file_content", "get_class_source",
                           "describe_self", "contemplate", "_build_self_model"]
        preserved = [m for m in critical_methods if m in all_funcs]
        all_preserved = len(preserved) == len(critical_methods)
        log_data("Critical methods preserved", f"{len(preserved)}/{len(critical_methods)}: {', '.join(preserved)}")
        report.record("LLM", "Critical existing methods preserved", all_preserved,
                       f"Missing: {set(critical_methods) - set(preserved)}" if not all_preserved else None)

    except Exception as e:
        log_fail("LLM", f"LLM call failed: {e}")
        traceback.print_exc()
        report.record("LLM", "Code generation", False, str(e))
        return report

    # ──────────────────────────────────────────────────────────────────
    # PHASE 2: Initialize mirror + SelfModifier pointing at REAL project
    # ──────────────────────────────────────────────────────────────────
    log("MIRROR", "Initializing mirror system against REAL ARIA codebase...", Colors.HEADER)

    mirror = MirrorManager(
        project_root=PROJECT_ROOT,
        config={"run_tests": False},
    )

    modifier = SelfModifier(
        project_root=PROJECT_ROOT,
        log_path=os.path.join(PROJECT_ROOT, "data", "modification_log.yaml"),
        backup_dir=os.path.join(PROJECT_ROOT, "data", "backups"),
        mirror=mirror,
        mirror_config={"require_confirmation": False},
    )

    log_ok("MIRROR", f"MirrorManager initialized (project_root={PROJECT_ROOT})")
    log_data("Mirror dir", mirror.mirror_dir)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 3: Write through SelfModifier (triggers full mirror pipeline)
    # ──────────────────────────────────────────────────────────────────
    log("MIRROR", f"Writing LLM-generated code to {TARGET_FILE} through SelfModifier...", Colors.HEADER)
    log("MIRROR", "Pipeline: sync → apply_change → validate(syntax+import) → pending_approval", Colors.DIM)

    t0 = time.time()
    modification = modifier.write_file(
        relative_path=TARGET_FILE,
        content=llm_output,
        reason="E2E test: LLM-generated improvement to Introspector (add get_module_stats method)",
        initiated_by="aria",
    )
    pipeline_time = time.time() - t0

    log_data("Modification ID", modification.id)
    log_data("Status", modification.status)
    log_data("Success", str(modification.success))
    log_data("Type", modification.modification_type)
    log_data("Pipeline time", f"{pipeline_time:.2f}s")

    if modification.validation_result:
        vr = modification.validation_result
        log_data("Syntax OK", str(vr.get("syntax_ok")))
        log_data("Import OK", str(vr.get("import_ok")))
        log_data("Tests OK", str(vr.get("tests_ok")))
        if vr.get("errors"):
            log_data("Errors", str(vr.get("errors")))
        log_data("Validation duration", f"{vr.get('duration_seconds', 0):.2f}s")

    report.record("MIRROR", "Write routed through mirror pipeline", True)
    report.record("MIRROR", "Validation passed (syntax + import)", modification.success,
                   modification.error_message if not modification.success else None)

    if modification.validation_result:
        report.record("MIRROR", "Syntax validation OK",
                       modification.validation_result.get("syntax_ok", False))
        report.record("MIRROR", "Import validation OK",
                       modification.validation_result.get("import_ok", False))

    is_pending = modification.status == "validated_pending_approval"
    if is_pending:
        log_ok("MIRROR", "Change is validated_pending_approval — NOT applied to live yet")
    else:
        # If require_confirmation is False, it auto-promotes
        if modification.status == "applied" and modification.success:
            log_ok("MIRROR", "Change auto-promoted (require_confirmation=False)")
        else:
            log_fail("MIRROR", f"Unexpected status: {modification.status}")
    report.record("MIRROR", "Modification reached correct state", modification.success)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 4: Verify live file state
    # ──────────────────────────────────────────────────────────────────
    log("VERIFY", "Checking live file state...", Colors.HEADER)

    with open(target_path, "r", encoding="utf-8") as f:
        live_content_now = f.read()

    if is_pending:
        # If pending, live should be UNCHANGED
        live_unchanged = live_content_now == original_content
        if live_unchanged:
            log_ok("VERIFY", "Live file UNCHANGED during pending state (mirror protection works!)")
        else:
            log_fail("VERIFY", "Live file was modified while still pending!")
        report.record("VERIFY", "Live file unchanged during pending state", live_unchanged)
    else:
        # If auto-promoted, live should have the new code
        live_changed = live_content_now != original_content
        if live_changed:
            log_ok("VERIFY", "Live file updated after auto-promotion")
        else:
            log_fail("VERIFY", "Live file was NOT updated after auto-promotion")
        report.record("VERIFY", "Live file updated after promotion", live_changed)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 5: If pending, inspect and approve
    # ──────────────────────────────────────────────────────────────────
    if is_pending:
        log("REVIEW", "Inspecting pending changes (simulates Review Panel)...", Colors.HEADER)

        pending = modifier.list_pending_changes()
        log_data("Pending count", len(pending))
        report.record("REVIEW", "Pending changes found", len(pending) > 0)

        if pending:
            change = pending[0]
            log_data("Change ID", change.get("id", "?")[:12])
            log_data("File", change.get("target_file"))
            log_data("Type", change.get("modification_type"))
            log_data("Reason", change.get("reason"))

            # Show diff
            log("REVIEW", "Diff of proposed change:", Colors.YELLOW)
            mirror_file = os.path.join(mirror.mirror_dir, TARGET_FILE)
            if os.path.exists(mirror_file):
                with open(mirror_file, "r", encoding="utf-8") as f:
                    mirror_content = f.read()
                show_diff(original_content, mirror_content, TARGET_FILE)

            # Retrieve by ID
            by_id = modifier.get_pending_change(change["id"])
            report.record("REVIEW", "Pending change retrievable by ID", by_id is not None)

        # Approve
        log("APPROVE", "Approving pending change → promoting to live code...", Colors.HEADER)

        if pending:
            change_id = pending[0]["id"]
            log_data("Approving ID", change_id[:12])

            result = modifier.approve_change_by_id(
                mod_id=change_id,
                reason="E2E test: User approved LLM-generated improvement to introspection",
                initiated_by="user",
            )

            log_data("Result status", result.status)
            log_data("Result success", str(result.success))

            if result.success:
                log_ok("APPROVE", "Change promoted to live code!")
            else:
                log_fail("APPROVE", f"Promotion failed: {result.error_message}")

            report.record("APPROVE", "Promotion successful", result.success,
                           result.error_message if not result.success else None)

            remaining = modifier.list_pending_changes()
            report.record("APPROVE", "Pending queue cleared", len(remaining) == 0)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 6: Verify the promoted code in live
    # ──────────────────────────────────────────────────────────────────
    log("VERIFY", "Verifying promoted code in live file...", Colors.HEADER)

    with open(target_path, "r", encoding="utf-8") as f:
        live_after_promote = f.read()

    live_has_new_code = live_after_promote != original_content
    if live_has_new_code:
        log_ok("VERIFY", "Live file contains LLM-generated improvement")
    else:
        log_fail("VERIFY", "Live file was NOT updated!")
    report.record("VERIFY", "Live file contains new code after promotion", live_has_new_code)

    # Verify the new method exists in live
    try:
        tree = ast.parse(live_after_promote)
        live_funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        live_classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]

        has_new = "get_module_stats" in live_funcs
        has_originals = "Introspector" in live_classes and "SelfAwareness" in live_classes

        log_data("Live functions", f"{len(live_funcs)} total")
        log_data("get_module_stats in live", str(has_new))
        log_data("Original classes in live", str(has_originals))

        report.record("VERIFY", "get_module_stats exists in live code", has_new)
        report.record("VERIFY", "Original classes preserved in live", has_originals)
    except SyntaxError as e:
        log_fail("VERIFY", f"Live file has syntax error after promotion: {e}")
        report.record("VERIFY", "Live code is valid Python after promotion", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # PHASE 7: Post-promote state
    # ──────────────────────────────────────────────────────────────────
    log("POST", "Checking post-promote state...", Colors.HEADER)

    post_state = modifier.get_post_promote_state()
    has_post_state = bool(post_state) and post_state.get("recommended_action") is not None

    if has_post_state:
        log_data("Recommended action", post_state.get("recommended_action"))
        log_data("Requires restart", str(post_state.get("requires_restart")))
        log_data("Affected paths", post_state.get("affected_paths"))
        log_data("Reasons", post_state.get("reasons", []))
        log_ok("POST", f"Post-promote state recorded: {post_state.get('recommended_action')}")
    else:
        log("POST", "No post-promote state recorded", Colors.YELLOW)

    report.record("POST", "Post-promote state recorded", has_post_state)
    if has_post_state:
        # core/cognition/ should trigger "restart" recommendation
        is_restart = post_state.get("recommended_action") == "restart"
        log_data("Classified as restart?", str(is_restart))
        report.record("POST", "Correctly classified as restart (core/cognition/ path)", is_restart)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 8: Backup verification
    # ──────────────────────────────────────────────────────────────────
    log("BACKUP", "Checking backup...", Colors.HEADER)

    backup_dir = os.path.join(PROJECT_ROOT, "data", "backups")
    backups = sorted(os.listdir(backup_dir)) if os.path.isdir(backup_dir) else []
    introspection_backups = [b for b in backups if "introspection" in b]
    has_backup = len(introspection_backups) > 0

    log_data("Total backups", len(backups))
    log_data("Introspection backups", len(introspection_backups))
    if introspection_backups:
        log_data("Latest", introspection_backups[-1])
    report.record("BACKUP", "Backup created for introspection.py", has_backup)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 9: Modification history
    # ──────────────────────────────────────────────────────────────────
    log("LOG", "Checking modification history...", Colors.HEADER)

    history = modifier.get_modification_history()
    log_data("History entries", len(history))

    has_log = len(history) > 0
    report.record("LOG", "Modification recorded in history", has_log)
    if history:
        last = history[-1]
        log_data("Last entry", f"{last.get('id', '?')[:12]} — {last.get('modification_type')} — {last.get('status')}")

    # ──────────────────────────────────────────────────────────────────
    # PHASE 10: Rejection flow — broken code blocked by mirror
    # ──────────────────────────────────────────────────────────────────
    log("REJECT", "Testing rejection flow with broken code...", Colors.HEADER)

    # Re-sync mirror after promotion
    mirror.sync()

    # Inject intentionally broken Python into the target
    broken_content = live_after_promote + "\n\ndef broken_function(:\n    pass\n"
    bad_mod = modifier.write_file(
        relative_path=TARGET_FILE,
        content=broken_content,
        reason="E2E test: Intentionally broken code to verify mirror blocks it",
        initiated_by="aria",
    )

    log_data("Broken mod status", bad_mod.status)
    log_data("Broken mod success", str(bad_mod.success))

    bad_was_blocked = bad_mod.status == "failed" and not bad_mod.success
    if bad_was_blocked:
        log_ok("REJECT", "Broken code BLOCKED by mirror validation!")
        log_data("Error", bad_mod.error_message)
    else:
        log_fail("REJECT", f"Expected failure, got status={bad_mod.status}")
    report.record("REJECT", "Broken code blocked by validation", bad_was_blocked)

    # Verify live file was not corrupted
    with open(target_path, "r", encoding="utf-8") as f:
        live_after_bad = f.read()

    live_safe_after_bad = live_after_bad == live_after_promote
    if live_safe_after_bad:
        log_ok("REJECT", "Live code untouched after blocked modification")
    else:
        log_fail("REJECT", "Live code was corrupted by broken modification!")
    report.record("REJECT", "Live code safe after blocked modification", live_safe_after_bad)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 11: Rejection flow — valid code rejected by user
    # ──────────────────────────────────────────────────────────────────
    log("REJECT", "Testing user rejection of valid code...", Colors.HEADER)

    mirror.sync()
    valid_addition = live_after_promote + '''

def _test_placeholder():
    """Placeholder function for E2E rejection test."""
    return "this should be rejected"
'''

    valid_mod = modifier.write_file(
        relative_path=TARGET_FILE,
        content=valid_addition,
        reason="E2E test: Valid code that user will reject",
        initiated_by="aria",
    )

    log_data("Valid mod status", valid_mod.status)

    if valid_mod.status == "validated_pending_approval":
        # User rejects it
        reject_result = modifier.reject_change(
            mod_id=valid_mod.id,
            reason="E2E test: User chose to reject this change",
            initiated_by="user",
        )
        log_data("Reject result", reject_result.status)

        with open(target_path, "r", encoding="utf-8") as f:
            live_after_user_reject = f.read()

        user_reject_safe = live_after_user_reject == live_after_promote
        if user_reject_safe:
            log_ok("REJECT", "User rejection preserved live code")
        else:
            log_fail("REJECT", "User rejection somehow modified live code!")

        remaining = modifier.list_pending_changes()
        queue_clear = len(remaining) == 0

        report.record("REJECT", "Valid code held as pending", True)
        report.record("REJECT", "User rejection preserved live code", user_reject_safe)
        report.record("REJECT", "Pending queue cleared after rejection", queue_clear)
    elif valid_mod.status == "applied" and valid_mod.success:
        # Auto-promoted due to require_confirmation=False
        log("REJECT", "Code auto-promoted (require_confirmation=False) — skipping rejection test", Colors.YELLOW)
        report.record("REJECT", "Valid code auto-promoted (cannot test rejection in this mode)", True)
    else:
        report.record("REJECT", "Valid code held as pending", False, f"Got: {valid_mod.status}")

    # ──────────────────────────────────────────────────────────────────
    # PHASE 12: Restore original file via git
    # ──────────────────────────────────────────────────────────────────
    log("RESTORE", "Restoring original file...", Colors.HEADER)

    # Write back the original content directly
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(original_content)

    # Verify restoration
    with open(target_path, "r", encoding="utf-8") as f:
        restored_content = f.read()

    restored_ok = restored_content == original_content
    if restored_ok:
        log_ok("RESTORE", f"{TARGET_FILE} restored to original")
    else:
        log_fail("RESTORE", "Restoration failed! Use: git checkout -- " + TARGET_FILE)
    report.record("RESTORE", "Original file restored", restored_ok)

    # Clean up post-promote state
    modifier.clear_post_promote_state()
    log_ok("RESTORE", "Post-promote state cleared")

    return report


# ─── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
{Colors.BOLD}{'='*60}
  ARIA Mirror System — End-to-End Test with REAL LLM
  Target: core/cognition/introspection.py
  LLM: DeepSeek (deepseek-chat)
  Safety: git + file restoration
{'='*60}{Colors.END}
""")

    report = run_e2e_test()
    all_passed = report.summary()

    # Save report
    report_path = os.path.join(PROJECT_ROOT, "data", "test_mirror_e2e_report.yaml")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    try:
        import yaml
        with open(report_path, "w") as f:
            yaml.dump(report.to_dict(), f, default_flow_style=False, allow_unicode=True)
        print(f"\nReport saved to: {report_path}")
    except Exception:
        report_path = report_path.replace(".yaml", ".json")
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nReport saved to: {report_path}")

    sys.exit(0 if all_passed else 1)
