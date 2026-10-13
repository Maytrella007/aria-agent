"""
ARIA - Agent Protocol
======================

Defines the base interface for worker agents in the multi-agent system.
Worker agents are lightweight — they get an LLM, a tool subset, and a task.
They run in threads, communicate via EventBus, and return structured results.

Unlike the main ARIA agent, workers have no memory, no personality,
no autonomy — they are pure task executors.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("aria.agents.protocol")


class AgentRole(Enum):
    """Predefined agent specializations."""
    RESEARCHER = "researcher"
    CODER = "coder"
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    WRITER = "writer"
    MONITOR = "monitor"
    GENERAL = "general"


# Role → system prompt + allowed tools
ROLE_CONFIGS = {
    AgentRole.RESEARCHER: {
        "system": (
            "You are a research agent. Find and synthesize information from multiple sources. "
            "Be thorough but concise. Cite sources when possible. "
            "Limit: 4 tool calls max."
        ),
        "tools": ["web_search", "web_fetch", "rag", "calculator"],
        "max_tokens": 2000,
        "max_rounds": 5,
    },
    AgentRole.CODER: {
        "system": (
            "You are a coding agent. Write, execute, and debug code. "
            "Return clean, working code with brief explanations. "
            "Limit: 6 tool calls max."
        ),
        "tools": ["code_exec", "shell_exec", "file_manager", "git"],
        "max_tokens": 3000,
        "max_rounds": 7,
    },
    AgentRole.ANALYST: {
        "system": (
            "You are a data analysis agent. Analyze data, compute statistics, "
            "and provide clear insights. Use structured output when possible. "
            "Limit: 4 tool calls max."
        ),
        "tools": ["calculator", "database", "code_exec", "rag"],
        "max_tokens": 2000,
        "max_rounds": 5,
    },
    AgentRole.REVIEWER: {
        "system": (
            "You are a review agent. Evaluate the provided content for: "
            "accuracy, completeness, clarity, and potential issues. "
            "Return a structured review with verdict (APPROVE/REVISE) and specific feedback. "
            "Do NOT use tools — review based on your knowledge."
        ),
        "tools": [],
        "max_tokens": 1500,
        "max_rounds": 1,
    },
    AgentRole.WRITER: {
        "system": (
            "You are a writing agent. Compose clear, well-structured text. "
            "Match the requested tone and format. "
            "Limit: 3 tool calls max."
        ),
        "tools": ["web_search", "web_fetch", "rag", "file_manager"],
        "max_tokens": 2500,
        "max_rounds": 4,
    },
    AgentRole.MONITOR: {
        "system": (
            "You are a monitoring agent. Check the specified resources and report status. "
            "Be precise with metrics and timestamps. "
            "Limit: 3 tool calls max."
        ),
        "tools": ["web_fetch", "shell_exec", "system_info", "web_search"],
        "max_tokens": 1000,
        "max_rounds": 4,
    },
    AgentRole.GENERAL: {
        "system": (
            "You are a general-purpose agent. Complete the task efficiently. "
            "Return a clear, actionable result. "
            "Limit: 5 tool calls max."
        ),
        "tools": [
            "web_search", "web_fetch", "calculator", "code_exec",
            "shell_exec", "file_manager", "system_info",
        ],
        "max_tokens": 2000,
        "max_rounds": 6,
    },
}


@dataclass
class AgentMessage:
    """Message between agents via EventBus."""
    from_agent: str          # sender agent ID
    to_agent: str            # target agent ID ("orchestrator" for main)
    msg_type: str            # "task", "result", "status", "review_request", "review_response"
    content: str             # message body
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class AgentResult:
    """Structured result from a worker agent."""
    agent_id: str
    role: AgentRole
    task: str
    success: bool
    output: str = ""
    error: str = ""
    tools_used: List[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    reviewed: bool = False
    review_verdict: str = ""    # "APPROVE" or "REVISE"
    review_feedback: str = ""


class WorkerAgent:
    """
    Lightweight worker agent that runs an LLM+tools loop in a thread.

    Lifecycle:
    1. Created by AgentPool with role, tools, and LLM
    2. Given a task via run(task)
    3. Executes LLM loop with tool calling
    4. Returns AgentResult
    5. Cleaned up by AgentPool
    """

    def __init__(
        self,
        agent_id: str,
        role: AgentRole,
        llm,
        tool_registry,
        event_bus=None,
        on_complete: Optional[Callable] = None,
    ):
        self.agent_id = agent_id
        self.role = role
        self.llm = llm
        self.tool_registry = tool_registry
        self.event_bus = event_bus
        self.on_complete = on_complete

        self._config = ROLE_CONFIGS.get(role, ROLE_CONFIGS[AgentRole.GENERAL])
        self._thread: Optional[threading.Thread] = None
        self._result: Optional[AgentResult] = None
        self._started_at: float = 0
        self._status: str = "idle"  # idle, running, completed, failed

    @property
    def status(self) -> str:
        return self._status

    @property
    def result(self) -> Optional[AgentResult]:
        return self._result

    @property
    def is_done(self) -> bool:
        return self._status in ("completed", "failed")

    def run(self, task: str, extra_context: str = "", wait: bool = False, timeout: float = 120) -> Optional[AgentResult]:
        """
        Start the agent on a task.

        Args:
            task: What to do
            extra_context: Additional context (e.g., other agents' results)
            wait: Block until done
            timeout: Max seconds (only if wait=True)

        Returns:
            AgentResult if wait=True, None if async
        """
        self._started_at = time.time()
        self._status = "running"

        self._thread = threading.Thread(
            target=self._execute_loop,
            args=(task, extra_context),
            name=f"aria-worker-{self.agent_id}",
            daemon=True,
        )
        self._thread.start()

        if wait:
            self._thread.join(timeout=timeout)
            if not self.is_done:
                self._status = "failed"
                self._result = AgentResult(
                    agent_id=self.agent_id,
                    role=self.role,
                    task=task,
                    success=False,
                    error=f"Timeout after {timeout}s",
                    elapsed_seconds=time.time() - self._started_at,
                )
            return self._result

        return None

    def _execute_loop(self, task: str, extra_context: str):
        """Core LLM + tool loop (runs in thread)."""
        import json

        tools_used = []
        max_rounds = self._config["max_rounds"]
        max_tokens = self._config["max_tokens"]
        allowed_tools = self._config["tools"]

        # Build tool schemas for allowed tools
        tool_schemas = []
        if self.tool_registry and allowed_tools:
            for tool in self.tool_registry.list():
                if tool.name in allowed_tools:
                    tool_schemas.append(tool.to_function_schema())

        # System prompt
        sys_prompt = self._config["system"]
        if extra_context:
            sys_prompt += f"\n\nADDITIONAL CONTEXT:\n{extra_context}"

        messages = [{"role": "user", "content": task}]

        # Emit start event
        if self.event_bus:
            self.event_bus.emit("agent", "start", {
                "agent_id": self.agent_id,
                "role": self.role.value,
                "task": task[:200],
            }, run_id=self.agent_id)

        try:
            response = None
            for round_num in range(1, max_rounds + 1):
                response = self.llm.chat(
                    messages=messages,
                    system=sys_prompt,
                    max_tokens=max_tokens,
                    tools=tool_schemas if tool_schemas else None,
                )

                if not response.tool_calls:
                    break

                # Execute tools
                provider = response.provider

                if provider == "anthropic":
                    messages.append({
                        "role": "assistant",
                        "content": response.raw_response.content,
                    })
                    tool_result_blocks = []
                    for tc in response.tool_calls:
                        tools_used.append(tc.name)
                        result = self.tool_registry.execute(tc.name, **tc.args)
                        tool_result_blocks.append({
                            "type": "tool_result",
                            "tool_use_id": tc.id,
                            "content": str(result)[:5000],
                        })
                        if self.event_bus:
                            self.event_bus.emit("agent", "tool", {
                                "agent_id": self.agent_id,
                                "tool": tc.name,
                                "success": result.success,
                            }, run_id=self.agent_id)
                    messages.append({"role": "user", "content": tool_result_blocks})
                else:
                    # OpenAI-compatible format
                    assistant_msg = {"role": "assistant", "content": response.content or ""}
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc.id or f"call_{uuid.uuid4().hex[:8]}",
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.args),
                            },
                        }
                        for tc in response.tool_calls
                    ]
                    messages.append(assistant_msg)

                    for tc in response.tool_calls:
                        tools_used.append(tc.name)
                        result = self.tool_registry.execute(tc.name, **tc.args)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": str(result)[:5000],
                        })
                        if self.event_bus:
                            self.event_bus.emit("agent", "tool", {
                                "agent_id": self.agent_id,
                                "tool": tc.name,
                                "success": result.success,
                            }, run_id=self.agent_id)

            # Build result
            output = response.content if response else "[No response]"
            elapsed = time.time() - self._started_at

            self._result = AgentResult(
                agent_id=self.agent_id,
                role=self.role,
                task=task,
                success=True,
                output=output or "[Empty response]",
                tools_used=tools_used,
                elapsed_seconds=round(elapsed, 1),
            )
            self._status = "completed"

        except Exception as e:
            elapsed = time.time() - self._started_at
            self._result = AgentResult(
                agent_id=self.agent_id,
                role=self.role,
                task=task,
                success=False,
                error=str(e),
                tools_used=tools_used,
                elapsed_seconds=round(elapsed, 1),
            )
            self._status = "failed"
            logger.error(f"Worker {self.agent_id} failed: {e}")

        # Emit completion event
        if self.event_bus:
            self.event_bus.emit("agent", "done", {
                "agent_id": self.agent_id,
                "success": self._result.success,
                "elapsed": self._result.elapsed_seconds,
                "tools_used": tools_used,
            }, run_id=self.agent_id)

        # Notify pool
        if self.on_complete:
            try:
                self.on_complete(self._result)
            except Exception:
                pass
