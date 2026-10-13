"""
ARIA - Multi-Agent Orchestrator
=================================

The Orchestrator is ARIA's multi-agent coordinator. It implements three patterns:

1. **Parallel Workers**: Split a complex task into subtasks, run workers
   in parallel, synthesize their results into a unified response.

2. **Self-Review**: After generating a response, spawn a reviewer agent
   to evaluate it. If the review says REVISE, iterate.

3. **Supervisor Delegation**: ARIA detects a task needs specialist(s),
   spawns the right worker(s), collects results.

The Orchestrator is exposed as a tool so the LLM can invoke it naturally.
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

from .agent_protocol import AgentRole, AgentResult, WorkerAgent
from .agent_pool import AgentPool

logger = logging.getLogger("aria.agents.orchestrator")


# Task decomposition prompt
DECOMPOSE_PROMPT = """You are a task planner. Break the following complex task into 2-4 independent subtasks that can be done in parallel by specialist agents.

Available agent roles:
- researcher: web search, information gathering, fact-finding
- coder: write/execute code, shell commands, file operations
- analyst: calculations, data analysis, statistics
- writer: compose text, draft documents, translate

Task: {task}

Return a JSON array of subtasks. Each subtask:
{{"role": "researcher|coder|analyst|writer", "task": "specific subtask description"}}

RULES:
- Each subtask must be independent (no dependencies between them)
- Be specific — each agent works alone without seeing others' progress
- 2-4 subtasks max
- Return ONLY the JSON array, no explanation"""

# Synthesis prompt
SYNTHESIZE_PROMPT = """You are synthesizing results from multiple specialist agents into one coherent response.

Original task: {task}

Agent results:
{results}

Create a unified, well-organized response that combines all findings.
Be concise but complete. Credit specific findings where useful.
If any agent failed, note what's missing and work around it."""

# Review prompt
REVIEW_PROMPT = """Review the following response for:
1. Accuracy — are claims correct and well-supported?
2. Completeness — does it fully address the task?
3. Clarity — is it well-organized and easy to understand?
4. Issues — any errors, gaps, or misleading statements?

Task: {task}

Response to review:
{response}

Return your verdict as:
VERDICT: APPROVE or REVISE
FEEDBACK: (specific feedback, especially if REVISE)"""


class Orchestrator:
    """
    Multi-agent task orchestrator.

    Integrates with ARIA's existing infrastructure:
    - Uses the shared LLM provider
    - Creates worker agents via AgentPool
    - Communicates via EventBus
    - Exposed as a tool in ToolRegistry
    """

    def __init__(
        self,
        llm,
        tool_registry,
        event_bus=None,
        max_workers: int = 6,
        review_enabled: bool = True,
        max_review_rounds: int = 2,
    ):
        self.llm = llm
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self.review_enabled = review_enabled
        self.max_review_rounds = max_review_rounds

        self.pool = AgentPool(
            llm=llm,
            tool_registry=tool_registry,
            event_bus=event_bus,
            max_concurrent=max_workers,
        )

        # Stats
        self._total_orchestrations = 0
        self._total_workers_spawned = 0

    # =========================================================================
    # Pattern 1: Parallel Workers
    # =========================================================================

    def parallel_execute(
        self,
        task: str,
        timeout: float = 120,
    ) -> str:
        """
        Decompose a task into subtasks, run workers in parallel, synthesize.

        Args:
            task: Complex task to decompose and execute
            timeout: Max seconds for all workers

        Returns:
            Synthesized response string
        """
        self._total_orchestrations += 1

        # Step 1: Decompose task via LLM
        subtasks = self._decompose_task(task)
        if not subtasks:
            return self._fallback_single(task, timeout)

        logger.info(f"Orchestrator: decomposed into {len(subtasks)} subtasks")

        if self.event_bus:
            self.event_bus.emit("orchestrator", "decompose", {
                "task": task[:200],
                "subtasks": len(subtasks),
            })

        # Step 2: Spawn workers
        workers = []
        for st in subtasks:
            role_str = st.get("role", "general")
            try:
                role = AgentRole(role_str)
            except ValueError:
                role = AgentRole.GENERAL

            worker = self.pool.spawn(
                role=role,
                task=st["task"],
            )
            workers.append(worker)
            self._total_workers_spawned += 1

        # Step 3: Wait for all
        self.pool.wait_all(timeout=timeout)

        # Step 4: Collect results
        results = []
        for w in workers:
            r = w.result
            if r:
                results.append(r)

        if not results:
            return "[All workers failed to produce results]"

        # Step 5: Synthesize
        synthesized = self._synthesize_results(task, results)

        # Step 6: Optional self-review
        if self.review_enabled:
            synthesized = self._self_review(task, synthesized)

        # Cleanup
        self.pool.cleanup()

        return synthesized

    # =========================================================================
    # Pattern 2: Self-Review
    # =========================================================================

    def review(self, task: str, response: str) -> AgentResult:
        """
        Spawn a reviewer agent to evaluate a response.

        Returns:
            AgentResult with review_verdict and review_feedback
        """
        reviewer = self.pool.spawn(
            role=AgentRole.REVIEWER,
            task=REVIEW_PROMPT.format(task=task, response=response[:3000]),
            wait=True,
            timeout=30,
        )

        result = reviewer.result
        if result and result.success:
            # Parse verdict
            output = result.output
            if "VERDICT:" in output:
                verdict_line = [l for l in output.split("\n") if "VERDICT:" in l]
                if verdict_line:
                    verdict = "APPROVE" if "APPROVE" in verdict_line[0] else "REVISE"
                    result.review_verdict = verdict

                    # Extract feedback
                    feedback_start = output.find("FEEDBACK:")
                    if feedback_start != -1:
                        result.review_feedback = output[feedback_start + 9:].strip()
                    else:
                        result.review_feedback = output

                    result.reviewed = True

        self.pool.cleanup()
        return result

    def _self_review(self, task: str, response: str) -> str:
        """Internal self-review loop. Returns improved response."""
        for round_num in range(self.max_review_rounds):
            review_result = self.review(task, response)

            if not review_result or not review_result.success:
                break  # Can't review, return as-is

            if review_result.review_verdict == "APPROVE":
                logger.info(f"Self-review: APPROVED on round {round_num + 1}")
                break

            if review_result.review_verdict == "REVISE" and review_result.review_feedback:
                logger.info(f"Self-review: REVISE requested on round {round_num + 1}")
                # Revise using feedback
                response = self._revise(task, response, review_result.review_feedback)

        return response

    # =========================================================================
    # Pattern 3: Supervisor Delegation
    # =========================================================================

    def delegate(
        self,
        role: AgentRole,
        task: str,
        extra_context: str = "",
        wait: bool = True,
        timeout: float = 120,
    ) -> AgentResult:
        """
        Delegate a task to a specific specialist agent.

        This is the simplest pattern — ARIA decides it needs a specialist
        and sends the task directly.
        """
        self._total_orchestrations += 1
        self._total_workers_spawned += 1

        worker = self.pool.spawn(
            role=role,
            task=task,
            extra_context=extra_context,
            wait=wait,
            timeout=timeout,
        )

        result = worker.result if wait else None
        if wait:
            self.pool.cleanup()

        return result

    def delegate_many(
        self,
        assignments: List[Dict[str, Any]],
        timeout: float = 120,
    ) -> List[AgentResult]:
        """
        Delegate multiple tasks to specialists in parallel.

        Args:
            assignments: List of {"role": AgentRole, "task": str}
            timeout: Max total wait time

        Returns:
            List of AgentResults
        """
        self._total_orchestrations += 1

        workers = self.pool.spawn_many(
            tasks=assignments,
            wait_all=True,
            timeout=timeout,
        )

        self._total_workers_spawned += len(workers)

        results = [w.result for w in workers if w.result]
        self.pool.cleanup()
        return results

    # =========================================================================
    # Helper methods
    # =========================================================================

    def _decompose_task(self, task: str) -> List[Dict[str, str]]:
        """Use LLM to decompose a complex task into subtasks."""
        try:
            response = self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": DECOMPOSE_PROMPT.format(task=task),
                }],
                system="You are a task decomposition engine. Return only valid JSON.",
                max_tokens=500,
            )

            if not response or not response.content:
                return []

            # Parse JSON from response
            text = response.content.strip()
            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            subtasks = json.loads(text)
            if not isinstance(subtasks, list) or len(subtasks) < 2:
                return []

            # Validate structure
            valid = []
            for st in subtasks[:4]:  # Max 4
                if isinstance(st, dict) and "task" in st:
                    valid.append({
                        "role": st.get("role", "general"),
                        "task": st["task"],
                    })

            return valid if len(valid) >= 2 else []

        except (json.JSONDecodeError, Exception) as e:
            logger.debug(f"Task decomposition failed: {e}")
            return []

    def _synthesize_results(self, task: str, results: List[AgentResult]) -> str:
        """Use LLM to synthesize multiple agent results into one response."""
        results_text = ""
        for r in results:
            status = "SUCCESS" if r.success else "FAILED"
            results_text += f"\n--- {r.role.value} agent [{status}] ---\n"
            if r.success:
                results_text += r.output[:2000] + "\n"
            else:
                results_text += f"Error: {r.error}\n"

        try:
            response = self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": SYNTHESIZE_PROMPT.format(
                        task=task,
                        results=results_text,
                    ),
                }],
                system="You are a synthesis engine. Combine multiple sources into one clear response.",
                max_tokens=3000,
            )

            return response.content if response and response.content else results_text

        except Exception as e:
            logger.warning(f"Synthesis failed: {e}")
            # Fallback: concatenate results
            return results_text

    def _revise(self, task: str, response: str, feedback: str) -> str:
        """Revise a response based on review feedback."""
        try:
            result = self.llm.chat(
                messages=[{
                    "role": "user",
                    "content": (
                        f"Revise this response based on the feedback.\n\n"
                        f"Original task: {task}\n\n"
                        f"Current response:\n{response[:2000]}\n\n"
                        f"Feedback:\n{feedback}\n\n"
                        f"Return the improved response."
                    ),
                }],
                max_tokens=3000,
            )
            return result.content if result and result.content else response
        except Exception:
            return response

    def _fallback_single(self, task: str, timeout: float) -> str:
        """Fallback: run as single general agent if decomposition fails."""
        logger.info("Orchestrator: decomposition failed, falling back to single agent")
        result = self.delegate(
            role=AgentRole.GENERAL,
            task=task,
            wait=True,
            timeout=timeout,
        )
        return result.output if result and result.success else f"[Agent failed: {result.error if result else 'unknown'}]"

    def get_stats(self) -> Dict[str, Any]:
        """Get orchestrator statistics."""
        pool_status = self.pool.get_status()
        return {
            "total_orchestrations": self._total_orchestrations,
            "total_workers_spawned": self._total_workers_spawned,
            "review_enabled": self.review_enabled,
            "pool": pool_status,
        }

    def shutdown(self):
        """Clean shutdown of pool."""
        self.pool.shutdown()
