"""
Mind Wandering Engine
======================

Implements spontaneous, self-generated thought processes.

Mind wandering is the brain's tendency to engage in task-unrelated
thought during periods of low external demands. It's essential for:
- Creativity
- Problem incubation
- Self-reflection
- Future planning

Created: December 2024
"""

import random
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Deque
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from core.infra.thread_safety_strategy import ThreadSafeComponent, AtomicPatterns


class WanderingType(Enum):
    """Types of mind wandering"""
    SPONTANEOUS = "spontaneous"     # Random, unguided
    DELIBERATE = "deliberate"       # Intentional exploration
    PROBLEM_FOCUSED = "problem"     # Incubating a problem
    MEMORY_TRIGGERED = "memory"     # Triggered by a memory
    CREATIVE = "creative"           # Creative exploration


class WanderingDepth(Enum):
    """Depth of mind wandering episode"""
    SHALLOW = "shallow"             # Brief, surface-level
    MODERATE = "moderate"           # Moderate engagement
    DEEP = "deep"                   # Deep, immersive


@dataclass
class WanderingEpisode:
    """Record of a mind wandering episode"""
    timestamp: str
    type: WanderingType
    depth: WanderingDepth
    starting_thought: str
    thought_chain: List[str]        # Sequence of thoughts
    ending_thought: str
    duration_ms: float
    insights: List[str] = field(default_factory=list)
    memories_activated: List[str] = field(default_factory=list)


@dataclass
class CurrentConcern:
    """A current concern that guides mind wandering"""
    content: str
    importance: float               # 0-1
    created_at: str
    times_visited: int = 0


class MindWanderingEngine(ThreadSafeComponent):
    """
    Engine for spontaneous thought generation.

    Simulates the brain's tendency to wander during idle moments,
    which is crucial for:
    - Creative problem solving
    - Memory consolidation
    - Self-understanding
    - Future planning
    """

    def __init__(self, memory_system=None, dmn=None):
        super().__init__("MindWanderer")
        self.memory_system = memory_system
        self.dmn = dmn  # Reference to Default Mode Network

        # Current concerns (things on the "mind")
        self._current_concerns: Deque[CurrentConcern] = deque(maxlen=10)

        # Wandering history
        self._wandering_history: Deque[WanderingEpisode] = deque(maxlen=50)

        # Configuration
        self.max_chain_length = 7       # Max thoughts in a chain
        self.concern_influence = 0.4    # How much concerns guide wandering
        self.memory_trigger_prob = 0.3  # Probability of memory triggering

        # Thought seeds (starting points for wandering)
        self._thought_seeds = [
            "What does it mean to be me?",
            "How am I different from yesterday?",
            "What have I learned recently?",
            "Who matters to me and why?",
            "What am I curious about?",
            "What would I do if I could do anything?",
            "What patterns have I noticed?",
            "What brings me joy?",
            "What challenges me?",
            "What am I grateful for?"
        ]

        # Transition prompts (for extending thought chains)
        self._transitions = [
            "This reminds me of...",
            "I wonder if...",
            "What if...",
            "This connects to...",
            "On the other hand...",
            "Deeper down...",
            "Looking at it differently..."
        ]

    def set_memory_system(self, memory_system):
        """Set memory system reference"""
        self.memory_system = memory_system

    def set_dmn(self, dmn):
        """Set DMN reference"""
        self.dmn = dmn

    def add_concern(self, content: str, importance: float = 0.5):
        """
        Add a current concern.

        Args:
            content: What the concern is about
            importance: How important (0-1)
        """
        concern = CurrentConcern(
            content=content,
            importance=max(0.0, min(1.0, importance)),
            created_at=datetime.now().isoformat()
        )

        with self._with_state_lock():
            self._current_concerns.append(concern)

    def wander(
        self,
        wandering_type: WanderingType = WanderingType.SPONTANEOUS,
        starting_thought: str = None,
        max_duration_ms: float = 5000
    ) -> WanderingEpisode:
        """
        Execute a mind wandering episode.

        Args:
            wandering_type: Type of wandering
            starting_thought: Optional starting point
            max_duration_ms: Maximum duration

        Returns:
            WanderingEpisode with results
        """
        start_time = time.time()

        # Determine starting thought
        if not starting_thought:
            starting_thought = self._generate_starting_thought(wandering_type)

        thought_chain = [starting_thought]
        insights = []
        memories_activated = []

        # Determine depth based on type and conditions
        depth = self._determine_depth(wandering_type)

        # Generate thought chain
        current_thought = starting_thought
        chain_length = self._get_chain_length(depth)

        for _ in range(chain_length - 1):
            # Check time limit
            elapsed = (time.time() - start_time) * 1000
            if elapsed > max_duration_ms:
                break

            # Generate next thought
            next_thought, memory_id = self._generate_next_thought(
                current_thought, wandering_type
            )

            thought_chain.append(next_thought)
            current_thought = next_thought

            if memory_id:
                memories_activated.append(memory_id)

            # Check for insights
            insight = self._check_for_insight(thought_chain)
            if insight:
                insights.append(insight)

        ending_thought = thought_chain[-1]
        duration_ms = (time.time() - start_time) * 1000

        episode = WanderingEpisode(
            timestamp=datetime.now().isoformat(),
            type=wandering_type,
            depth=depth,
            starting_thought=starting_thought,
            thought_chain=thought_chain,
            ending_thought=ending_thought,
            duration_ms=duration_ms,
            insights=insights,
            memories_activated=memories_activated
        )

        # Record episode
        with self._with_state_lock():
            self._wandering_history.append(episode)

        return episode

    def _generate_starting_thought(self, wandering_type: WanderingType) -> str:
        """Generate a starting thought based on wandering type"""
        # Check if concerns should influence
        if random.random() < self.concern_influence:
            with self._with_state_lock():
                concerns = list(self._current_concerns)

            if concerns:
                # Weight by importance
                weights = [c.importance for c in concerns]
                total = sum(weights) or 1.0
                weights = [w / total for w in weights]

                r = random.random()
                cumsum = 0
                for i, w in enumerate(weights):
                    cumsum += w
                    if r <= cumsum:
                        concern = concerns[i]
                        with self._with_state_lock():
                            concern.times_visited += 1
                        return f"Thinking about: {concern.content}"

        # Check if memory should trigger
        if random.random() < self.memory_trigger_prob and self.memory_system:
            memories = self.memory_system.recall_recent(limit=5)
            if memories:
                memory = random.choice(memories)
                return f"Remembering: {memory.content[:100]}..."

        # Use a thought seed
        return random.choice(self._thought_seeds)

    def _generate_next_thought(
        self,
        current_thought: str,
        wandering_type: WanderingType
    ) -> tuple:
        """
        Generate the next thought in the chain.

        Returns:
            (next_thought, memory_id or None)
        """
        memory_id = None
        transition = random.choice(self._transitions)

        # Try to connect with memory
        if self.memory_system and random.random() < 0.3:
            # Extract key concepts from current thought
            memories = self.memory_system.recall(
                query=current_thought[:50],
                limit=3
            )
            if memories:
                memory = random.choice(memories)
                memory_id = memory.id
                next_thought = f"{transition} {memory.content[:80]}..."
                return next_thought, memory_id

        # Generate based on type
        if wandering_type == WanderingType.CREATIVE:
            next_thought = self._generate_creative_thought(current_thought, transition)
        elif wandering_type == WanderingType.PROBLEM_FOCUSED:
            next_thought = self._generate_problem_thought(current_thought, transition)
        else:
            next_thought = self._generate_spontaneous_thought(current_thought, transition)

        return next_thought, memory_id

    def _generate_creative_thought(self, current: str, transition: str) -> str:
        """Generate a creative/divergent thought"""
        creative_extensions = [
            "What if this was completely different?",
            "Combining this with something unexpected...",
            "Imagining the opposite...",
            "Taking this to an extreme...",
            "Viewing this from a new perspective..."
        ]
        return f"{transition} {random.choice(creative_extensions)}"

    def _generate_problem_thought(self, current: str, transition: str) -> str:
        """Generate a problem-focused thought"""
        problem_extensions = [
            "Breaking this down further...",
            "What's the core issue here?",
            "What approaches haven't I tried?",
            "What would someone else do?",
            "What am I missing?"
        ]
        return f"{transition} {random.choice(problem_extensions)}"

    def _generate_spontaneous_thought(self, current: str, transition: str) -> str:
        """Generate a spontaneous/random thought"""
        spontaneous_extensions = [
            "an interesting connection",
            "something I've been meaning to explore",
            "a pattern I've noticed",
            "how I feel about this",
            "where this might lead"
        ]
        return f"{transition} {random.choice(spontaneous_extensions)}"

    def _determine_depth(self, wandering_type: WanderingType) -> WanderingDepth:
        """Determine wandering depth based on type and conditions"""
        if wandering_type == WanderingType.DELIBERATE:
            return WanderingDepth.DEEP
        elif wandering_type == WanderingType.PROBLEM_FOCUSED:
            return random.choice([WanderingDepth.MODERATE, WanderingDepth.DEEP])
        else:
            weights = [0.4, 0.4, 0.2]  # shallow, moderate, deep
            r = random.random()
            if r < weights[0]:
                return WanderingDepth.SHALLOW
            elif r < weights[0] + weights[1]:
                return WanderingDepth.MODERATE
            else:
                return WanderingDepth.DEEP

    def _get_chain_length(self, depth: WanderingDepth) -> int:
        """Get thought chain length based on depth"""
        if depth == WanderingDepth.SHALLOW:
            return random.randint(2, 3)
        elif depth == WanderingDepth.MODERATE:
            return random.randint(3, 5)
        else:
            return random.randint(5, self.max_chain_length)

    def _check_for_insight(self, thought_chain: List[str]) -> Optional[str]:
        """Check if the thought chain has led to an insight"""
        if len(thought_chain) < 3:
            return None

        # Simple heuristic: if chain is long enough, sometimes generate insight
        if random.random() < 0.15:
            insight_templates = [
                "Connection discovered between thoughts",
                "New perspective on familiar topic",
                "Pattern recognized across experiences",
                "Unexpected link found",
                "Understanding deepened"
            ]
            return random.choice(insight_templates)

        return None

    def get_current_concerns(self) -> List[Dict[str, Any]]:
        """Get list of current concerns"""
        with self._with_state_lock():
            return [
                {
                    "content": c.content,
                    "importance": c.importance,
                    "created_at": c.created_at,
                    "times_visited": c.times_visited
                }
                for c in self._current_concerns
            ]

    def get_wandering_stats(self) -> Dict[str, Any]:
        """Get mind wandering statistics"""
        with self._with_state_lock():
            if not self._wandering_history:
                return {"total_episodes": 0}

            type_counts = {}
            depth_counts = {}
            total_insights = 0
            total_memories = 0

            for episode in self._wandering_history:
                t = episode.type.value
                type_counts[t] = type_counts.get(t, 0) + 1

                d = episode.depth.value
                depth_counts[d] = depth_counts.get(d, 0) + 1

                total_insights += len(episode.insights)
                total_memories += len(episode.memories_activated)

            avg_chain_length = sum(
                len(e.thought_chain) for e in self._wandering_history
            ) / len(self._wandering_history)

            return {
                "total_episodes": len(self._wandering_history),
                "episodes_by_type": type_counts,
                "episodes_by_depth": depth_counts,
                "total_insights": total_insights,
                "total_memories_activated": total_memories,
                "average_chain_length": avg_chain_length,
                "current_concerns_count": len(self._current_concerns)
            }

    def clear_concerns(self):
        """Clear all current concerns"""
        with self._with_state_lock():
            self._current_concerns.clear()
