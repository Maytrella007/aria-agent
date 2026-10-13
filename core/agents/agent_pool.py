"""
ARIA - Agent Pool
==================

Manages worker agent lifecycle: creation, execution, concurrency limits,
and cleanup. The pool is the factory for WorkerAgents.

Thread-safe — multiple orchestrator calls can run concurrently.
"""

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

from .agent_protocol import AgentRole, AgentResult, WorkerAgent

logger = logging.getLogger("aria.agents.pool")

# Limits
MAX_CONCURRENT_WORKERS = 8
DEFAULT_TIMEOUT = 120  # seconds


class AgentPool:
    """
    Factory and lifecycle manager for worker agents.

    Usage:
        pool = AgentPool(llm=llm, tool_registry=tools, event_bus=bus)
        agent = pool.spawn(AgentRole.RESEARCHER, "Find info about X")
        # ... agent runs in background ...
        result = pool.wait(agent.agent_id)
        pool.cleanup()
    """

    def __init__(
        self,
        llm,
        tool_registry,
        event_bus=None,
        max_concurrent: int = MAX_CONCURRENT_WORKERS,
    ):
        self.llm = llm
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self.max_concurrent = max_concurrent

        self._workers: Dict[str, WorkerAgent] = {}
        self._results: Dict[str, AgentResult] = {}
        self._lock = threading.Lock()
        self._completion_event = threading.Event()

    @property
    def active_count(self) -> int:
        """Number of currently running workers."""
        with self._lock:
            return sum(1 for w in self._workers.values() if not w.is_done)

    def spawn(
        self,
        role: AgentRole,
        task: str,
        extra_context: str = "",
        wait: bool = False,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> WorkerAgent:
        """
        Create and start a worker agent.

        Args:
            role: Agent specialization
            task: What the agent should do
            extra_context: Additional info (e.g., other agents' output)
            wait: Block until agent completes
            timeout: Max seconds (if wait=True)

        Returns:
            WorkerAgent instance

        Raises:
            RuntimeError: If max concurrent workers exceeded
        """
        if self.active_count >= self.max_concurrent:
            raise RuntimeError(
                f"Max concurrent workers reached ({self.max_concurrent}). "
                f"Wait for some to complete or increase the limit."
            )

        agent_id = f"w_{role.value[:3]}_{uuid.uuid4().hex[:6]}"

        def _on_complete(result: AgentResult):
            with self._lock:
                self._results[agent_id] = result
            self._completion_event.set()

        worker = WorkerAgent(
            agent_id=agent_id,
            role=role,
            llm=self.llm,
            tool_registry=self.tool_registry,
            event_bus=self.event_bus,
            on_complete=_on_complete,
        )

        with self._lock:
            self._workers[agent_id] = worker

        logger.info(f"Spawned worker {agent_id} ({role.value}): {task[:80]}")

        worker.run(task, extra_context=extra_context, wait=wait, timeout=timeout)

        return worker

    def spawn_many(
        self,
        tasks: List[Dict[str, Any]],
        wait_all: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> List[WorkerAgent]:
        """
        Spawn multiple workers in parallel.

        Args:
            tasks: List of {"role": AgentRole, "task": str, "extra_context": str}
            wait_all: Block until all complete
            timeout: Max seconds for all to complete

        Returns:
            List of WorkerAgent instances
        """
        workers = []
        for t in tasks:
            role = t.get("role", AgentRole.GENERAL)
            task = t["task"]
            extra = t.get("extra_context", "")
            worker = self.spawn(role, task, extra_context=extra)
            workers.append(worker)

        if wait_all:
            self.wait_all(timeout=timeout)

        return workers

    def wait(self, agent_id: str, timeout: float = DEFAULT_TIMEOUT) -> Optional[AgentResult]:
        """Wait for a specific worker to complete."""
        worker = self._workers.get(agent_id)
        if not worker:
            return None

        if worker._thread:
            worker._thread.join(timeout=timeout)

        return worker.result

    def wait_all(self, timeout: float = DEFAULT_TIMEOUT):
        """Wait for all active workers to complete."""
        deadline = time.time() + timeout

        with self._lock:
            active_workers = [w for w in self._workers.values() if not w.is_done]

        for worker in active_workers:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            if worker._thread:
                worker._thread.join(timeout=max(0.1, remaining))

    def get_result(self, agent_id: str) -> Optional[AgentResult]:
        """Get result for a specific agent (None if not done)."""
        with self._lock:
            return self._results.get(agent_id)

    def get_all_results(self) -> Dict[str, AgentResult]:
        """Get all completed results."""
        with self._lock:
            return dict(self._results)

    def get_status(self) -> Dict[str, Any]:
        """Get pool status overview."""
        with self._lock:
            workers_info = []
            for wid, w in self._workers.items():
                workers_info.append({
                    "id": wid,
                    "role": w.role.value,
                    "status": w.status,
                    "elapsed": round(time.time() - w._started_at, 1) if w._started_at else 0,
                })

        active = sum(1 for w in workers_info if w["status"] == "running")
        completed = sum(1 for w in workers_info if w["status"] == "completed")
        failed = sum(1 for w in workers_info if w["status"] == "failed")

        return {
            "total_workers": len(workers_info),
            "active": active,
            "completed": completed,
            "failed": failed,
            "max_concurrent": self.max_concurrent,
            "workers": workers_info,
        }

    def cleanup(self, keep_results: bool = True):
        """Remove completed workers. Optionally keep results."""
        with self._lock:
            done_ids = [wid for wid, w in self._workers.items() if w.is_done]
            for wid in done_ids:
                del self._workers[wid]
            if not keep_results:
                self._results.clear()

        logger.debug(f"Cleaned up {len(done_ids)} completed workers")

    def shutdown(self):
        """Wait for all workers and clean up everything."""
        self.wait_all(timeout=30)
        with self._lock:
            self._workers.clear()
            self._results.clear()
        logger.info("Agent pool shut down")
