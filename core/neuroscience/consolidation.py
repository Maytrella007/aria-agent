"""
Memory Consolidation System (Neuroscience-Inspired)
====================================================

Implements memory consolidation based on neuroscience principles:
- Sharp Wave Ripple (SWR) simulation for memory replay
- Systems consolidation (hippocampus -> neocortex transfer)
- Sleep-like consolidation phases

Created: December 2024
"""

import random
import time
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

from core.infra.thread_safety_strategy import ThreadSafeComponent, LockLevel, AtomicPatterns


class ConsolidationPhase(Enum):
    """Phases of memory consolidation (inspired by sleep stages)"""
    ENCODING = "encoding"           # Initial memory formation
    EARLY_CONSOLIDATION = "early"   # First hours after encoding
    SWR_REPLAY = "swr_replay"       # Sharp wave ripple replay (NREM-like)
    INTEGRATION = "integration"     # Integration with existing memories
    STABILIZATION = "stabilization" # Long-term stabilization


@dataclass
class ConsolidationEvent:
    """Record of a consolidation event"""
    timestamp: str
    phase: ConsolidationPhase
    memories_processed: int
    memories_strengthened: int
    memories_linked: int
    duration_ms: float
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SWREvent:
    """A Sharp Wave Ripple event (memory replay burst)"""
    timestamp: str
    memory_ids: List[str]           # Memories replayed in sequence
    replay_strength: float          # How strong the replay was (0-1)
    new_connections: List[tuple]    # New connections discovered
    duration_ms: float


class SharpWaveRippleSimulator(ThreadSafeComponent):
    """
    Simulates Sharp Wave Ripple events for memory consolidation.

    SWRs in the hippocampus compress and replay sequences of memories,
    which helps transfer them to long-term storage and discover connections.
    """

    def __init__(self, memory_system=None):
        super().__init__("SWRSimulator")
        self.memory_system = memory_system

        # SWR configuration
        self.min_replay_interval_ms = 50      # Minimum time between replays
        self.max_replay_interval_ms = 200     # Maximum time between replays
        self.sequence_length = 3              # Memories per SWR sequence
        self.connection_threshold = 0.2       # Similarity threshold for connections (lowered from 0.4)

        # State
        self._swr_history: List[SWREvent] = []
        self._total_replays = 0

    def simulate_swr_burst(
        self,
        candidate_memories: List[Any],
        num_ripples: int = 5
    ) -> List[SWREvent]:
        """
        Simulate a burst of Sharp Wave Ripples.

        Args:
            candidate_memories: Pool of memories to replay
            num_ripples: Number of SWR events in the burst

        Returns:
            List of SWR events that occurred
        """
        if not candidate_memories or len(candidate_memories) < 2:
            return []

        events = []
        start_time = time.time()

        for i in range(num_ripples):
            # Select sequence of memories (weighted by importance)
            weights = [m.importance * m.emotional_intensity for m in candidate_memories]
            total_weight = sum(weights) or 1.0
            weights = [w / total_weight for w in weights]

            # Sample memories for this ripple
            sample_size = min(self.sequence_length, len(candidate_memories))
            sequence_indices = self._weighted_sample(
                range(len(candidate_memories)),
                weights,
                sample_size
            )
            sequence = [candidate_memories[i] for i in sequence_indices]
            memory_ids = [m.id for m in sequence]

            # Calculate replay strength based on memory properties
            avg_importance = sum(m.importance for m in sequence) / len(sequence)
            avg_emotion = sum(m.emotional_intensity for m in sequence) / len(sequence)
            replay_strength = (avg_importance + avg_emotion) / 2

            # Discover potential new connections
            new_connections = self._find_connections(sequence)

            # Simulate ripple timing
            ripple_duration = random.uniform(
                self.min_replay_interval_ms,
                self.max_replay_interval_ms
            )

            event = SWREvent(
                timestamp=datetime.now().isoformat(),
                memory_ids=memory_ids,
                replay_strength=replay_strength,
                new_connections=new_connections,
                duration_ms=ripple_duration
            )
            events.append(event)

            # Update state (thread-safe)
            with self._with_state_lock():
                self._swr_history.append(event)
                self._total_replays += 1

            # Brief pause between ripples
            time.sleep(ripple_duration / 1000.0)

        return events

    def _weighted_sample(
        self,
        population: range,
        weights: List[float],
        k: int
    ) -> List[int]:
        """Weighted random sampling without replacement"""
        population = list(population)
        remaining_weights = [weights[p] for p in population]
        result = []

        for _ in range(min(k, len(population))):
            if not population:
                break

            total = sum(remaining_weights)
            if total == 0:
                idx = random.randint(0, len(population) - 1)
            else:
                r = random.random() * total
                cumsum = 0
                idx = 0
                for i, w in enumerate(remaining_weights):
                    cumsum += w
                    if cumsum >= r:
                        idx = i
                        break

            result.append(population[idx])
            population.pop(idx)
            remaining_weights.pop(idx)

        return result

    def _find_connections(self, memories: List[Any]) -> List[tuple]:
        """
        Find potential connections between memories based on content overlap.

        Uses Jaccard similarity for tags plus a bonus for shared people.
        This provides a more balanced connection discovery that works with
        realistic memory data.

        Formula:
        - tag_similarity = |shared_tags| / |all_tags|  (Jaccard index)
        - people_bonus = min(len(shared_people) * 0.3, 0.6)
        - connection_strength = min(1.0, tag_similarity + people_bonus)
        """
        connections = []

        for i, m1 in enumerate(memories):
            for m2 in memories[i + 1:]:
                # Get tags and people sets (handle None gracefully)
                tags1 = set(m1.tags or [])
                tags2 = set(m2.tags or [])
                people1 = set(m1.involves_people or [])
                people2 = set(m2.involves_people or [])

                # Calculate shared elements
                shared_tags = tags1 & tags2
                shared_people = people1 & people2
                all_tags = tags1 | tags2

                # Jaccard similarity for tags (0-1)
                tag_similarity = len(shared_tags) / max(len(all_tags), 1)

                # Bonus for shared people (each person adds 0.3, max 0.6)
                people_bonus = min(len(shared_people) * 0.3, 0.6)

                # Combined connection strength
                connection_strength = min(1.0, tag_similarity + people_bonus)

                if connection_strength >= self.connection_threshold:
                    connections.append((m1.id, m2.id, connection_strength))

        return connections

    def get_swr_stats(self) -> Dict[str, Any]:
        """Get statistics about SWR activity"""
        with self._with_state_lock():
            if not self._swr_history:
                return {"total_replays": 0, "history_size": 0}

            avg_strength = sum(e.replay_strength for e in self._swr_history) / len(self._swr_history)
            total_connections = sum(len(e.new_connections) for e in self._swr_history)

            return {
                "total_replays": self._total_replays,
                "history_size": len(self._swr_history),
                "avg_replay_strength": avg_strength,
                "total_connections_discovered": total_connections,
                "last_replay": self._swr_history[-1].timestamp if self._swr_history else None
            }


class MemoryConsolidator(ThreadSafeComponent):
    """
    Main memory consolidation engine.

    Orchestrates the consolidation process:
    1. Identifies memories needing consolidation
    2. Runs SWR simulation for memory replay
    3. Strengthens replayed memories
    4. Creates new connections
    5. Applies memory decay to non-consolidated memories
    """

    def __init__(self, memory_system=None):
        super().__init__("MemoryConsolidator")
        self.memory_system = memory_system
        self.swr_simulator = SharpWaveRippleSimulator(memory_system)

        # Consolidation parameters
        self.min_age_hours = 1              # Minimum age before consolidation
        self.batch_size = 20                # Memories per consolidation batch
        self.strength_boost = 0.15          # Strength boost per consolidation
        self.consolidation_interval = 3600  # Seconds between consolidation runs

        # State
        self._last_consolidation: Optional[str] = None
        self._consolidation_history: List[ConsolidationEvent] = []
        self._is_consolidating = False

        # Callbacks
        self._on_consolidation_complete: Optional[Callable] = None
        self._on_connection_discovered: Optional[Callable] = None

    def set_memory_system(self, memory_system):
        """Set the memory system reference"""
        self.memory_system = memory_system
        self.swr_simulator.memory_system = memory_system

    def set_callbacks(
        self,
        on_complete: Callable = None,
        on_connection: Callable = None
    ):
        """Set consolidation callbacks"""
        self._on_consolidation_complete = on_complete
        self._on_connection_discovered = on_connection

    def run_consolidation_cycle(self) -> ConsolidationEvent:
        """
        Run a complete consolidation cycle.

        Returns:
            ConsolidationEvent with results
        """
        if not self.memory_system:
            raise ValueError("Memory system not set")

        with self._with_state_lock():
            if self._is_consolidating:
                return None
            self._is_consolidating = True

        start_time = time.time()
        memories_strengthened = 0
        memories_linked = 0

        try:
            # Phase 1: Get consolidation candidates
            candidates = self.memory_system.get_consolidation_candidates(
                limit=self.batch_size
            )

            if not candidates:
                return self._create_event(
                    ConsolidationPhase.ENCODING,
                    0, 0, 0, (time.time() - start_time) * 1000
                )

            # Phase 2: Run SWR simulation
            swr_events = self.swr_simulator.simulate_swr_burst(
                candidates,
                num_ripples=min(10, len(candidates))
            )

            # Phase 3: Process SWR results
            for event in swr_events:
                # Strengthen replayed memories
                for memory_id in event.memory_ids:
                    if self.memory_system.update_memory_strength(
                        memory_id, boost=self.strength_boost * event.replay_strength
                    ):
                        memories_strengthened += 1

                    # Mark as consolidated
                    self.memory_system.mark_consolidated(memory_id)

                # Create discovered connections
                for m1_id, m2_id, strength in event.new_connections:
                    self.memory_system.connect_memories(
                        m1_id, m2_id,
                        f"SWR-discovered (strength: {strength:.2f})"
                    )
                    memories_linked += 1

                    if self._on_connection_discovered:
                        self._on_connection_discovered(m1_id, m2_id, strength)

            # Phase 4: Run central memory maintenance using elapsed real time
            self.memory_system.run_memory_maintenance()

            # Create consolidation event
            duration_ms = (time.time() - start_time) * 1000
            event = self._create_event(
                ConsolidationPhase.INTEGRATION,
                len(candidates),
                memories_strengthened,
                memories_linked,
                duration_ms
            )

            # Update state
            with self._with_state_lock():
                self._last_consolidation = datetime.now().isoformat()
                self._consolidation_history.append(event)
                # Keep only last 100 events
                if len(self._consolidation_history) > 100:
                    self._consolidation_history = self._consolidation_history[-100:]

            # Callback
            if self._on_consolidation_complete:
                self._on_consolidation_complete(event)

            return event

        finally:
            with self._with_state_lock():
                self._is_consolidating = False

    def _create_event(
        self,
        phase: ConsolidationPhase,
        processed: int,
        strengthened: int,
        linked: int,
        duration_ms: float
    ) -> ConsolidationEvent:
        """Create a consolidation event record"""
        return ConsolidationEvent(
            timestamp=datetime.now().isoformat(),
            phase=phase,
            memories_processed=processed,
            memories_strengthened=strengthened,
            memories_linked=linked,
            duration_ms=duration_ms
        )

    def get_consolidation_stats(self) -> Dict[str, Any]:
        """Get consolidation statistics"""
        with self._with_state_lock():
            total_processed = sum(e.memories_processed for e in self._consolidation_history)
            total_strengthened = sum(e.memories_strengthened for e in self._consolidation_history)
            total_linked = sum(e.memories_linked for e in self._consolidation_history)

            return {
                "total_consolidation_cycles": len(self._consolidation_history),
                "total_memories_processed": total_processed,
                "total_memories_strengthened": total_strengthened,
                "total_connections_created": total_linked,
                "last_consolidation": self._last_consolidation,
                "is_consolidating": self._is_consolidating,
                "swr_stats": self.swr_simulator.get_swr_stats()
            }

    def should_consolidate(self) -> bool:
        """Check if it's time to run consolidation"""
        if self._is_consolidating:
            return False

        if not self._last_consolidation:
            return True

        try:
            last = datetime.fromisoformat(self._last_consolidation)
            elapsed = (datetime.now() - last).total_seconds()
            return elapsed >= self.consolidation_interval
        except (ValueError, TypeError):
            return True
