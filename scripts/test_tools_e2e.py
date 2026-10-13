#!/usr/bin/env python3
"""
ARIA - End-to-End Tool Testing with Real LLM
==============================================

Tests the full flow: User prompt → LLM → tool_call → execute → result → LLM → final answer.
Requires a real API key (DeepSeek, OpenAI, etc.)

Usage:
    export DEEPSEEK_API_KEY='your-key'
    python scripts/test_tools_e2e.py

    # Or specify provider:
    python scripts/test_tools_e2e.py --provider openai
    python scripts/test_tools_e2e.py --provider deepseek
"""

import os
import sys
import json
import time
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.llm_providers import LLMProvider, ToolCall
from core.tools import (
    ToolRegistry, WebSearchTool, WebFetchTool, CalculatorTool, SystemInfoTool,
    TodoTool, ProjectKnowledgeTool, DatabaseTool, CompressTool,
    FileManagerTool, PdfTool, ShellExecTool, HttpRequestTool, TranslateTool,
)
from core.interaction.world_access import WorldInterface

# =============================================================================
# Setup
# =============================================================================

def create_registry(tmpdir: str) -> ToolRegistry:
    """Create a tool registry with safe tools for testing."""
    world = WorldInterface()
    ctx = {"world": world, "config": {}, "data_dir": tmpdir}

    registry = ToolRegistry()
    registry.register(WebSearchTool(context=ctx))
    registry.register(WebFetchTool(context=ctx))
    registry.register(CalculatorTool(context=ctx))
    registry.register(SystemInfoTool(context=ctx))
    registry.register(TodoTool(context=ctx))
    registry.register(ProjectKnowledgeTool(context=ctx))
    registry.register(DatabaseTool(context=ctx))
    registry.register(FileManagerTool(context=ctx))
    registry.register(ShellExecTool(context=ctx))
    registry.register(HttpRequestTool(context=ctx))
    registry.register(CompressTool(context=ctx))
    # TranslateTool needs LLM in context — registered without it for now
    # (LLM will be injected in main() after provider is created)
    registry.register(TranslateTool(context=ctx))
    return registry


# =============================================================================
# Test cases
# =============================================================================

TESTS = [
    {
        "name": "Calculator — basic math",
        "prompt": "What is 847 * 23 + 156? Use the calculator tool to compute this.",
        "expect_tool": "calculator",
        "validate": lambda result: "19637" in result or "19,637" in result,
    },
    {
        "name": "Calculator — trig",
        "prompt": "Calculate sin(pi/4) using the calculator tool. Give me the numeric result.",
        "expect_tool": "calculator",
        "validate": lambda result: "0.707" in result,
    },
    {
        "name": "System info",
        "prompt": "Show me the system overview using the system_info tool.",
        "expect_tool": "system_info",
        "validate": lambda result: any(w in result.lower() for w in ["hostname", "cpu", "memory", "os", "linux", "windows"]),
    },
    {
        "name": "Todo — add and list",
        "prompt": "Add a todo item 'Buy groceries' using the todo tool, then list all todos.",
        "expect_tool": "todo",
        "validate": lambda result: "groceries" in result.lower() or "buy" in result.lower(),
    },
    {
        "name": "Project knowledge — save",
        "prompt": "Save a decision using project_knowledge: 'We chose PostgreSQL for the database because of its JSON support'",
        "expect_tool": "project_knowledge",
        "validate": lambda result: "postgresql" in result.lower() or "saved" in result.lower() or "decision" in result.lower(),
    },
    {
        "name": "Web search",
        "prompt": "Search the web for 'Python 3.13 new features' using the web_search tool. Include the URLs you found.",
        "expect_tool": "web_search",
        "validate": lambda result: "python" in result.lower() and ("http" in result or "www" in result or "result" in result.lower()),
    },
    {
        "name": "Multi-tool chain",
        "prompt": "First calculate 2**16 with the calculator, then save the result as a decision in project_knowledge saying 'Max batch size is 65536'.",
        "expect_tool": None,  # Multiple tools
        "validate": lambda result: "65536" in result or "batch" in result.lower(),
    },
    {
        "name": "File manager — write and read",
        "prompt": "Use the file_manager tool to write 'Hello ARIA' to a file called test_e2e.txt in the data directory, then read it back.",
        "expect_tool": "file_manager",
        "validate": lambda result: "hello" in result.lower() or "aria" in result.lower(),
    },
    {
        "name": "Database — create and query",
        "prompt": "Using the database tool with SQLite: create a table called 'products' with columns id (INTEGER) and name (TEXT), insert a row (1, 'Widget'), then query all rows and show me the results.",
        "expect_tool": "database",
        "validate": lambda result: "widget" in result.lower() or "product" in result.lower(),
    },
    {
        "name": "No tool needed",
        "prompt": "What is the capital of France? Answer directly without using any tools.",
        "expect_tool": "__none__",
        "validate": lambda result: "paris" in result.lower(),
    },
    {
        "name": "Search + Fetch chain",
        "prompt": "Use web_search to search for 'python requests library'. Then use web_fetch to read the first URL from the results. Give me a brief summary of what the page says.",
        "expect_tool": None,  # Multiple tools expected
        "validate": lambda result: any(w in result.lower() for w in ["request", "http", "python", "library", "url"]),
    },
    {
        "name": "Shell exec — simple command",
        "prompt": "Use the shell_exec tool to run 'echo Hello from ARIA' and show me the output.",
        "expect_tool": "shell_exec",
        "validate": lambda result: "hello" in result.lower() and "aria" in result.lower(),
    },
    {
        "name": "Shell exec — list files",
        "prompt": "Use the shell_exec tool to run 'ls -la /tmp' and tell me how many files are there.",
        "expect_tool": "shell_exec",
        "validate": lambda result: any(w in result.lower() for w in ["total", "file", "drw", "tmp"]),
    },
    {
        "name": "Compress — zip and list",
        "prompt": "First use file_manager to write 'test data 123' to a file called compress_test.txt in the data directory. Then use the compress tool to create a zip archive called test.zip containing that file. Finally, use compress to list the contents of the zip.",
        "expect_tool": None,  # Multiple tools
        "validate": lambda result: "compress_test" in result.lower() or "test.zip" in result.lower() or "test data" in result.lower(),
    },
    {
        "name": "HTTP request — GET",
        "prompt": "Use the http_request tool to make a GET request to https://httpbin.org/get and show me the response.",
        "expect_tool": "http_request",
        "validate": lambda result: "httpbin" in result.lower() or "origin" in result.lower() or "headers" in result.lower(),
    },
    {
        "name": "Translate — Spanish to English",
        "prompt": "Use the translate tool to translate 'Buenos días, ¿cómo estás?' to English.",
        "expect_tool": "translate",
        "validate": lambda result: any(w in result.lower() for w in ["good morning", "how are you", "hello"]),
    },
    {
        "name": "Calculator — chained with todo",
        "prompt": "Calculate 365 * 24 with the calculator tool. Then add a todo item with the result saying 'There are X hours in a year' where X is the calculated number.",
        "expect_tool": None,  # Multiple tools
        "validate": lambda result: "8760" in result,
    },
]


# =============================================================================
# Runner
# =============================================================================

def run_test(llm, registry, test: dict, verbose: bool = False) -> dict:
    """Run a single e2e test. Returns result dict."""
    name = test["name"]
    prompt = test["prompt"]
    expect_tool = test["expect_tool"]

    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    print(f"Prompt: {prompt[:80]}...")

    messages = [{"role": "user", "content": prompt}]
    tool_schemas = registry.get_function_schemas()

    system = (
        "You are ARIA, an AI assistant with tools. "
        "Use the available tools when the user asks you to. "
        "Always use the specific tool the user mentions. "
        "After getting a tool result, summarize it immediately. "
        "Be efficient: minimize tool rounds, do not re-verify successful operations. "
        "One tool call per step is enough unless the task explicitly requires chaining."
    )

    tools_used = []
    rounds = 0
    start = time.time()
    final_text = ""

    try:
        # Initial LLM call
        response = llm.chat(
            messages=messages,
            system=system,
            max_tokens=1024,
            tools=tool_schemas,
        )

        # Agent loop
        MAX_ROUNDS = 5
        while response.tool_calls and rounds < MAX_ROUNDS:
            rounds += 1

            # Execute tools and collect results
            tool_results = []
            for tc in response.tool_calls:
                tools_used.append(tc.name)
                print(f"  → Tool call: {tc.name}({json.dumps(tc.args)[:80]})")

                result = registry.execute(tc.name, **tc.args)
                tool_results.append((tc, result))
                status = "✓" if result.success else "✗"
                print(f"    {status} {str(result.output)[:80] if result.output else result.error[:80]}")

            # Build tool result messages (OpenAI format for DeepSeek)
            assistant_msg = {"role": "assistant", "content": response.content or None}
            if response.raw_response and hasattr(response.raw_response, 'choices'):
                raw_msg = response.raw_response.choices[0].message
                if hasattr(raw_msg, 'tool_calls') and raw_msg.tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": rtc.id,
                            "type": "function",
                            "function": {
                                "name": rtc.function.name,
                                "arguments": rtc.function.arguments,
                            },
                        }
                        for rtc in raw_msg.tool_calls
                    ]
            messages.append(assistant_msg)

            for tc, r in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": str(r)[:5000],
                })

            response = llm.chat(
                messages=messages,
                system=system,
                max_tokens=1024,
                tools=tool_schemas,
            )

        final_text = response.content or ""
        elapsed = time.time() - start

        print(f"\n  Final response ({elapsed:.1f}s, {rounds} tool rounds):")
        print(f"  {final_text[:200]}")

        # Validate
        tool_ok = True
        if expect_tool == "__none__":
            tool_ok = len(tools_used) == 0
        elif expect_tool is not None:
            tool_ok = expect_tool in tools_used

        content_ok = test["validate"](final_text)

        passed = tool_ok and content_ok
        status = "PASS" if passed else "FAIL"

        if not tool_ok:
            print(f"  ⚠ Expected tool '{expect_tool}', got: {tools_used or 'none'}")
        if not content_ok:
            print(f"  ⚠ Content validation failed")

        print(f"\n  Result: {status}")

        return {
            "name": name,
            "passed": passed,
            "tools_used": tools_used,
            "rounds": rounds,
            "elapsed": round(elapsed, 2),
            "tool_ok": tool_ok,
            "content_ok": content_ok,
            "response_preview": final_text[:200],
        }

    except Exception as e:
        elapsed = time.time() - start
        print(f"  ERROR: {e}")
        return {
            "name": name,
            "passed": False,
            "tools_used": tools_used,
            "rounds": rounds,
            "elapsed": round(elapsed, 2),
            "error": str(e),
        }


def main():
    parser = argparse.ArgumentParser(description="ARIA E2E Tool Testing")
    parser.add_argument("--provider", default=None, help="LLM provider (deepseek, openai, etc.)")
    parser.add_argument("--model", default=None, help="Model name override")
    parser.add_argument("--tests", default=None, help="Comma-separated test indices (0-based) or 'all'")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Create temp dir for test data
    import tempfile
    tmpdir = tempfile.mkdtemp(prefix="aria_e2e_")
    print(f"Test data dir: {tmpdir}")

    # Create LLM provider
    try:
        if args.provider:
            llm = LLMProvider.create(args.provider, model=args.model)
        else:
            llm = LLMProvider.from_env()
        print(f"LLM Provider: {llm.__class__.__name__}")
    except Exception as e:
        print(f"ERROR: Could not create LLM provider: {e}")
        print("Set an API key: export DEEPSEEK_API_KEY='...' or export OPENAI_API_KEY='...'")
        sys.exit(1)

    # Create tool registry
    registry = create_registry(tmpdir)
    print(f"Tools registered: {len(registry)} ({', '.join(registry.names())})")

    # Select tests
    if args.tests and args.tests != "all":
        indices = [int(i) for i in args.tests.split(",")]
        selected = [TESTS[i] for i in indices]
    else:
        selected = TESTS

    print(f"\nRunning {len(selected)} tests...")

    # Run tests
    results = []
    for test in selected:
        result = run_test(llm, registry, test, verbose=args.verbose)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    total_time = sum(r["elapsed"] for r in results)

    for r in results:
        icon = "✓" if r["passed"] else "✗"
        tools = ", ".join(r["tools_used"]) if r["tools_used"] else "none"
        print(f"  {icon} {r['name']} ({r['elapsed']}s) — tools: {tools}")

    print(f"\n  {passed}/{total} passed in {total_time:.1f}s")

    # Cleanup
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
