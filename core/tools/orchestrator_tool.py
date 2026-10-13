"""
ARIA - Orchestrator Tool
=========================

Exposes the multi-agent orchestrator as a tool in ARIA's tool registry.
The LLM can invoke this to delegate complex tasks to specialist workers.

Actions:
  - parallel: decompose + parallel workers + synthesize
  - delegate: send task to a specific specialist
  - review: evaluate a response for quality
  - status: check orchestrator/pool status
"""

import logging
from typing import Any, Dict

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.orchestrator")


class OrchestratorTool(ToolBase):
    """Multi-agent orchestrator — delegate complex tasks to specialist workers."""

    name = "orchestrate"
    description = (
        "Orchestrate multi-agent execution for complex tasks. "
        "Actions: "
        "'parallel' — decompose a complex task, run specialist agents in parallel, synthesize results. "
        "'delegate' — send a task to a specific specialist (researcher/coder/analyst/writer). "
        "'review' — evaluate a response for accuracy and completeness. "
        "'status' — check orchestrator status and active workers. "
        "Use 'parallel' for complex multi-faceted tasks. "
        "Use 'delegate' when you know exactly which specialist to use. "
        "Use 'review' to verify important responses before delivering them."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action: parallel, delegate, review, status",
            required=True,
            enum=["parallel", "delegate", "review", "status"],
        ),
        ToolParam(
            name="task",
            type="string",
            description="Task description (required for parallel/delegate)",
            required=False,
        ),
        ToolParam(
            name="role",
            type="string",
            description="Specialist role for delegate action: researcher, coder, analyst, writer, general",
            required=False,
            default="general",
            enum=["researcher", "coder", "analyst", "writer", "general"],
        ),
        ToolParam(
            name="response",
            type="string",
            description="Response text to review (required for review action)",
            required=False,
        ),
        ToolParam(
            name="context",
            type="string",
            description="Additional context for the agent(s)",
            required=False,
            default="",
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        orchestrator = self.context.get("orchestrator")

        if not orchestrator:
            return ToolResult(
                success=False,
                error="Orchestrator not available. Multi-agent system not initialized.",
            )

        if action == "parallel":
            return self._parallel(orchestrator, kwargs)
        elif action == "delegate":
            return self._delegate(orchestrator, kwargs)
        elif action == "review":
            return self._review(orchestrator, kwargs)
        elif action == "status":
            return self._status(orchestrator)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    def _parallel(self, orchestrator, kwargs) -> ToolResult:
        task = kwargs.get("task")
        if not task:
            return ToolResult(success=False, error="'task' is required for parallel action")

        try:
            result = orchestrator.parallel_execute(task=task, timeout=120)
            return ToolResult(
                success=True,
                output=result,
                data={"action": "parallel", "stats": orchestrator.get_stats()},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Parallel execution failed: {e}")

    def _delegate(self, orchestrator, kwargs) -> ToolResult:
        task = kwargs.get("task")
        if not task:
            return ToolResult(success=False, error="'task' is required for delegate action")

        role_str = kwargs.get("role", "general")
        extra_context = kwargs.get("context", "")

        from core.agents.agent_protocol import AgentRole
        try:
            role = AgentRole(role_str)
        except ValueError:
            role = AgentRole.GENERAL

        try:
            result = orchestrator.delegate(
                role=role,
                task=task,
                extra_context=extra_context,
                wait=True,
                timeout=120,
            )

            if result and result.success:
                return ToolResult(
                    success=True,
                    output=f"[{role.value} agent — {result.elapsed_seconds}s]\n{result.output}",
                    data={
                        "agent_id": result.agent_id,
                        "role": role.value,
                        "tools_used": result.tools_used,
                        "elapsed": result.elapsed_seconds,
                    },
                )
            else:
                error = result.error if result else "Agent returned no result"
                return ToolResult(success=False, error=f"Agent failed: {error}")

        except Exception as e:
            return ToolResult(success=False, error=f"Delegation failed: {e}")

    def _review(self, orchestrator, kwargs) -> ToolResult:
        task = kwargs.get("task", "")
        response = kwargs.get("response")
        if not response:
            return ToolResult(success=False, error="'response' is required for review action")

        try:
            result = orchestrator.review(task=task, response=response)

            if result and result.success:
                verdict = result.review_verdict or "UNKNOWN"
                feedback = result.review_feedback or result.output
                return ToolResult(
                    success=True,
                    output=f"Review verdict: {verdict}\n\n{feedback}",
                    data={
                        "verdict": verdict,
                        "feedback": feedback,
                        "reviewed": result.reviewed,
                    },
                )
            else:
                return ToolResult(
                    success=False,
                    error=f"Review failed: {result.error if result else 'unknown'}",
                )

        except Exception as e:
            return ToolResult(success=False, error=f"Review failed: {e}")

    def _status(self, orchestrator) -> ToolResult:
        stats = orchestrator.get_stats()
        pool = stats["pool"]

        lines = [
            f"Orchestrator Stats:",
            f"  Total orchestrations: {stats['total_orchestrations']}",
            f"  Total workers spawned: {stats['total_workers_spawned']}",
            f"  Self-review: {'enabled' if stats['review_enabled'] else 'disabled'}",
            f"",
            f"Pool Status:",
            f"  Active: {pool['active']}/{pool['max_concurrent']}",
            f"  Completed: {pool['completed']}",
            f"  Failed: {pool['failed']}",
        ]

        if pool["workers"]:
            lines.append("")
            lines.append("Workers:")
            for w in pool["workers"]:
                lines.append(f"  [{w['id']}] {w['role']} — {w['status']} ({w['elapsed']}s)")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data=stats,
        )
