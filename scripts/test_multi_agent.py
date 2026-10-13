#!/usr/bin/env python3
"""
Test the Multi-Agent System — Orchestrator, AgentPool, WorkerAgents.
"""

import os
import sys
import time
import threading
from unittest.mock import MagicMock, patch

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


def make_mock_llm(response_text="Mock response", tool_calls=None):
    """Create a mock LLM that returns predictable responses."""
    llm = MagicMock()
    llm.name = "mock"

    response = MagicMock()
    response.content = response_text
    response.provider = "openai"
    response.tool_calls = tool_calls or []
    response.raw_response = None

    llm.chat.return_value = response
    llm.simple_chat.return_value = response_text
    return llm


def make_mock_registry():
    """Create a mock tool registry with basic tools."""
    from core.tools.registry import ToolRegistry
    from core.tools.tool_base import ToolBase, ToolParam, ToolResult

    registry = ToolRegistry()

    # Create a simple mock tool
    class MockCalcTool(ToolBase):
        name = "calculator"
        description = "Calculate math"
        parameters = [
            ToolParam(name="expression", type="string", description="Math expression", required=True),
        ]

        def _execute(self, **kwargs):
            return ToolResult(success=True, output=f"Result: {kwargs.get('expression', '?')}")

    class MockSearchTool(ToolBase):
        name = "web_search"
        description = "Search the web"
        parameters = [
            ToolParam(name="query", type="string", description="Search query", required=True),
        ]

        def _execute(self, **kwargs):
            return ToolResult(success=True, output=f"Found results for: {kwargs.get('query', '?')}")

    registry.register(MockCalcTool(context={}))
    registry.register(MockSearchTool(context={}))
    return registry


def main():
    print("\n" + "=" * 60)
    print("  Multi-Agent System Test")
    print("=" * 60)

    from core.agents.agent_protocol import WorkerAgent, AgentRole, AgentResult, AgentMessage
    from core.agents.agent_pool import AgentPool
    from core.agents.orchestrator import Orchestrator
    from core.tools.orchestrator_tool import OrchestratorTool
    from core.infra.event_stream import EventBus

    # --- Protocol Tests ---
    print(f"\n  --- Agent Protocol ---")

    test("AgentRole enum has expected roles", len(AgentRole) >= 6)
    test("AgentRole.RESEARCHER exists", AgentRole.RESEARCHER.value == "researcher")
    test("AgentRole.REVIEWER exists", AgentRole.REVIEWER.value == "reviewer")

    msg = AgentMessage(
        from_agent="w_res_abc",
        to_agent="orchestrator",
        msg_type="result",
        content="Found 5 results",
    )
    test("AgentMessage creation", msg.msg_id is not None and len(msg.msg_id) == 12)

    result = AgentResult(
        agent_id="w_cod_abc",
        role=AgentRole.CODER,
        task="Write a function",
        success=True,
        output="def hello(): pass",
    )
    test("AgentResult creation", result.success and result.output == "def hello(): pass")

    # --- WorkerAgent Tests ---
    print(f"\n  --- Worker Agent ---")

    llm = make_mock_llm("Hello from worker agent!")
    registry = make_mock_registry()

    worker = WorkerAgent(
        agent_id="test_w_001",
        role=AgentRole.GENERAL,
        llm=llm,
        tool_registry=registry,
    )
    test("Worker creation", worker.agent_id == "test_w_001")
    test("Worker initial status", worker.status == "idle")

    # Run synchronously
    agent_result = worker.run("Say hello", wait=True, timeout=10)
    test("Worker completes", worker.is_done)
    test("Worker result exists", agent_result is not None)
    test("Worker result success", agent_result.success)
    test("Worker result has output", "Hello from worker" in agent_result.output)
    print(f"  [{INFO}] Worker output: {agent_result.output[:80]}")

    # --- WorkerAgent with no tools (reviewer) ---
    print(f"\n  --- Reviewer Agent ---")

    review_llm = make_mock_llm("VERDICT: APPROVE\nFEEDBACK: Response is accurate and complete.")
    reviewer = WorkerAgent(
        agent_id="test_rev_001",
        role=AgentRole.REVIEWER,
        llm=review_llm,
        tool_registry=registry,
    )
    rev_result = reviewer.run("Review this response", wait=True, timeout=10)
    test("Reviewer completes", reviewer.is_done)
    test("Reviewer has verdict", "APPROVE" in rev_result.output)

    # --- Agent Pool Tests ---
    print(f"\n  --- Agent Pool ---")

    pool_llm = make_mock_llm("Pool worker result")
    pool = AgentPool(
        llm=pool_llm,
        tool_registry=registry,
        max_concurrent=4,
    )

    test("Pool creation", pool.active_count == 0)

    # Spawn single worker
    w1 = pool.spawn(AgentRole.RESEARCHER, "Find info about AI", wait=True, timeout=10)
    test("Pool spawn works", w1.is_done)
    test("Pool result stored", pool.get_result(w1.agent_id) is not None)

    # Spawn multiple workers
    w_list = pool.spawn_many([
        {"role": AgentRole.RESEARCHER, "task": "Research topic A"},
        {"role": AgentRole.CODER, "task": "Write code for B"},
        {"role": AgentRole.ANALYST, "task": "Analyze data C"},
    ], wait_all=True, timeout=15)
    test("Pool spawn_many works", len(w_list) == 3)
    test("All workers completed", all(w.is_done for w in w_list))

    all_results = pool.get_all_results()
    test("All results stored", len(all_results) >= 3)

    status = pool.get_status()
    test("Pool status works", status["completed"] >= 3)
    print(f"  [{INFO}] Pool: {status['completed']} completed, {status['failed']} failed")

    # Concurrency limit — use a slow LLM so the first worker is still running
    def slow_chat(**kwargs):
        time.sleep(2)
        resp = MagicMock()
        resp.content = "slow result"
        resp.provider = "openai"
        resp.tool_calls = []
        resp.raw_response = None
        return resp

    slow_llm = MagicMock()
    slow_llm.name = "mock_slow"
    slow_llm.chat = MagicMock(side_effect=slow_chat)

    small_pool = AgentPool(llm=slow_llm, tool_registry=registry, max_concurrent=1)
    small_pool.spawn(AgentRole.GENERAL, "Task 1")  # Starts, won't finish for 2s
    time.sleep(0.1)  # Let thread start
    try:
        small_pool.spawn(AgentRole.GENERAL, "Task 2")
        concurrency_ok = False  # Should have raised
    except RuntimeError:
        concurrency_ok = True
    test("Pool enforces concurrency limit", concurrency_ok)
    small_pool.shutdown()

    pool.cleanup()
    test("Pool cleanup works", pool.active_count == 0)

    # --- EventBus Integration ---
    print(f"\n  --- EventBus Integration ---")

    bus = EventBus()
    events_received = []

    def on_event(ev):
        if ev.stream == "agent":
            events_received.append(ev)

    bus.subscribe(on_event)

    eb_llm = make_mock_llm("EventBus agent result")
    eb_worker = WorkerAgent(
        agent_id="test_eb_001",
        role=AgentRole.GENERAL,
        llm=eb_llm,
        tool_registry=registry,
        event_bus=bus,
    )
    eb_worker.run("Test with events", wait=True, timeout=10)
    time.sleep(0.1)

    test("Agent emits events", len(events_received) >= 2)  # start + done
    start_events = [e for e in events_received if e.event == "start"]
    done_events = [e for e in events_received if e.event == "done"]
    test("Has start event", len(start_events) >= 1)
    test("Has done event", len(done_events) >= 1)
    if done_events:
        test("Done event has success", done_events[0].data.get("success") == True)

    # --- Orchestrator Tests ---
    print(f"\n  --- Orchestrator ---")

    # Mock LLM that returns decomposition for parallel, then worker responses
    call_count = [0]

    def mock_chat(**kwargs):
        call_count[0] += 1
        messages = kwargs.get("messages", [])
        content = messages[-1].get("content", "") if messages else ""

        response = MagicMock()
        response.provider = "openai"
        response.tool_calls = []
        response.raw_response = None

        if "Break the following" in content or "task planner" in str(kwargs.get("system", "")):
            # Decomposition response
            response.content = '[{"role": "researcher", "task": "Research part A"}, {"role": "analyst", "task": "Analyze part B"}]'
        elif "synthesizing" in str(kwargs.get("system", "")).lower():
            response.content = "Synthesized result: Part A findings + Part B analysis combined."
        elif "Review" in content or "review agent" in str(kwargs.get("system", "")).lower():
            response.content = "VERDICT: APPROVE\nFEEDBACK: Good quality response."
        elif "Revise" in content:
            response.content = "Revised response with improvements."
        else:
            response.content = f"Agent response for: {content[:50]}"

        return response

    orch_llm = MagicMock()
    orch_llm.name = "mock"
    orch_llm.chat = MagicMock(side_effect=mock_chat)

    orchestrator = Orchestrator(
        llm=orch_llm,
        tool_registry=registry,
        review_enabled=True,
        max_review_rounds=1,
    )

    test("Orchestrator creation", orchestrator is not None)

    # Test parallel execution
    parallel_result = orchestrator.parallel_execute(
        task="Research AI trends and analyze their market impact",
        timeout=30,
    )
    test("Parallel execution returns result", len(parallel_result) > 0)
    test("Parallel result not empty", parallel_result != "[All workers failed to produce results]")
    print(f"  [{INFO}] Parallel result: {parallel_result[:100]}")

    # Test delegation
    delegate_result = orchestrator.delegate(
        role=AgentRole.RESEARCHER,
        task="Find the latest news about Python 4",
        wait=True,
        timeout=15,
    )
    test("Delegation returns result", delegate_result is not None)
    test("Delegation success", delegate_result.success)

    # Test review
    review_result = orchestrator.review(
        task="Summarize quantum computing",
        response="Quantum computing uses qubits that can be 0 and 1 simultaneously.",
    )
    test("Review returns result", review_result is not None)
    test("Review has verdict", review_result.review_verdict in ("APPROVE", "REVISE", ""))

    # Stats
    stats = orchestrator.get_stats()
    test("Stats track orchestrations", stats["total_orchestrations"] >= 2)
    test("Stats track workers", stats["total_workers_spawned"] >= 3)
    print(f"  [{INFO}] Stats: {stats['total_orchestrations']} orchestrations, {stats['total_workers_spawned']} workers")

    # --- OrchestratorTool Tests ---
    print(f"\n  --- Orchestrator Tool ---")

    orch_tool = OrchestratorTool(context={"orchestrator": orchestrator})
    test("Tool creation", orch_tool.name == "orchestrate")

    # Status action
    status_result = orch_tool.execute(action="status")
    test("Status action works", status_result.success)
    print(f"  [{INFO}] {status_result.output[:150]}")

    # Delegate action
    delegate_tool_result = orch_tool.execute(
        action="delegate",
        task="Calculate compound interest",
        role="analyst",
    )
    test("Delegate via tool works", delegate_tool_result.success)

    # Missing orchestrator
    bad_tool = OrchestratorTool(context={})
    bad_result = bad_tool.execute(action="status")
    test("Missing orchestrator handled", not bad_result.success)

    # Cleanup
    orchestrator.shutdown()

    # Summary
    print(f"\n{'='*60}")
    total = results["pass"] + results["fail"]
    print(f"  Total: {total}  Passed: {results['pass']}  Failed: {results['fail']}")
    print(f"{'='*60}\n")

    sys.exit(0 if results["fail"] == 0 else 1)


if __name__ == "__main__":
    main()
