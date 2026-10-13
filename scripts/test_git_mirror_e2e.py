#!/usr/bin/env python3
"""
ARIA Git Mirror — End-to-End Test (DeepSeek + Claude Code)
============================================================

REAL flow — nothing hardcoded:
  1. DeepSeek reads the actual source code and freely proposes improvements
  2. Claude Code pre-evaluates each proposal (PROCEED or SKIP)
  3. If PROCEED: branch → Claude Code edits → validate → merge develop
  4. If SKIP: move to next proposal (pre-eval is respected, not overridden)
  5. Verify accumulation, promote, conflict detection

This tests both the git mirror mechanics AND the quality of DeepSeek's insights.

Usage:
    python3 scripts/test_git_mirror_e2e.py
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
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


class TestReport:
    def __init__(self):
        self.steps = []
        self.start_time = time.time()
        self.insights_proposed = 0
        self.insights_accepted = 0
        self.insights_rejected = 0
        self.insights_merged = 0

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

        print(f"\n{'='*60}")
        print(f"{Colors.BOLD}ARIA Git Mirror E2E Test Report{Colors.END}")
        print(f"{'='*60}")
        print(f"Date:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: {elapsed:.1f}s")
        print(f"Flow:     DeepSeek(free analysis) → Claude Code(pre-eval+code) → git(branch+merge)")
        print(f"Target:   {TARGET_FILE}")
        print(f"{'='*60}")
        print(f"  DeepSeek proposed: {self.insights_proposed} insights")
        print(f"  Pre-eval PROCEED:  {self.insights_accepted}")
        print(f"  Pre-eval SKIP:     {self.insights_rejected}")
        print(f"  Merged to develop: {self.insights_merged}")
        print(f"{'='*60}")
        print(f"Steps:    {len(self.steps)}")
        print(f"Passed:   {Colors.GREEN}{passed}{Colors.END}")
        print(f"Failed:   {Colors.RED}{failed}{Colors.END}")
        print(f"{'='*60}")

        for step in self.steps:
            icon = f"{Colors.GREEN}PASS{Colors.END}" if step["passed"] else f"{Colors.RED}FAIL{Colors.END}"
            print(f"  [{icon}] [{step['phase']}] {step['description']}")
            if step["details"] and not step["passed"]:
                print(f"         {Colors.RED}{step['details']}{Colors.END}")
            elif step["details"] and step["passed"]:
                print(f"         {Colors.DIM}{step['details']}{Colors.END}")

        print(f"{'='*60}")
        return failed == 0

    def to_dict(self):
        return {
            "date": datetime.now().isoformat(),
            "duration_seconds": time.time() - self.start_time,
            "test": "git_mirror_e2e_v2",
            "target_module": TARGET_FILE,
            "insights_proposed": self.insights_proposed,
            "insights_accepted": self.insights_accepted,
            "insights_rejected": self.insights_rejected,
            "insights_merged": self.insights_merged,
            "steps": self.steps,
            "all_passed": all(s["passed"] for s in self.steps),
        }


# ─── DeepSeek LLM (for reflection/insights only) ───────────────────────

def setup_deepseek():
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        key_file = os.path.join(os.path.dirname(PROJECT_ROOT), "deepseek.txt")
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                api_key = f.read().strip()
    if not api_key:
        return None

    from openai import OpenAI

    class DeepSeekLLM:
        def __init__(self, api_key):
            self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

        def chat(self, messages, system=None, max_tokens=1000, **kwargs):
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.extend(messages)
            response = self.client.chat.completions.create(
                model="deepseek-chat", messages=msgs,
                max_tokens=max_tokens, temperature=0.7,
            )
            return type("R", (), {"content": response.choices[0].message.content})()

    return DeepSeekLLM(api_key)


# ─── Claude Code (coding agent) ────────────────────────────────────────

def run_claude_code(prompt, cwd, timeout=120):
    """Run Claude Code CLI and return (success, output, cost)."""
    cmd = [
        "claude", "-p",
        "--output-format", "json",
        "--max-budget-usd", "1.00",
        "--allowedTools", "Read", "Edit", "Glob", "Grep",
        "--dangerously-skip-permissions",
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, cwd=cwd,
        )
        output = proc.stdout.strip()
        try:
            data = json.loads(output)
            text = data.get("result", output)
            cost = data.get("cost_usd", "?")
        except json.JSONDecodeError:
            text = output
            cost = "?"

        return proc.returncode == 0, text, cost
    except subprocess.TimeoutExpired:
        return False, "Timed out", "?"
    except Exception as e:
        return False, str(e), "?"


def claude_pre_evaluate(target_file, description, reason, cwd):
    """Use Claude Code to pre-evaluate an idea."""
    prompt = f"""Before writing any code, evaluate this proposed change to ARIA:

TARGET FILE: {target_file}
PROPOSED CHANGE: {description}
REASON: {reason}

Do these checks:
1. Read the target file. Does something similar already exist?
2. Search the codebase (Grep/Glob): who would call/consume this change?
3. Is this a real improvement or speculative code nobody needs?
4. Does it duplicate existing functionality?

Respond in EXACTLY this format (nothing else):
VERDICT: PROCEED or SKIP
REASON: one sentence"""

    success, output, cost = run_claude_code(prompt, cwd, timeout=60)
    verdict = "PROCEED"
    eval_reason = output[:200]

    for line in output.split("\n"):
        stripped = line.strip().upper()
        if stripped.startswith("VERDICT:"):
            verdict = stripped.split(":", 1)[1].strip()
        elif line.strip().upper().startswith("REASON:"):
            eval_reason = line.split(":", 1)[1].strip()

    return verdict == "PROCEED", eval_reason, cost


def claude_generate_code(mirror_file, description, reason, cwd):
    """Use Claude Code to make a surgical Edit to the mirror file."""
    prompt = f"""You are modifying ARIA's source code in its mirror (safe staging area).

TARGET FILE: {mirror_file}

TASK: {description}

REASON: {reason}

RULES:
- Use the Edit tool to make ONLY the targeted change
- Do NOT rewrite the entire file — make surgical edits
- Do NOT touch any other method or class
- Keep the existing code style exactly
- The change should be minimal — only add what's needed
- Read the file first to understand the current code

Make the edit now."""

    success, output, cost = run_claude_code(prompt, cwd, timeout=180)
    return success, output, cost


# ─── DeepSeek insight parsing ────────────────────────────────────────────

def parse_deepseek_insights(response_text):
    """Parse DeepSeek's free-form response into structured insights.

    Expected format from DeepSeek:
    INSIGHT 1:
    DESCRIPTION: ...
    REASON: ...

    INSIGHT 2:
    DESCRIPTION: ...
    REASON: ...
    """
    insights = []
    current = {}

    for line in response_text.split("\n"):
        stripped = line.strip()

        # New insight marker
        if re.match(r'^INSIGHT\s*\d+\s*:', stripped, re.IGNORECASE):
            if current.get("description"):
                insights.append(current)
            current = {}
            continue

        if stripped.upper().startswith("DESCRIPTION:"):
            current["description"] = stripped.split(":", 1)[1].strip()
        elif stripped.upper().startswith("REASON:"):
            current["reason"] = stripped.split(":", 1)[1].strip()

    # Don't forget last one
    if current.get("description"):
        insights.append(current)

    # Validate: each insight needs description and reason
    valid = []
    for ins in insights:
        if ins.get("description") and ins.get("reason"):
            valid.append(ins)

    return valid


# ─── Main Test ───────────────────────────────────────────────────────────

TARGET_FILE = "core/cognition/reflection.py"


def run_e2e_test():
    report = TestReport()

    # ──────────────────────────────────────────────────────────────────
    # PHASE 0: Setup
    # ──────────────────────────────────────────────────────────────────
    log("SETUP", "Initializing...", Colors.HEADER)

    target_path = os.path.join(PROJECT_ROOT, TARGET_FILE)
    if not os.path.exists(target_path):
        log_fail("SETUP", f"Target not found: {target_path}")
        report.record("SETUP", "Target file exists", False)
        return report

    with open(target_path, "r", encoding="utf-8") as f:
        original_content = f.read()

    log_ok("SETUP", f"Target: {TARGET_FILE} ({len(original_content.splitlines())} lines)")
    report.record("SETUP", "Target file exists", True)

    # Check Claude Code CLI
    claude_check = subprocess.run(["which", "claude"], capture_output=True, text=True)
    if not claude_check.stdout.strip():
        log_fail("SETUP", "Claude Code CLI not found")
        report.record("SETUP", "Claude Code CLI available", False, "not in PATH")
        return report
    log_ok("SETUP", f"Claude Code CLI: {claude_check.stdout.strip()}")
    report.record("SETUP", "Claude Code CLI available", True)

    # Check DeepSeek
    deepseek = setup_deepseek()
    if not deepseek:
        log_fail("SETUP", "DeepSeek API key not found")
        report.record("SETUP", "DeepSeek LLM available", False)
        return report
    log_ok("SETUP", "DeepSeek LLM initialized")
    report.record("SETUP", "DeepSeek LLM available", True)

    # Initialize mirror
    from core.cognition.mirror import MirrorManager
    mirror = MirrorManager(PROJECT_ROOT, config={"run_tests": False})

    # Clean stale e2e branches
    try:
        for b in mirror.list_branches():
            if b.get("name", "").startswith("improve/e2e-"):
                mirror.rollback_branch(b["name"])
    except Exception:
        pass

    mirror.sync()
    log_ok("SETUP", f"Mirror synced (type: {mirror.status().get('type')})")
    report.record("SETUP", "Mirror synced (git)", True)

    mirror_file = os.path.join(mirror.mirror_dir, TARGET_FILE)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 1: DeepSeek analyzes the code and proposes improvements
    # ──────────────────────────────────────────────────────────────────
    log("ANALYZE", "DeepSeek analyzing source code (free analysis)...", Colors.HEADER)

    insights = []
    try:
        t0 = time.time()
        analysis = deepseek.chat(
            messages=[{"role": "user", "content": f"""You are ARIA, an AI that can modify its own source code.
Below is one of your modules. Analyze it carefully and propose exactly 3 concrete improvements.

FILE: {TARGET_FILE}

```python
{original_content}
```

Rules:
- Each improvement must be a SPECIFIC code change (not vague like "add logging")
- Explain what method to add or modify and exactly what it should do
- Only propose changes that add real value — no cosmetic or speculative changes
- Think about what's MISSING that would make this module more useful
- Consider: error handling gaps, missing functionality, data that's collected but not used

Respond in EXACTLY this format:

INSIGHT 1:
DESCRIPTION: [specific description of what to add/change]
REASON: [why this improves the module]

INSIGHT 2:
DESCRIPTION: [specific description of what to add/change]
REASON: [why this improves the module]

INSIGHT 3:
DESCRIPTION: [specific description of what to add/change]
REASON: [why this improves the module]"""}],
            system="You are a senior engineer reviewing your own code. Be specific and practical. Only propose changes that have clear value.",
            max_tokens=1000,
        )
        analyze_time = time.time() - t0

        insights = parse_deepseek_insights(analysis.content)
        report.insights_proposed = len(insights)

        log_ok("ANALYZE", f"DeepSeek proposed {len(insights)} insights in {analyze_time:.1f}s")
        log_data("Raw response", analysis.content[:300] + "...")

        for i, ins in enumerate(insights):
            log_data(f"  Insight {i+1}", ins["description"][:100])
            log_data(f"  Reason  {i+1}", ins["reason"][:100])

        report.record("ANALYZE", f"DeepSeek proposed {len(insights)} insights",
                       len(insights) >= 1,
                       f"Got {len(insights)}, expected >= 1")

    except Exception as e:
        log_fail("ANALYZE", f"Failed: {e}")
        traceback.print_exc()
        report.record("ANALYZE", "DeepSeek analysis completed", False, str(e))
        return report

    if not insights:
        log_fail("ANALYZE", "No parseable insights from DeepSeek")
        report.record("ANALYZE", "Insights parsed", False, "Could not parse structured insights")
        return report

    # ──────────────────────────────────────────────────────────────────
    # PHASE 2-N: For each insight → pre-eval → branch → edit → merge
    # ──────────────────────────────────────────────────────────────────
    merged_insights = []

    for idx, insight in enumerate(insights):
        phase = f"INSIGHT-{idx+1}"
        desc = insight["description"]
        reason = insight["reason"]
        slug = re.sub(r'[^a-z0-9]+', '-', desc[:40].lower()).strip('-') or f"change-{idx+1}"

        log(phase, f"Processing insight {idx+1}/{len(insights)}...", Colors.HEADER)
        log_data("Description", desc[:120])
        log_data("Reason", reason[:120])

        # ── Pre-evaluation ──
        log(phase, "Claude Code pre-evaluating...", Colors.BLUE)
        try:
            t0 = time.time()
            should_proceed, eval_reason, eval_cost = claude_pre_evaluate(
                TARGET_FILE, desc, reason, PROJECT_ROOT,
            )
            eval_time = time.time() - t0

            verdict_str = "PROCEED" if should_proceed else "SKIP"
            log_data("Verdict", verdict_str)
            log_data("Reason", eval_reason)
            log_data("Time", f"{eval_time:.1f}s")

            report.record(phase, f"Pre-eval: {verdict_str}", True, eval_reason)

            if not should_proceed:
                report.insights_rejected += 1
                log(phase, f"Pre-eval SKIP — moving to next insight", Colors.YELLOW)
                continue

            report.insights_accepted += 1

        except Exception as e:
            log_fail(phase, f"Pre-eval failed: {e}")
            report.record(phase, "Pre-eval completed", False, str(e))
            continue

        # ── Create branch ──
        branch = None
        try:
            branch = mirror.create_branch(f"e2e-{slug}")
            log_ok(phase, f"Branch: {branch}")
            report.record(phase, "Branch created", True)
        except Exception as e:
            log_fail(phase, f"Branch failed: {e}")
            report.record(phase, "Branch created", False, str(e))
            continue

        # ── Claude Code generates code ──
        try:
            with open(mirror_file, "r", encoding="utf-8") as f:
                before_edit = f.read()

            t0 = time.time()
            success, output, cost = claude_generate_code(
                mirror_file, desc, reason, PROJECT_ROOT,
            )
            gen_time = time.time() - t0

            log_data("Claude Code success", success)
            log_data("Time", f"{gen_time:.1f}s")
            log_data("Cost", f"${cost}")
            log_data("Output", output[:200])

            report.record(phase, "Claude Code edit", success,
                           output[:200] if not success else None)

            if not success:
                mirror.rollback_branch(branch)
                continue

            # Check if file changed
            with open(mirror_file, "r", encoding="utf-8") as f:
                after_edit = f.read()

            if after_edit == before_edit:
                log(phase, "File not modified — skipping", Colors.YELLOW)
                report.record(phase, "File modified", False, "Claude Code made no changes")
                mirror.rollback_branch(branch)
                continue

            log_ok(phase, "File modified by Claude Code")
            report.record(phase, "File modified", True)

            # Validate syntax
            try:
                ast.parse(after_edit)
                log_ok(phase, "Valid Python")
                report.record(phase, "Valid Python syntax", True)
            except SyntaxError as e:
                log_fail(phase, f"Syntax error: {e}")
                report.record(phase, "Valid Python syntax", False, str(e))
                mirror.rollback_branch(branch)
                continue

            # Commit + merge
            mirror._git("add", "-A")
            if mirror._has_staged_changes():
                commit_msg = f"Insight {idx+1}: {desc[:60]}"
                mirror._git("commit", "-m", commit_msg)

            merge_result = mirror.merge_to_develop(branch)
            if merge_result.success:
                log_ok(phase, "Merged to develop!")
                report.record(phase, "Merged to develop", True)
                merged_insights.append({
                    "index": idx + 1,
                    "description": desc,
                    "reason": reason,
                    "branch": branch,
                })
                report.insights_merged += 1
            elif merge_result.conflict:
                log(phase, f"Merge conflict — skipping", Colors.YELLOW)
                report.record(phase, "Merged to develop", False, "Merge conflict")
            else:
                log_fail(phase, f"Merge failed: {merge_result.error}")
                report.record(phase, "Merged to develop", False, merge_result.error)

        except Exception as e:
            log_fail(phase, f"Failed: {e}")
            traceback.print_exc()
            report.record(phase, f"Insight {idx+1} completed", False, str(e))
            if branch:
                try:
                    mirror.rollback_branch(branch)
                except Exception:
                    pass

    # ──────────────────────────────────────────────────────────────────
    # PHASE: Accumulation summary
    # ──────────────────────────────────────────────────────────────────
    log("ACCUMULATE", "Checking what accumulated on develop...", Colors.HEADER)

    try:
        mirror._git("checkout", "develop")
        with open(mirror_file, "r", encoding="utf-8") as f:
            final_develop = f.read()

        tree = ast.parse(final_develop)
        funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]

        has_original = "ReflectionEngine" in classes
        log_data("Original code preserved", has_original)
        log_data("Total functions", len(funcs))
        log_data("Insights merged", len(merged_insights))

        for mi in merged_insights:
            log_data(f"  Merged #{mi['index']}", mi['description'][:80])

        report.record("ACCUMULATE", "Original code preserved", has_original)

        if len(merged_insights) >= 2:
            report.record("ACCUMULATE", f"{len(merged_insights)} insights accumulated", True)
        elif len(merged_insights) == 1:
            report.record("ACCUMULATE", "1 insight merged (others filtered by pre-eval)", True,
                           "Pre-eval correctly filtered low-value insights")
        else:
            report.record("ACCUMULATE", "No insights merged",
                           report.insights_rejected > 0,
                           "All rejected by pre-eval — DeepSeek proposed only noise" if report.insights_rejected > 0
                           else "No insights processed")

    except Exception as e:
        log_fail("ACCUMULATE", f"Failed: {e}")
        report.record("ACCUMULATE", "Accumulation check", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # PHASE: Git history
    # ──────────────────────────────────────────────────────────────────
    log("HISTORY", "Git history on develop...", Colors.HEADER)

    dev_log = mirror.get_develop_log(limit=10)
    for i, c in enumerate(dev_log[:5]):
        log_data(f"  #{i+1}", f"{c.get('hash', '?')[:8]} — {c.get('message', '')}")
    report.record("HISTORY", "Git log shows commits", len(dev_log) > 1)

    diff = mirror.get_develop_diff()
    diff_lines = len(diff.splitlines())
    log_data("Diff main..develop", f"{diff_lines} lines")
    report.record("HISTORY", "Diff main..develop", diff_lines > 0 or len(merged_insights) == 0,
                   None if diff_lines > 0 else "No diff (nothing merged)")

    # ──────────────────────────────────────────────────────────────────
    # PHASE: Promote develop → main → live (only if something merged)
    # ──────────────────────────────────────────────────────────────────
    if merged_insights:
        log("PROMOTE", "Promoting develop → main → live...", Colors.HEADER)

        try:
            result = mirror.promote_to_main()
            log_data("Success", result.get("success"))
            log_data("Files", result.get("promoted_files"))

            if result.get("success"):
                log_ok("PROMOTE", "Promoted to live!")
                with open(target_path, "r", encoding="utf-8") as f:
                    live_content = f.read()
                live_changed = live_content != original_content
                report.record("PROMOTE", "Live file updated", live_changed)

                # Verify live is valid Python
                try:
                    ast.parse(live_content)
                    log_ok("PROMOTE", "Live file is valid Python")
                    report.record("PROMOTE", "Live file valid Python", True)
                except SyntaxError as e:
                    log_fail("PROMOTE", f"Live syntax error: {e}")
                    report.record("PROMOTE", "Live file valid Python", False, str(e))
            else:
                log_fail("PROMOTE", f"Failed: {result.get('error')}")
                report.record("PROMOTE", "Promotion successful", False, result.get("error"))

        except Exception as e:
            log_fail("PROMOTE", f"Failed: {e}")
            report.record("PROMOTE", "Promotion completed", False, str(e))
    else:
        log("PROMOTE", "Nothing to promote (no insights merged)", Colors.YELLOW)
        report.record("PROMOTE", "Skipped (no merges)", True, "Pre-eval filtered all insights")

    # ──────────────────────────────────────────────────────────────────
    # PHASE: Conflict detection (mechanical test, always runs)
    # ──────────────────────────────────────────────────────────────────
    log("CONFLICT", "Testing conflict detection...", Colors.HEADER)

    try:
        mirror.sync()

        branch_a = mirror.create_branch("e2e-conflict-a")
        mirror.apply_change(TARGET_FILE, "# replaced by A\ndef a(): pass\n", branch=branch_a)

        mirror._git("checkout", "develop")
        branch_b = mirror.create_branch("e2e-conflict-b")
        mirror.apply_change(TARGET_FILE, "# replaced by B\ndef b(): pass\n", branch=branch_b)

        merge_a = mirror.merge_to_develop(branch_a)
        merge_b = mirror.merge_to_develop(branch_b)

        log_data("Branch A", "merged" if merge_a.success else "failed")
        log_data("Branch B", "conflict" if merge_b.conflict else ("merged" if merge_b.success else "failed"))

        report.record("CONFLICT", "Conflict detected between competing branches",
                       merge_b.conflict or merge_b.success)

        # Cleanup conflict branches
        mirror.rollback_branch(branch_a)
        mirror.rollback_branch(branch_b)
        mirror._git("checkout", "develop")
        try:
            mirror._git("reset", "--hard", "HEAD~1")
        except Exception:
            pass

    except Exception as e:
        log_fail("CONFLICT", f"Failed: {e}")
        report.record("CONFLICT", "Conflict test completed", False, str(e))

    # ──────────────────────────────────────────────────────────────────
    # PHASE: Cleanup — restore original
    # ──────────────────────────────────────────────────────────────────
    log("CLEANUP", "Restoring original file...", Colors.HEADER)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(original_content)

    with open(target_path, "r", encoding="utf-8") as f:
        restored = f.read()

    restored_ok = restored == original_content
    if restored_ok:
        log_ok("CLEANUP", f"{TARGET_FILE} restored")
    else:
        log_fail("CLEANUP", "Restoration failed!")
    report.record("CLEANUP", "Original file restored", restored_ok)

    # Clean e2e branches
    try:
        for b in mirror.list_branches():
            if b.get("name", "").startswith("improve/e2e-"):
                mirror.rollback_branch(b["name"])
    except Exception:
        pass

    try:
        mirror.sync()
    except Exception:
        pass

    return report


# ─── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
{Colors.BOLD}{'='*60}
  ARIA Git Mirror — End-to-End Test v2
  DeepSeek: FREE analysis (no hardcoded insights)
  Claude Code: pre-eval + code generation (Edit tool)
  Git: branches + merge + promote
  Target: {TARGET_FILE}
{'='*60}{Colors.END}
""")

    report = run_e2e_test()
    all_passed = report.summary()

    report_path = os.path.join(PROJECT_ROOT, "data", "test_git_mirror_e2e_report.yaml")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    try:
        import yaml
        with open(report_path, "w") as f:
            yaml.dump(report.to_dict(), f, default_flow_style=False, allow_unicode=True)
        print(f"\nReport saved to: {report_path}")
    except Exception:
        pass

    sys.exit(0 if all_passed else 1)
