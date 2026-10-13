#!/usr/bin/env python3
"""
ARIA Cognitive Cycle — End-to-End Test with LLM
=================================================

Tests the COMPLETE cognitive cycle against ARIA's REAL codebase:

  1. FORCE a reflection with actionable insights about a real ARIA module
  2. InsightEvaluator reads the reflection, LLM classifies it as actionable
  3. CognitiveCycleOrchestrator generates code via LLM
  4. EvolutionEngine validates through mirror
  5. Change arrives at validated_pending_approval
  6. Verify the pending change exists and is NOT applied to live
  7. Clean up (reject the pending, restore state)

This proves the full loop: ARIA thinks → decides → generates code → mirror blocks
until human approves. The human always has the last word.

Target module: core/cognition/reflection.py
LLM: DeepSeek (deepseek-chat)
Safety: git + manual restoration

Usage:
    python3 scripts/test_cognitive_cycle_e2e.py
"""

import ast
import os
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
        print(f"{Colors.BOLD}ARIA Cognitive Cycle E2E Test Report{Colors.END}")
        print(f"{'='*60}")
        print(f"Date:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Duration: {elapsed:.1f}s")
        print(f"Cycle:    reflection → evaluator → code gen → mirror pending")
        print(f"Target:   core/cognition/reflection.py")
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
            "test": "cognitive_cycle_e2e",
            "target_module": "core/cognition/reflection.py",
            "steps": self.steps,
            "all_passed": all(s["passed"] for s in self.steps),
        }


# ─── Main Test ───────────────────────────────────────────────────────────

TARGET_FILE = "core/cognition/reflection.py"


def run_e2e_test():
    report = TestReport()

    # ──────────────────────────────────────────────────────────────────
    # PHASE 0: Setup
    # ──────────────────────────────────────────────────────────────────
    log("SETUP", "Initializing...", Colors.HEADER)

    # Verify target exists
    target_path = os.path.join(PROJECT_ROOT, TARGET_FILE)
    if not os.path.exists(target_path):
        log_fail("SETUP", f"Target not found: {target_path}")
        report.record("SETUP", "Target file exists", False)
        return report

    with open(target_path, "r", encoding="utf-8") as f:
        original_content = f.read()

    log_ok("SETUP", f"Target: {TARGET_FILE} ({len(original_content.splitlines())} lines)")
    report.record("SETUP", "Target file exists", True)

    # Load API key
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        key_file = os.path.join(os.path.dirname(PROJECT_ROOT), "deepseek.txt")
        if os.path.exists(key_file):
            with open(key_file, "r") as f:
                api_key = f.read().strip()

    if not api_key:
        log_fail("SETUP", "No API key found")
        report.record("SETUP", "API key available", False)
        return report

    log_ok("SETUP", f"API key loaded ({api_key[:8]}...)")
    report.record("SETUP", "API key available", True)

    # Initialize LLM provider
    try:
        from openai import OpenAI

        class DeepSeekLLM:
            """Minimal LLM wrapper matching ARIA's .chat() interface."""
            def __init__(self, api_key):
                self.client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")

            def chat(self, messages, system=None, max_tokens=2000, **kwargs):
                msgs = []
                if system:
                    msgs.append({"role": "system", "content": system})
                msgs.extend(messages)
                response = self.client.chat.completions.create(
                    model="deepseek-chat",
                    messages=msgs,
                    max_tokens=max_tokens,
                    temperature=0.3,
                )
                return type("LLMResponse", (), {
                    "content": response.choices[0].message.content,
                    "usage": response.usage,
                    "raw_response": response,
                })()

        llm = DeepSeekLLM(api_key)
        log_ok("SETUP", "DeepSeek LLM initialized")
        report.record("SETUP", "LLM initialized", True)
    except Exception as e:
        log_fail("SETUP", f"LLM init failed: {e}")
        report.record("SETUP", "LLM initialized", False, str(e))
        return report

    # Initialize ARIA components
    try:
        from core.cognition.reflection import ReflectionEngine, Reflection
        from core.cognition.introspection import Introspector
        from core.cognition.evolution import EvolutionEngine
        from core.cognition.mirror import MirrorManager
        from core.cognition.insight_evaluator import InsightEvaluator
        from core.cognition.cognitive_cycle import CognitiveCycleOrchestrator

        reflection_engine = ReflectionEngine(
            reflections_path=os.path.join(PROJECT_ROOT, "data", "reflections"),
            memory_system=None,  # No memory system for test
        )
        introspector = Introspector(PROJECT_ROOT)
        mirror = MirrorManager(PROJECT_ROOT, config={"run_tests": False})
        evolution = EvolutionEngine(PROJECT_ROOT, mirror=mirror, mirror_config={"require_confirmation": True})

        log_ok("SETUP", "ARIA components initialized")
        report.record("SETUP", "ARIA components initialized", True)
    except Exception as e:
        log_fail("SETUP", f"Component init failed: {e}")
        traceback.print_exc()
        report.record("SETUP", "ARIA components initialized", False, str(e))
        return report

    # Clean any stale pending for our target
    pending_before = evolution.modifier.list_pending_changes()
    stale = [c for c in pending_before if c.get("target_file") == TARGET_FILE]
    if stale:
        log("SETUP", f"Clearing {len(stale)} stale pending for {TARGET_FILE}", Colors.YELLOW)
        for s in stale:
            evolution.modifier.reject_change(s["id"], reason="E2E test cleanup")

    # ──────────────────────────────────────────────────────────────────
    # PHASE 1: Force a reflection with actionable insights
    # ──────────────────────────────────────────────────────────────────
    log("REFLECT", "Forcing a reflection about ReflectionEngine...", Colors.HEADER)

    # Ask LLM to generate a reflection about ReflectionEngine that contains
    # a concrete, actionable insight about improving the code.
    reflect_prompt = f"""You are ARIA, an AI reflecting on your own code.
You just examined your ReflectionEngine module ({TARGET_FILE}).

Here is the current code of analyze_patterns():

```python
def analyze_patterns(self, reflections: List[Dict] = None) -> Dict:
    if reflections is None:
        reflections = self.get_recent_reflections(30)
    if not reflections:
        return {{'message': 'Insufficient reflections for analysis'}}
    tones = {{}}
    triggers = {{}}
    all_insights = []
    for r in reflections:
        tone = r.get('emotional_tone', 'unknown')
        tones[tone] = tones.get(tone, 0) + 1
        trigger = r.get('trigger', 'unknown')
        triggers[trigger] = triggers.get(trigger, 0) + 1
        all_insights.extend(r.get('insights', []))
    return {{
        'total_reflections': len(reflections),
        'emotional_distribution': tones,
        'common_triggers': dict(sorted(triggers.items(), key=lambda x: x[1], reverse=True)[:5]),
        'insight_count': len(all_insights),
        'period': f"last {{len(set(r['timestamp'][:10] for r in reflections))}} days"
    }}
```

Reflect on this code. Your reflection MUST include:
1. At least one concrete insight about a limitation of this method
2. At least one ACTION ITEM that suggests adding a specific method or improving this one
   (use the word "should" in the action item — e.g., "I should add a method that...")

Format your reflection naturally, with insights as bullet points starting with "-"
and action items starting with "- I should" or "- Should"."""

    try:
        t0 = time.time()
        response = llm.chat(
            messages=[{"role": "user", "content": reflect_prompt}],
            system="You are ARIA, reflecting genuinely on your own code. Be specific and actionable.",
            max_tokens=500,
        )
        reflect_time = time.time() - t0

        reflection_text = response.content
        log_ok("REFLECT", f"Generated reflection in {reflect_time:.1f}s")
        log_data("Reflection", reflection_text[:200] + "...")

        # Parse into a Reflection object
        reflection = reflection_engine.parse_reflection_response(
            reflection_text, trigger="code_review"
        )

        log_data("Insights found", len(reflection.insights))
        log_data("Action items found", len(reflection.action_items))
        for i, insight in enumerate(reflection.insights[:3]):
            log_data(f"  Insight {i+1}", insight[:100])
        for i, action in enumerate(reflection.action_items[:3]):
            log_data(f"  Action {i+1}", action[:100])

        has_insights = len(reflection.insights) > 0 or len(reflection.action_items) > 0
        report.record("REFLECT", "Reflection generated with content", True)
        report.record("REFLECT", "Reflection has insights or action items", has_insights,
                       "No insights or action items extracted" if not has_insights else None)

        # Save the reflection so the evaluator can find it
        reflection_engine.save_reflection(reflection)
        log_ok("REFLECT", "Reflection saved to data/reflections/")
        report.record("REFLECT", "Reflection saved", True)

    except Exception as e:
        log_fail("REFLECT", f"Reflection failed: {e}")
        traceback.print_exc()
        report.record("REFLECT", "Reflection generated", False, str(e))
        return report

    # ──────────────────────────────────────────────────────────────────
    # PHASE 2: InsightEvaluator classifies insights
    # ──────────────────────────────────────────────────────────────────
    log("EVALUATE", "InsightEvaluator analyzing insights...", Colors.HEADER)

    try:
        evaluator = InsightEvaluator(
            llm=llm,
            reflection_engine=reflection_engine,
            introspector=introspector,
            data_dir=os.path.join(PROJECT_ROOT, "data"),
        )

        t0 = time.time()
        evaluations = evaluator.evaluate_recent_insights(days=1)
        eval_time = time.time() - t0

        log_ok("EVALUATE", f"Evaluated {len(evaluations)} insights in {eval_time:.1f}s")

        actionable = [e for e in evaluations if e.is_actionable]
        non_actionable = [e for e in evaluations if not e.is_actionable]

        log_data("Actionable", len(actionable))
        log_data("Non-actionable", len(non_actionable))

        for e in actionable:
            log_data("  Target", e.target_file)
            log_data("  Change", e.proposed_change)
            log_data("  Confidence", f"{e.confidence:.2f}")

        for e in non_actionable[:3]:
            log_data("  Skipped", f"{e.insight_text[:60]}... → {e.reason[:60]}")

        has_actionable = len(actionable) > 0
        report.record("EVALUATE", "Insights evaluated by LLM", len(evaluations) > 0)
        report.record("EVALUATE", "At least one actionable insight found", has_actionable,
                       "No actionable insights — LLM was too conservative" if not has_actionable else None)

        from core.cognition.insight_evaluator import ProposalDraft

        if has_actionable:
            all_drafts = evaluator.get_proposal_drafts(
                results=evaluations,
                min_confidence=0.4,
            )
            log_data("Drafts above threshold", len(all_drafts))
            report.record("EVALUATE", "Proposal drafts created", len(all_drafts) > 0)

            # Prefer a draft targeting our TARGET_FILE
            target_drafts = [d for d in all_drafts if d.target_file == TARGET_FILE]
            if target_drafts:
                drafts = [target_drafts[0]]
                log_ok("EVALUATE", f"Found draft targeting {TARGET_FILE}")
            elif all_drafts:
                # LLM pointed actionable insights at a different file.
                # The evaluator worked correctly — the LLM just decided a
                # different file was more relevant. Use a forced draft for
                # our target to test the full pipeline.
                log("EVALUATE", f"Evaluator found actionable insights but for other files, not {TARGET_FILE}", Colors.YELLOW)
                for d in all_drafts[:3]:
                    log_data("  Evaluator suggested", f"{d.target_file} → {d.modification_description[:60]}")
                log("EVALUATE", "Using forced draft for target file to test full pipeline", Colors.YELLOW)
                drafts = [ProposalDraft(
                    title="Improve analyze_patterns with action_item tracking",
                    reason="From reflection: analyze_patterns doesn't track action_items frequency",
                    target_file=TARGET_FILE,
                    modification_description="Add action_item_count to the dict returned by analyze_patterns() — count how many action_items exist across all reflections, and add the top 3 most common action verbs",
                    source_insight_id=reflection.id,
                    confidence=0.8,
                )]
                report.record("EVALUATE", "Forced draft for target (evaluator pointed elsewhere)", True)
            else:
                drafts = []
        else:
            log("EVALUATE", "No actionable insights. Using forced draft.", Colors.YELLOW)
            drafts = [ProposalDraft(
                title="Improve analyze_patterns with action_item tracking",
                reason="From reflection: analyze_patterns doesn't track action_items frequency",
                target_file=TARGET_FILE,
                modification_description="Add action_item_count to the dict returned by analyze_patterns() — count how many action_items exist across all reflections, and add the top 3 most common action verbs",
                source_insight_id=reflection.id,
                confidence=0.8,
            )]
            report.record("EVALUATE", "Forced draft created (evaluator was too conservative)", True)

    except Exception as e:
        log_fail("EVALUATE", f"Evaluation failed: {e}")
        traceback.print_exc()
        report.record("EVALUATE", "Evaluation completed", False, str(e))
        return report

    # ──────────────────────────────────────────────────────────────────
    # PHASE 3: Orchestrator generates code and routes through mirror
    # ──────────────────────────────────────────────────────────────────
    log("ORCHESTRATE", "CognitiveCycleOrchestrator generating code...", Colors.HEADER)

    try:
        orchestrator = CognitiveCycleOrchestrator(
            llm=llm,
            reflection_engine=reflection_engine,
            introspector=introspector,
            evolution_engine=evolution,
            data_dir=os.path.join(PROJECT_ROOT, "data"),
            min_confidence=0.4,
        )

        # Process the first draft manually (to control which draft we test)
        draft = drafts[0]
        log_data("Processing draft", draft.title)
        log_data("Target file", draft.target_file)
        log_data("Modification", draft.modification_description)

        t0 = time.time()
        detail = orchestrator._process_draft(draft)
        process_time = time.time() - t0

        log_data("Status", detail.get("status"))
        log_data("Processing time", f"{process_time:.1f}s")

        if detail.get("status") == "pending_approval":
            pending_ids = detail.get("pending_ids", [])
            log_ok("ORCHESTRATE", f"Code generated and validated → pending_approval (ids: {pending_ids})")
            report.record("ORCHESTRATE", "Code generated by LLM", True)
            report.record("ORCHESTRATE", "Quality gate passed", True)
            report.record("ORCHESTRATE", "Mirror validation passed", True)
            report.record("ORCHESTRATE", "Change reached pending_approval", True)
        elif detail.get("status") == "quality_rejected":
            score = detail.get("quality_score", 0)
            reasons = detail.get("quality_reasons", [])
            log_fail("ORCHESTRATE", f"Quality gate REJECTED — score={score:.2f}")
            for r in reasons:
                log_data("  Reason", r)
            log_data("Full report", detail.get("quality_report", ""))
            report.record("ORCHESTRATE", "Code generated by LLM", True)
            report.record("ORCHESTRATE", "Quality gate passed", False,
                           f"score={score:.2f}: {'; '.join(reasons[:3])}")
            report.record("ORCHESTRATE", "Change reached pending_approval", False,
                           "Rejected by quality gate as noise")
        elif detail.get("status") == "failed":
            log_fail("ORCHESTRATE", f"Mirror validation failed: {detail.get('error')}")
            log_data("Validation errors", detail.get("validation_errors"))
            report.record("ORCHESTRATE", "Code generated by LLM", True)
            report.record("ORCHESTRATE", "Mirror validation passed", False, detail.get("error"))
            report.record("ORCHESTRATE", "Change reached pending_approval", False)
        elif detail.get("status") == "generation_failed":
            log_fail("ORCHESTRATE", f"Code generation failed: {detail.get('error')}")
            report.record("ORCHESTRATE", "Code generated by LLM", False, detail.get("error"))
            report.record("ORCHESTRATE", "Change reached pending_approval", False)
        else:
            log_fail("ORCHESTRATE", f"Unexpected status: {detail}")
            report.record("ORCHESTRATE", "Change reached pending_approval", False, str(detail))

    except Exception as e:
        log_fail("ORCHESTRATE", f"Orchestrator failed: {e}")
        traceback.print_exc()
        report.record("ORCHESTRATE", "Orchestrator completed", False, str(e))
        return report

    # ──────────────────────────────────────────────────────────────────
    # PHASE 4: Verify pending state — live file NOT modified
    # ──────────────────────────────────────────────────────────────────
    log("VERIFY", "Verifying pending state...", Colors.HEADER)

    # Check pending changes
    pending = evolution.modifier.list_pending_changes()
    our_pending = [c for c in pending if c.get("target_file") == TARGET_FILE]

    log_data("Total pending", len(pending))
    log_data("Pending for target", len(our_pending))

    has_pending = len(our_pending) > 0
    if has_pending:
        change = our_pending[0]
        log_ok("VERIFY", f"Pending change found: {change.get('id', '?')[:12]}")
        log_data("Status", change.get("status"))
        log_data("Type", change.get("modification_type"))
        log_data("Reason", change.get("reason", "")[:80])

        if change.get("validation_result"):
            vr = change["validation_result"]
            log_data("Syntax OK", vr.get("syntax_ok"))
            log_data("Import OK", vr.get("import_ok"))
            log_data("Duration", f"{vr.get('duration_seconds', 0):.2f}s")
    else:
        log_fail("VERIFY", "No pending change found for target file")

    report.record("VERIFY", "Pending change exists in mirror", has_pending)

    # Verify live file is UNCHANGED
    with open(target_path, "r", encoding="utf-8") as f:
        live_now = f.read()

    live_unchanged = live_now == original_content
    if live_unchanged:
        log_ok("VERIFY", "Live file UNCHANGED — human approval required to promote")
    else:
        log_fail("VERIFY", "Live file was modified! The cycle should NOT auto-promote!")

    report.record("VERIFY", "Live file unchanged (human must approve)", live_unchanged)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 5: Verify the generated code quality
    # ──────────────────────────────────────────────────────────────────
    log("QUALITY", "Checking generated code quality...", Colors.HEADER)

    if has_pending:
        # Read the mirror file to see what was generated
        mirror_file = os.path.join(mirror.mirror_dir, TARGET_FILE)
        if os.path.exists(mirror_file):
            with open(mirror_file, "r", encoding="utf-8") as f:
                mirror_content = f.read()

            # Check it's valid Python
            try:
                tree = ast.parse(mirror_content)
                log_ok("QUALITY", "Generated code is valid Python")
                report.record("QUALITY", "Generated code is valid Python", True)
            except SyntaxError as e:
                log_fail("QUALITY", f"Syntax error: {e}")
                report.record("QUALITY", "Generated code is valid Python", False, str(e))
                mirror_content = None

            if mirror_content:
                # Check original classes preserved
                classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
                funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]

                has_reflection_engine = "ReflectionEngine" in classes
                has_metacognition = "MetaCognition" in classes
                has_reflection_dc = "Reflection" in classes

                log_data("Classes", ", ".join(classes))
                log_data("Total methods/functions", len(funcs))

                report.record("QUALITY", "ReflectionEngine class preserved",
                               has_reflection_engine)
                report.record("QUALITY", "MetaCognition class preserved",
                               has_metacognition)

                # Check it's actually different (has new code)
                is_different = mirror_content.strip() != original_content.strip()
                log_data("Code differs from original", is_different)
                report.record("QUALITY", "Generated code differs from original", is_different)

                # Size comparison
                orig_lines = len(original_content.splitlines())
                mirror_lines = len(mirror_content.splitlines())
                log_data("Size", f"original={orig_lines} lines, generated={mirror_lines} lines")
        else:
            log_fail("QUALITY", "Mirror file not found")
            report.record("QUALITY", "Mirror file exists", False)

    # ──────────────────────────────────────────────────────────────────
    # PHASE 6: Cleanup — reject the pending change, restore state
    # ──────────────────────────────────────────────────────────────────
    log("CLEANUP", "Rejecting pending change and restoring state...", Colors.HEADER)

    if our_pending:
        for change in our_pending:
            reject = evolution.modifier.reject_change(
                mod_id=change["id"],
                reason="E2E cognitive cycle test cleanup",
                initiated_by="user",
            )
            log_data("Rejected", f"{change['id'][:12]} → {reject.status}")

        # Verify pending is cleared
        remaining = [c for c in evolution.modifier.list_pending_changes()
                     if c.get("target_file") == TARGET_FILE]
        cleared = len(remaining) == 0
        if cleared:
            log_ok("CLEANUP", "Pending changes cleared")
        else:
            log_fail("CLEANUP", f"Still {len(remaining)} pending")
        report.record("CLEANUP", "Pending changes rejected and cleared", cleared)

    # Verify live file still original
    with open(target_path, "r", encoding="utf-8") as f:
        final_content = f.read()

    still_original = final_content == original_content
    if still_original:
        log_ok("CLEANUP", f"{TARGET_FILE} untouched throughout entire test")
    else:
        log_fail("CLEANUP", "File was modified! Restoring...")
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(original_content)
        log("CLEANUP", "Restored from backup", Colors.YELLOW)

    report.record("CLEANUP", "Target file intact after test", still_original)

    # Clear post-promote state if any
    evolution.modifier.clear_post_promote_state()

    return report


# ─── Entry point ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
{Colors.BOLD}{'='*60}
  ARIA Cognitive Cycle — End-to-End Test
  reflection → evaluate → generate → mirror pending
  Target: {TARGET_FILE}
  LLM: DeepSeek
  Rule: NOTHING is auto-approved
{'='*60}{Colors.END}
""")

    report = run_e2e_test()
    all_passed = report.summary()

    # Save report
    report_path = os.path.join(PROJECT_ROOT, "data", "test_cognitive_cycle_e2e_report.yaml")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    try:
        import yaml
        with open(report_path, "w") as f:
            yaml.dump(report.to_dict(), f, default_flow_style=False, allow_unicode=True)
        print(f"\nReport saved to: {report_path}")
    except Exception:
        import json
        report_path = report_path.replace(".yaml", ".json")
        with open(report_path, "w") as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nReport saved to: {report_path}")

    sys.exit(0 if all_passed else 1)
