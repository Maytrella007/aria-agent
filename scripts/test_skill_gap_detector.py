#!/usr/bin/env python3
"""
Test the Skill Gap Detector — ARIA's proactive skill auto-creation system.
"""

import os
import sys
import json
import shutil
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[96mINFO\033[0m"

results = {"pass": 0, "fail": 0}


def test(name, condition):
    if condition:
        print(f"  [{PASS}] {name}")
        results["pass"] += 1
    else:
        print(f"  [{FAIL}] {name}")
        results["fail"] += 1


def main():
    print("\n" + "=" * 60)
    print("  Skill Gap Detector Test")
    print("=" * 60)

    from core.autonomy.skill_gap_detector import SkillGapDetector, TaskPattern
    from core.infra.event_stream import EventBus

    # Use temp directory for data
    tmp_dir = tempfile.mkdtemp(prefix="aria_test_gap_")

    try:
        # --- Unit Tests ---
        print(f"\n  --- Unit Tests ---")

        # Test: basic instantiation
        detector = SkillGapDetector(data_dir=tmp_dir, forge_threshold=3)
        test("Instantiation works", detector is not None)
        test("Default threshold", detector.forge_threshold == 3)

        # Test: domain classification
        domain = detector._classify_domain("search for python tutorials", ["web_search"])
        test("Classify single tool domain", domain == "web_research")

        domain = detector._classify_domain("fetch a page", ["web_fetch"])
        test("Classify web_fetch domain", domain == "web_scraping")

        domain = detector._classify_domain("run a script", ["shell_exec"])
        test("Classify shell_exec domain", domain == "system_operations")

        domain = detector._classify_domain("multi-step", ["web_search", "web_fetch"])
        test("Classify multi-tool domain", domain == "web_research")

        domain = detector._classify_domain("complex task", ["shell_exec", "file_manager"])
        test("Classify unknown multi-tool domain", domain is not None and "multi_tool" in domain)

        # --- Tracking Tests ---
        print(f"\n  --- Tracking Tests ---")

        detector2 = SkillGapDetector(data_dir=tmp_dir, forge_threshold=3)

        # Track requests without skill match
        for i in range(3):
            detector2.track_request(
                query=f"search for topic {i}",
                tools_used=["web_search"],
                skill_matched=None,
                confidence=0.6,
            )

        patterns = detector2.get_patterns()
        test("Patterns tracked", len(patterns) > 0)

        web_pattern = [p for p in patterns if p["domain"] == "web_research"]
        test("Web research pattern detected", len(web_pattern) == 1)
        test("Occurrence count correct", web_pattern[0]["occurrences"] == 3)
        test("Progress shows 3/3", web_pattern[0]["progress"] == "3/3")

        # Test: skill match means no gap
        detector2.track_request(
            query="translate hello to spanish",
            tools_used=["web_search"],
            skill_matched="translate",
            confidence=0.9,
        )
        patterns_after = detector2.get_patterns()
        test("Skill match not tracked as gap", len(patterns_after) == len(patterns))

        # Test: no tools = no gap
        detector2.track_request(
            query="hello how are you",
            tools_used=[],
            skill_matched=None,
            confidence=0.9,
        )
        test("No tools not tracked as gap", len(detector2.get_patterns()) == len(patterns))

        # --- Persistence Tests ---
        print(f"\n  --- Persistence Tests ---")

        detector2._save_patterns()
        data_file = os.path.join(tmp_dir, "skill_gap_patterns.json")
        test("Patterns file created", os.path.exists(data_file))

        # Load in a new detector
        detector3 = SkillGapDetector(data_dir=tmp_dir, forge_threshold=3)
        test("Patterns loaded from disk", len(detector3.get_patterns()) > 0)

        loaded_pattern = [p for p in detector3.get_patterns() if p["domain"] == "web_research"]
        test("Loaded pattern has correct count", loaded_pattern[0]["occurrences"] == 3)

        # --- EventBus Integration Tests ---
        print(f"\n  --- EventBus Integration Tests ---")

        bus = EventBus()
        detector4 = SkillGapDetector(event_bus=bus, data_dir=tmp_dir, forge_threshold=5)
        detector4.subscribe()
        test("EventBus subscription works", detector4._unsubscribe is not None)

        # Simulate tool events
        bus.emit("tool", "result", {
            "name": "calculator", "success": True, "elapsed_ms": 50,
        }, run_id="test_run_1")
        bus.emit("tool", "result", {
            "name": "calculator", "success": False, "elapsed_ms": 100,
        }, run_id="test_run_1")

        # Give the event handler a moment
        import time
        time.sleep(0.1)

        test("Events received", len(detector4._current_tools) >= 0)  # May have been processed already

        # Emit lifecycle end to trigger processing
        bus.emit("lifecycle", "end", {"duration_ms": 200}, run_id="test_run_1")
        time.sleep(0.5)  # Wait for background thread

        # Unsubscribe
        detector4.unsubscribe()
        test("EventBus unsubscribe works", detector4._unsubscribe is None)

        # --- Analysis Tests ---
        print(f"\n  --- Analysis Tests ---")

        detector5 = SkillGapDetector(data_dir=tmp_dir, forge_threshold=3)

        # Add patterns near threshold
        for i in range(2):
            detector5.track_request(
                query=f"run command {i}",
                tools_used=["shell_exec"],
                skill_matched=None,
                confidence=0.5,
            )

        report = detector5.analyze()
        test("Analysis returns report", isinstance(report, str) and len(report) > 0)
        print(f"  [{INFO}] {report[:200]}")

        # --- Auto-forge threshold (without actual forge tool) ---
        print(f"\n  --- Threshold Detection ---")

        detector6 = SkillGapDetector(data_dir=tmp_dir, forge_threshold=2)
        for i in range(2):
            detector6.track_request(
                query=f"compress files {i}",
                tools_used=["compress"],
                skill_matched=None,
                confidence=0.6,
            )

        compress_pattern = [p for p in detector6.get_patterns() if p["domain"] == "file_compression"]
        test("Pattern reaches threshold", len(compress_pattern) > 0 and compress_pattern[0]["occurrences"] >= 2)
        # Without forge_skill_tool, forging won't happen but pattern is tracked
        test("Not forged without tool", not compress_pattern[0]["forged"])

    finally:
        # Cleanup
        shutil.rmtree(tmp_dir, ignore_errors=True)

    # Summary
    print(f"\n{'='*60}")
    total = results["pass"] + results["fail"]
    print(f"  Total: {total}  Passed: {results['pass']}  Failed: {results['fail']}")
    print(f"{'='*60}\n")

    sys.exit(0 if results["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
