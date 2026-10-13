"""
ARIA - Agent Module Tests
==========================

Tests for:
- agent_protocol.py: AgentRole, AgentMessage, AgentResult, ROLE_CONFIGS, WorkerAgent
- agent_pool.py: AgentPool lifecycle, concurrency, cleanup
- orchestrator.py: Orchestrator decompose, delegate, parallel_execute, stats
"""

import json
import time
import pytest
from unittest.mock import Mock
from dataclasses import fields

from core.agents.agent_protocol import (
    AgentRole,
    AgentMessage,
    AgentResult,
    ROLE_CONFIGS,
    WorkerAgent,
)
from core.agents.agent_pool import AgentPool, MAX_CONCURRENT_WORKERS
from core.agents.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tool_registry():
    """Create a minimal mock tool registry."""
    reg = Mock()
    reg.list.return_value = []
    result_mock = Mock()
    result_mock.output = "result"
    result_mock.success = True
    reg.execute.return_value = result_mock
    return reg


def _patch_response(mock_llm, tool_calls=None):
    """
    Ensure MockLLMProvider responses include a tool_calls attribute
    so WorkerAgent._execute_loop doesn't raise AttributeError.
    """
    original_chat = mock_llm.chat

    def patched_chat(*args, **kwargs):
        resp = original_chat(*args, **kwargs)
        if not hasattr(resp, "tool_calls"):
            resp.tool_calls = tool_calls
        return resp

    mock_llm.chat = patched_chat


# ===========================================================================
# AgentRole enum
# ===========================================================================

class TestAgentRole:
    def test_all_roles_exist(self):
        expected = {"RESEARCHER", "CODER", "ANALYST", "REVIEWER", "WRITER", "MONITOR", "GENERAL"}
        actual = {r.name for r in AgentRole}
        assert actual == expected

    def test_role_values_are_lowercase(self):
        for role in AgentRole:
            assert role.value == role.name.lower()

    def test_role_lookup_by_value(self):
        assert AgentRole("researcher") is AgentRole.RESEARCHER
        assert AgentRole("coder") is AgentRole.CODER


# ===========================================================================
# AgentMessage dataclass
# ===========================================================================

class TestAgentMessage:
    def test_construction(self):
        msg = AgentMessage(
            from_agent="w_res_abc123",
            to_agent="orchestrator",
            msg_type="result",
            content="done",
        )
        assert msg.from_agent == "w_res_abc123"
        assert msg.to_agent == "orchestrator"
        assert msg.msg_type == "result"
        assert msg.content == "done"

    def test_default_values(self):
        msg = AgentMessage(from_agent="a", to_agent="b", msg_type="task", content="x")
        assert isinstance(msg.data, dict) and msg.data == {}
        assert isinstance(msg.timestamp, float)
        assert isinstance(msg.msg_id, str) and len(msg.msg_id) == 12

    def test_unique_msg_ids(self):
        ids = {
            AgentMessage(from_agent="a", to_agent="b", msg_type="t", content="c").msg_id
            for _ in range(50)
        }
        assert len(ids) == 50


# ===========================================================================
# AgentResult dataclass
# ===========================================================================

class TestAgentResult:
    def test_success_result(self):
        r = AgentResult(
            agent_id="w_cod_aaa",
            role=AgentRole.CODER,
            task="write code",
            success=True,
            output="print('hi')",
        )
        assert r.success is True
        assert r.output == "print('hi')"
        assert r.error == ""

    def test_failure_result(self):
        r = AgentResult(
            agent_id="w_res_bbb",
            role=AgentRole.RESEARCHER,
            task="search",
            success=False,
            error="Timeout after 120s",
        )
        assert r.success is False
        assert r.error == "Timeout after 120s"
        assert r.output == ""

    def test_default_review_fields(self):
        r = AgentResult(agent_id="x", role=AgentRole.GENERAL, task="t", success=True)
        assert r.reviewed is False
        assert r.review_verdict == ""
        assert r.review_feedback == ""
        assert r.tools_used == []
        assert r.elapsed_seconds == 0.0


# ===========================================================================
# ROLE_CONFIGS
# ===========================================================================

class TestRoleConfigs:
    def test_all_roles_have_config(self):
        for role in AgentRole:
            assert role in ROLE_CONFIGS, f"Missing config for {role}"

    @pytest.mark.parametrize("key", ["system", "tools", "max_tokens", "max_rounds"])
    def test_required_keys_present(self, key):
        for role, config in ROLE_CONFIGS.items():
            assert key in config, f"{role} missing '{key}'"

    def test_reviewer_has_no_tools(self):
        assert ROLE_CONFIGS[AgentRole.REVIEWER]["tools"] == []

    def test_max_rounds_positive(self):
        for role, config in ROLE_CONFIGS.items():
            assert config["max_rounds"] >= 1


# ===========================================================================
# WorkerAgent
# ===========================================================================

class TestWorkerAgent:
    def test_init_defaults(self, mock_llm_provider):
        reg = _make_tool_registry()
        w = WorkerAgent("w_gen_001", AgentRole.GENERAL, mock_llm_provider, reg)
        assert w.agent_id == "w_gen_001"
        assert w.role is AgentRole.GENERAL
        assert w.status == "idle"
        assert w.result is None
        assert w.is_done is False

    def test_run_wait_success(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response("Answer is 42")
        reg = _make_tool_registry()
        w = WorkerAgent("w_gen_002", AgentRole.GENERAL, mock_llm_provider, reg)

        result = w.run("What is 6*7?", wait=True, timeout=5)

        assert result is not None
        assert result.success is True
        assert result.output == "Answer is 42"
        assert w.status == "completed"
        assert w.is_done is True

    def test_run_async_returns_none(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        w = WorkerAgent("w_gen_003", AgentRole.GENERAL, mock_llm_provider, reg)

        ret = w.run("task", wait=False, timeout=5)
        assert ret is None
        # Wait for thread to finish
        w._thread.join(timeout=5)

    def test_on_complete_callback(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response("done")
        reg = _make_tool_registry()
        collected = []
        w = WorkerAgent(
            "w_gen_004", AgentRole.GENERAL, mock_llm_provider, reg,
            on_complete=lambda r: collected.append(r),
        )
        w.run("task", wait=True, timeout=5)
        assert len(collected) == 1
        assert collected[0].success is True

    def test_run_records_elapsed(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        w = WorkerAgent("w_gen_005", AgentRole.GENERAL, mock_llm_provider, reg)
        result = w.run("task", wait=True, timeout=5)
        assert result.elapsed_seconds >= 0


# ===========================================================================
# AgentPool
# ===========================================================================

class TestAgentPool:
    def test_spawn_single(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg, max_concurrent=4)

        worker = pool.spawn(AgentRole.RESEARCHER, "find info", wait=True, timeout=5)
        assert worker.status == "completed"
        assert worker.result.success is True

    def test_spawn_many(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg, max_concurrent=4)

        tasks = [
            {"role": AgentRole.RESEARCHER, "task": "search A"},
            {"role": AgentRole.CODER, "task": "write code B"},
        ]
        workers = pool.spawn_many(tasks, wait_all=True, timeout=10)
        assert len(workers) == 2
        assert all(w.is_done for w in workers)

    def test_concurrency_limit(self, mock_llm_provider):
        """Spawning beyond max_concurrent raises RuntimeError."""
        # Use a provider whose chat blocks so workers stay "running"
        blocking_llm = Mock()

        import threading
        block = threading.Event()

        def blocking_chat(*args, **kwargs):
            block.wait(timeout=10)
            resp = Mock()
            resp.content = "done"
            resp.tool_calls = None
            return resp

        blocking_llm.chat = blocking_chat
        reg = _make_tool_registry()
        pool = AgentPool(blocking_llm, reg, max_concurrent=2)

        pool.spawn(AgentRole.GENERAL, "task1")
        pool.spawn(AgentRole.GENERAL, "task2")

        with pytest.raises(RuntimeError, match="Max concurrent workers"):
            pool.spawn(AgentRole.GENERAL, "task3")

        # Unblock so threads can finish
        block.set()
        pool.shutdown()

    def test_get_status_structure(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg)

        pool.spawn(AgentRole.ANALYST, "analyze", wait=True, timeout=5)
        status = pool.get_status()

        assert "total_workers" in status
        assert "active" in status
        assert "completed" in status
        assert "failed" in status
        assert "max_concurrent" in status
        assert "workers" in status
        assert status["total_workers"] == 1
        assert status["completed"] == 1

    def test_cleanup_removes_done_workers(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg)

        pool.spawn(AgentRole.GENERAL, "t", wait=True, timeout=5)
        assert pool.get_status()["total_workers"] == 1

        pool.cleanup()
        assert pool.get_status()["total_workers"] == 0

    def test_cleanup_keeps_results_by_default(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg)

        w = pool.spawn(AgentRole.GENERAL, "t", wait=True, timeout=5)
        pool.cleanup(keep_results=True)
        assert pool.get_all_results() != {}

    def test_shutdown_clears_everything(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg)

        pool.spawn(AgentRole.GENERAL, "t", wait=True, timeout=5)
        pool.shutdown()
        assert pool.get_status()["total_workers"] == 0
        assert pool.get_all_results() == {}

    def test_wait_returns_result(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response("result text")
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg)

        w = pool.spawn(AgentRole.WRITER, "write something")
        result = pool.wait(w.agent_id, timeout=5)
        assert result is not None
        assert result.success is True

    def test_wait_nonexistent_returns_none(self, mock_llm_provider):
        reg = _make_tool_registry()
        pool = AgentPool(mock_llm_provider, reg)
        assert pool.wait("does_not_exist") is None


# ===========================================================================
# Orchestrator
# ===========================================================================

class TestOrchestrator:
    def test_decompose_task_valid_json(self, mock_llm_provider):
        """_decompose_task parses valid JSON subtasks from LLM."""
        _patch_response(mock_llm_provider, tool_calls=None)
        subtasks_json = json.dumps([
            {"role": "researcher", "task": "find info about X"},
            {"role": "coder", "task": "write a script for Y"},
        ])
        mock_llm_provider.set_response(subtasks_json)
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg, review_enabled=False)

        result = orch._decompose_task("complex task")
        assert len(result) == 2
        assert result[0]["role"] == "researcher"
        assert result[1]["task"] == "write a script for Y"

    def test_decompose_task_malformed_json_returns_empty(self, mock_llm_provider):
        """Malformed JSON from LLM gracefully returns empty list."""
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response("this is not json at all")
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg, review_enabled=False)

        result = orch._decompose_task("task")
        assert result == []

    def test_decompose_task_single_subtask_returns_empty(self, mock_llm_provider):
        """A single subtask is not enough for parallel execution."""
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response(json.dumps([{"role": "coder", "task": "only one"}]))
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg, review_enabled=False)

        result = orch._decompose_task("task")
        assert result == []

    def test_delegate_single(self, mock_llm_provider):
        """delegate() spawns one worker and returns its result."""
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response("delegation output")
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg, review_enabled=False)

        result = orch.delegate(AgentRole.CODER, "write hello world", wait=True, timeout=5)
        assert result is not None
        assert result.success is True
        assert result.output == "delegation output"
        assert result.role is AgentRole.CODER

    def test_get_stats_structure(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg)

        stats = orch.get_stats()
        assert "total_orchestrations" in stats
        assert "total_workers_spawned" in stats
        assert "review_enabled" in stats
        assert "pool" in stats
        assert stats["total_orchestrations"] == 0
        assert stats["total_workers_spawned"] == 0

    def test_stats_increment_after_delegate(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        mock_llm_provider.set_response("ok")
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg, review_enabled=False)

        orch.delegate(AgentRole.GENERAL, "task", wait=True, timeout=5)
        stats = orch.get_stats()
        assert stats["total_orchestrations"] == 1
        assert stats["total_workers_spawned"] == 1

    def test_parallel_execute_fallback_on_bad_decomposition(self, mock_llm_provider):
        """When decomposition fails, parallel_execute falls back to single agent."""
        _patch_response(mock_llm_provider, tool_calls=None)
        # First call: decomposition returns bad JSON; second call: fallback agent response
        mock_llm_provider.set_responses(["not json", "fallback answer"])
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg, review_enabled=False)

        result = orch.parallel_execute("complex task", timeout=10)
        assert "fallback answer" in result

    def test_shutdown(self, mock_llm_provider):
        _patch_response(mock_llm_provider, tool_calls=None)
        reg = _make_tool_registry()
        orch = Orchestrator(mock_llm_provider, reg)
        orch.shutdown()
        assert orch.pool.get_status()["total_workers"] == 0
