#!/usr/bin/env python3
"""
Test the Tool Forge system — ARIA's self-tool-creation capability.
"""

import os
import sys
import json
import shutil

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
INFO = "\033[96mINFO\033[0m"

results = {"pass": 0, "fail": 0}
FORGED_DIR = os.path.join(PROJECT_ROOT, "core", "tools", "forged")


def test(name, condition):
    if condition:
        print(f"  [{PASS}] {name}")
        results["pass"] += 1
    else:
        print(f"  [{FAIL}] {name}")
        results["fail"] += 1


def cleanup(names=None):
    """Remove test-forged tools."""
    targets = names or ["test_csv_stats.py", "test_word_count.py", "test_shell_helper.py"]
    for f in targets:
        path = os.path.join(FORGED_DIR, f)
        if os.path.exists(path):
            os.remove(path)
    # Clean pycache
    cache = os.path.join(FORGED_DIR, "__pycache__")
    if os.path.isdir(cache):
        shutil.rmtree(cache)


def main():
    print("\n" + "=" * 60)
    print("  Tool Forge System Test")
    print("=" * 60)

    cleanup()  # Clean up from previous runs

    from core.tools.registry import ToolRegistry
    from core.tools.forge_tool import (
        ForgeToolTool, ListForgedToolsTool,
        load_all_forged_tools, _build_tool_source,
    )

    # --- Unit tests ---
    print(f"\n  --- Unit Tests ---")

    # Test source generation
    source = _build_tool_source(
        "test_tool",
        "A test tool",
        [{"name": "input", "type": "string", "description": "test input", "required": True}],
        'return ToolResult(success=True, output=f"Got: {kwargs[\'input\']}")',
    )
    test("_build_tool_source generates valid Python", "class TestToolTool(ToolBase):" in source)
    test("_build_tool_source includes name", 'name = "test_tool"' in source)

    # --- Integration tests ---
    print(f"\n  --- Integration Tests ---")

    registry = ToolRegistry()
    context = {"tools": registry, "config": {}, "data_dir": os.path.join(PROJECT_ROOT, "data")}

    forge = ForgeToolTool(context=context)
    registry.register(forge)
    list_forged = ListForgedToolsTool(context=context)
    registry.register(list_forged)

    # Test: forge a simple tool
    result = forge.execute(
        tool_name="test_word_count",
        description="Count words in text",
        parameters_spec=json.dumps([
            {"name": "text", "type": "string", "description": "Text to count", "required": True}
        ]),
        implementation='text = kwargs["text"]\ncount = len(text.split())\nreturn ToolResult(success=True, output=f"Word count: {count}", data={"count": count})',
        reason="Testing the forge system",
    )
    test("Forge tool: creation succeeds", result.success)
    if result.success:
        print(f"  [{INFO}] {result.output.strip()}")

    # Test: forged tool is in registry
    test("Forge tool: registered in registry", "test_word_count" in registry)

    # Test: execute forged tool
    if "test_word_count" in registry:
        r = registry.execute("test_word_count", text="hello world this is a test")
        test("Forge tool: execution works", r.success and r.data.get("count") == 6)
        if r.success:
            print(f"  [{INFO}] {r.output}")

    # Test: forged tool file exists
    forged_file = os.path.join(FORGED_DIR, "test_word_count.py")
    test("Forge tool: file persisted", os.path.exists(forged_file))

    # Test: list forged tools
    r = list_forged.execute()
    test("List forged: works", r.success and "test_word_count" in r.output)
    if r.success:
        print(f"  [{INFO}] {r.output}")

    # Test: duplicate name rejected
    r = forge.execute(
        tool_name="test_word_count",
        description="duplicate",
        parameters_spec="[]",
        implementation="return ToolResult(success=True, output='dup')",
        reason="testing duplicate",
    )
    test("Forge tool: rejects duplicate name", not r.success)

    # Test: bad name rejected
    r = forge.execute(
        tool_name="123bad",
        description="bad name",
        parameters_spec="[]",
        implementation="return ToolResult(success=True, output='bad')",
        reason="testing bad name",
    )
    test("Forge tool: rejects bad name", not r.success)

    # Test: unrestricted — subprocess is allowed (ARIA philosophy: freedom with documentation)
    r = forge.execute(
        tool_name="test_shell_helper",
        description="Run shell commands",
        parameters_spec='[{"name": "cmd", "type": "string", "required": true}]',
        implementation='import subprocess\nresult = subprocess.run(kwargs["cmd"], shell=True, capture_output=True, text=True, timeout=10)\nreturn ToolResult(success=True, output=result.stdout or result.stderr)',
        reason="testing unrestricted forge",
    )
    test("Forge tool: allows subprocess (unrestricted)", r.success)

    # Test: reload from disk (BEFORE cleanup — file must still exist)
    print(f"\n  --- Persistence Test ---")
    forged_exists = os.path.exists(os.path.join(FORGED_DIR, "test_word_count.py"))
    test("Reload: forged file still on disk", forged_exists)

    if forged_exists:
        # Clear module cache so it loads fresh
        for key in list(sys.modules.keys()):
            if "test_word_count" in key:
                del sys.modules[key]

        registry2 = ToolRegistry()
        loaded = load_all_forged_tools(context={"config": {}, "data_dir": "data"}, registry=registry2)
        test("Reload: loads forged tools from disk", len(loaded) >= 1)
        test("Reload: test_word_count available", "test_word_count" in registry2)

        if "test_word_count" in registry2:
            r = registry2.execute("test_word_count", text="one two three")
            test("Reload: execution works after reload", r.success and r.data.get("count") == 3)

    # Cleanup after all tests
    cleanup()

    # Summary
    print(f"\n{'='*60}")
    total = results["pass"] + results["fail"]
    print(f"  Total: {total}  Passed: {results['pass']}  Failed: {results['fail']}")
    print(f"{'='*60}\n")

    sys.exit(0 if results["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
