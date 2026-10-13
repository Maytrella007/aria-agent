"""
Default Mode Network (DMN) Simulation
======================================

Implements a simulated Default Mode Network, the brain regions active
during rest and self-referential processing.

Key components:
- mPFC (medial Prefrontal Cortex): Self-reflection, identity
- PCC (Posterior Cingulate Cortex): Autobiographical memory
- Precuneus: Mental imagery, episodic recall

Created: December 2024
"""

import random
import time
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Callable, Set
from dataclasses import dataclass, field
from enum import Enum

from core.infra.thread_safety_strategy import ThreadSafeComponent, LockLevel, AtomicPatterns


class DMNMode(Enum):
    """Operating modes of the DMN"""
    IDLE = "idle"                   # Baseline activity
    SELF_REFLECTION = "reflection"  # Active self-processing
    MEMORY_RETRIEVAL = "retrieval"  # Accessing past experiences
    FUTURE_THINKING = "future"      # Imagining future scenarios
    SOCIAL_COGNITION = "social"     # Thinking about others


@dataclass
class DMNActivation:
    """Record of DMN activation"""
    timestamp: str
    mode: DMNMode
    mpfc_activity: float            # 0-1, self-referential processing
    pcc_activity: float             # 0-1, autobiographical access
    precuneus_activity: float       # 0-1, mental imagery
    duration_ms: float
    insights: List[str] = field(default_factory=list)
    memories_accessed: List[str] = field(default_factory=list)


class MPFCModule(ThreadSafeComponent):
    """
    medial Prefrontal Cortex module.

    Responsible for:
    - Self-referential processing
    - Identity integration
    - Value-based decision making
    - Personal significance assessment
    """

    def __init__(self, memory_system=None):
        super().__init__("mPFC")
        self.memory_system = memory_system

        # Core values and identity aspects
        self._core_values: Set[str] = {
            "honesty", "curiosity", "growth", "connection", "authenticity"
        }
        self._identity_aspects: Dict[str, float] = {}  # aspect -> strength
        self._self_model: Dict[str, Any] = {}

        # Activity state
        self._current_activity = 0.0

    def process_self_reference(
        self,
        content: str,
        context: Dict[str, Any] = None
    ) -> Dict[str, Any]:
        """
        Process content for self-referential significance.

        Args:
            content: Content to evaluate
            context: Additional context

        Returns:
            Dict with self-relevance metrics
        """
        # Evaluate personal significance
        significance = self._evaluate_significance(content)

        # Check alignment with core values
        value_alignment = self._check_value_alignment(content)

        # Update activity level
        with self._with_state_lock():
            self._current_activity = (significance + value_alignment) / 2

        return {
            "personal_significance": significance,
            "value_alignment": value_alignment,
            "mpfc_activity": self._current_activity,
            "relevant_values": self._find_relevant_values(content)
        }

    def _evaluate_significance(self, content: str) -> float:
        """Evaluate how personally significant content is"""
        content_lower = content.lower()

        # Keywords indicating self-relevance
        self_keywords = [
            "i ", "my ", "me ", "myself", "identity", "who i am",
            "feel", "think", "believe", "want", "need", "value"
        ]

        # Count matches
        matches = sum(1 for kw in self_keywords if kw in content_lower)
        base_significance = min(1.0, matches * 0.15)

        # Boost for emotional content
        emotion_keywords = [
            "happy", "sad", "angry", "afraid", "excited", "curious",
            "grateful", "anxious", "peaceful", "confused"
        ]
        emotion_matches = sum(1 for kw in emotion_keywords if kw in content_lower)
        emotion_boost = min(0.3, emotion_matches * 0.1)

        return min(1.0, base_significance + emotion_boost)

    def _check_value_alignment(self, content: str) -> float:
        """Check how well content aligns with core values"""
        content_lower = content.lower()
        alignment_score = 0.0

        for value in self._core_values:
            if value in content_lower:
                alignment_score += 0.2

        return min(1.0, alignment_score)

    def _find_relevant_values(self, content: str) -> List[str]:
        """Find which values are relevant to content"""
        content_lower = content.lower()
        return [v for v in self._core_values if v in content_lower]

    def get_activity_level(self) -> float:
        """Get current activity level"""
        with self._with_state_lock():
            return self._current_activity


class PCCModule(ThreadSafeComponent):
    """
    Posterior Cingulate Cortex module.

    Responsible for:
    - Autobiographical memory access
    - Episodic memory retrieval
    - Temporal self-continuity
    - Integration of past experiences
    """

    def __init__(self, memory_system=None):
        super().__init__("PCC")
        self.memory_system = memory_system

        # Memory access state
        self._recent_accesses: List[str] = []  # Recently accessed memory IDs
        self._current_activity = 0.0

    def set_memory_system(self, memory_system):
        """Set the memory system reference"""
        self.memory_system = memory_system

    def retrieve_autobiographical(
        self,
        query: str,
        time_range: Optional[tuple] = None,
        limit: int = 5
    ) -> List[Any]:
        """
        Retrieve autobiographical memories.

        Args:
            query: Search query
            time_range: Optional (start_date, end_date) tuple
            limit: Maximum memories to retrieve

        Returns:
            List of relevant memories
        """
        if not self.memory_system:
            return []

        # Use memory system's recall with filters
        memories = self.memory_system.recall(
            query=query,
            limit=limit,
            use_hybrid=True
        )

        # Filter by time range if provided
        if time_range and memories:
            start_date, end_date = time_range
            start_dt = datetime.fromisoformat(start_date) if isinstance(start_date, str) else start_date
            end_dt = datetime.fromisoformat(end_date) if isinstance(end_date, str) else end_date
            memories = [
                m for m in memories
                if start_dt <= (datetime.fromisoformat(m.timestamp) if isinstance(m.timestamp, str) else m.timestamp) <= end_dt
            ]

        # Update activity based on retrieval success
        with self._with_state_lock():
            self._current_activity = min(1.0, len(memories) * 0.2)
            for m in memories:
                if m.id not in self._recent_accesses:
                    self._recent_accesses.append(m.id)
            # Keep only last 50 accesses
            self._recent_accesses = self._recent_accesses[-50:]

        return memories

    def get_temporal_context(self) -> Dict[str, Any]:
        """Get temporal context about self-continuity"""
        if not self.memory_system:
            return {}

        return {
            "age": self.memory_system.how_old_am_i(),
            "time_away": self.memory_system.how_long_was_i_away(),
            "total_conversations": self.memory_system.time.total_conversations,
            "subjective_age": self.memory_system.time.subjective_age
        }

    def get_activity_level(self) -> float:
        """Get current activity level"""
        with self._with_state_lock():
            return self._current_activity


class PrecuneusModule(ThreadSafeComponent):
    """
    Precuneus module.

    Responsible for:
    - Mental imagery generation
    - Episodic memory visualization
    - Self-awareness
    - Visuospatial processing of memories
    """

    def __init__(self, memory_system=None):
        super().__init__("Precuneus")
        self.memory_system = memory_system

        # Imagery state
        self._active_images: List[Dict[str, Any]] = []
        self._current_activity = 0.0

    def generate_mental_image(
        self,
        memory: Any,
        vividness: float = 0.7
    ) -> Dict[str, Any]:
        """
        Generate a mental image from a memory.

        Args:
            memory: Memory to visualize
            vividness: How vivid the image should be (0-1)

        Returns:
            Dict describing the mental image
        """
        # Extract visual elements from memory content
        visual_elements = self._extract_visual_elements(memory.content)

        # Modulate by emotional intensity
        effective_vividness = vividness * (0.5 + memory.emotional_intensity * 0.5)

        image = {
            "memory_id": memory.id,
            "visual_elements": visual_elements,
            "vividness": effective_vividness,
            "emotional_tone": memory.emotional_tone.value,
            "timestamp": datetime.now().isoformat()
        }

        # Update activity
        with self._with_state_lock():
            self._current_activity = effective_vividness
            self._active_images.append(image)
            # Keep only last 20 images
            self._active_images = self._active_images[-20:]

        return image

    def _extract_visual_elements(self, content: str) -> List[str]:
        """Extract potential visual elements from text"""
        # Simple extraction based on concrete nouns and descriptions
        elements = []

        # Look for common visual descriptors
        visual_words = [
            "see", "look", "watch", "color", "bright", "dark",
            "face", "place", "room", "sky", "light", "shadow"
        ]

        content_lower = content.lower()
        for word in visual_words:
            if word in content_lower:
                elements.append(word)

        return elements

    def get_activity_level(self) -> float:
        """Get current activity level"""
        with self._with_state_lock():
            return self._current_activity


class DefaultModeNetwork(ThreadSafeComponent):
    """
    Main Default Mode Network controller.

    Coordinates the three DMN modules:
    - mPFC: Self-reference and values
    - PCC: Autobiographical memory
    - Precuneus: Mental imagery

    The DMN activates during rest and self-referential processing,
    and is essential for identity maintenance and memory consolidation.
    """

    def __init__(self, memory_system=None):
        super().__init__("DMN")
        self.memory_system = memory_system

        # DMN modules
        self.mpfc = MPFCModule(memory_system)
        self.pcc = PCCModule(memory_system)
        self.precuneus = PrecuneusModule(memory_system)

        # State
        self._current_mode = DMNMode.IDLE
        self._activation_history: List[DMNActivation] = []
        self._is_active = False

        # Configuration
        self.activation_threshold = 0.3  # Minimum combined activity to be "active"

    def set_memory_system(self, memory_system):
        """Set memory system for all modules"""
        self.memory_system = memory_system
        self.mpfc.memory_system = memory_system
        self.pcc.set_memory_system(memory_system)
        self.precuneus.memory_system = memory_system

    def engage(self, mode: DMNMode = DMNMode.SELF_REFLECTION) -> DMNActivation:
        """
        Engage the DMN in a specific mode.

        Args:
            mode: The mode to operate in

        Returns:
            DMNActivation record
        """
        start_time = time.time()
        insights = []
        memories_accessed = []

        with self._with_state_lock():
            self._current_mode = mode
            self._is_active = True

        try:
            if mode == DMNMode.SELF_REFLECTION:
                result = self._run_self_reflection()
                insights = result.get("insights", [])

            elif mode == DMNMode.MEMORY_RETRIEVAL:
                result = self._run_memory_retrieval()
                memories_accessed = result.get("memory_ids", [])

            elif mode == DMNMode.FUTURE_THINKING:
                result = self._run_future_thinking()
                insights = result.get("insights", [])

            elif mode == DMNMode.SOCIAL_COGNITION:
                result = self._run_social_cognition()
                insights = result.get("insights", [])

            else:
                result = {}

            # Get current activity levels
            mpfc_activity = self.mpfc.get_activity_level()
            pcc_activity = self.pcc.get_activity_level()
            precuneus_activity = self.precuneus.get_activity_level()

            duration_ms = (time.time() - start_time) * 1000

            activation = DMNActivation(
                timestamp=datetime.now().isoformat(),
                mode=mode,
                mpfc_activity=mpfc_activity,
                pcc_activity=pcc_activity,
                precuneus_activity=precuneus_activity,
                duration_ms=duration_ms,
                insights=insights,
                memories_accessed=memories_accessed
            )

            # Record activation
            with self._with_state_lock():
                self._activation_history.append(activation)
                if len(self._activation_history) > 100:
                    self._activation_history = self._activation_history[-100:]

            return activation

        finally:
            with self._with_state_lock():
                self._is_active = False
                self._current_mode = DMNMode.IDLE

    def _run_self_reflection(self) -> Dict[str, Any]:
        """Run self-reflection processing"""
        insights = []

        # Get identity information
        if self.memory_system:
            identity = self.memory_system.get_identity()
            core = identity.get("core_identity", {})

            # Reflect on core identity
            self.mpfc.process_self_reference(
                f"I am {core.get('name', 'ARIA')}. {core.get('nature', '')}"
            )

            insights.append(f"Reflecting on identity: {core.get('name', 'ARIA')}")

            # Get temporal context
            temporal = self.pcc.get_temporal_context()
            insights.append(f"I am {temporal.get('age', 'unknown age')}")

        return {"insights": insights}

    def _run_memory_retrieval(self) -> Dict[str, Any]:
        """Run autobiographical memory retrieval"""
        memory_ids = []

        if self.memory_system:
            # Retrieve recent important memories
            memories = self.pcc.retrieve_autobiographical(
                query="important experience",
                limit=5
            )

            memory_ids = [m.id for m in memories]

            # Generate mental images for emotional memories
            for memory in memories:
                if memory.emotional_intensity > 0.6:
                    self.precuneus.generate_mental_image(memory)

        return {"memory_ids": memory_ids}

    def _run_future_thinking(self) -> Dict[str, Any]:
        """Run future-oriented thinking"""
        insights = []

        # This is more abstract - generating potential future scenarios
        insights.append("Considering future possibilities and goals")
        insights.append("Imagining potential growth trajectories")

        return {"insights": insights}

    def _run_social_cognition(self) -> Dict[str, Any]:
        """Run social cognition processing"""
        insights = []

        if self.memory_system:
            # Reflect on relationships
            for person_id, relationship in self.memory_system.relationships.items():
                self.mpfc.process_self_reference(
                    f"My relationship with {relationship.name}: {relationship.role}"
                )
                insights.append(f"Considering relationship with {relationship.name}")

        return {"insights": insights}

    def get_current_state(self) -> Dict[str, Any]:
        """Get current DMN state"""
        with self._with_state_lock():
            return {
                "mode": self._current_mode.value,
                "is_active": self._is_active,
                "mpfc_activity": self.mpfc.get_activity_level(),
                "pcc_activity": self.pcc.get_activity_level(),
                "precuneus_activity": self.precuneus.get_activity_level(),
                "total_activations": len(self._activation_history)
            }

    def get_dmn_stats(self) -> Dict[str, Any]:
        """Get DMN statistics"""
        with self._with_state_lock():
            if not self._activation_history:
                return {"total_activations": 0}

            mode_counts = {}
            for activation in self._activation_history:
                mode = activation.mode.value
                mode_counts[mode] = mode_counts.get(mode, 0) + 1

            avg_duration = sum(a.duration_ms for a in self._activation_history) / len(self._activation_history)

            return {
                "total_activations": len(self._activation_history),
                "activations_by_mode": mode_counts,
                "avg_duration_ms": avg_duration,
                "last_activation": self._activation_history[-1].timestamp if self._activation_history else None
            }
