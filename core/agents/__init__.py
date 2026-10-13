"""
ARIA Multi-Agent System
========================

Supervisor + Workers architecture:
- ARIA remains the central agent with full capabilities
- Workers are lightweight, specialized agents spawned for parallel tasks
- Self-review agent validates outputs before delivery
- Background monitors extend AutonomousEngine

Components:
- AgentProtocol: base interface for all agents
- Orchestrator: routes complex tasks to worker teams
- AgentPool: manages worker lifecycle and concurrency
- Communication: inter-agent messaging via EventBus
"""

from .agent_protocol import WorkerAgent, AgentRole, AgentMessage, AgentResult
from .orchestrator import Orchestrator
from .agent_pool import AgentPool

__all__ = [
    "WorkerAgent",
    "AgentRole",
    "AgentMessage",
    "AgentResult",
    "Orchestrator",
    "AgentPool",
]
