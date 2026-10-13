"""
Metacognitive Monitoring System
================================

Implements metacognition - "thinking about thinking".

Key capabilities:
- Confidence monitoring
- Error detection
- Learning assessment
- Strategic regulation

Created: December 2024
"""

import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Deque
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from core.infra.thread_safety_strategy import ThreadSafeComponent, AtomicPatterns


class ConfidenceLevel(Enum):
    """Levels of confidence in responses/decisions"""
    VERY_LOW = 0.1
    LOW = 0.3
    MODERATE = 0.5
    HIGH = 0.7
    VERY_HIGH = 0.9


class MetacognitiveState(Enum):
    """States of metacognitive processing"""
    MONITORING = "monitoring"       # Observing own cognitive processes
    EVALUATING = "evaluating"       # Assessing performance
    REGULATING = "regulating"       # Adjusting strategies
    REFLECTING = "reflecting"       # Deep self-reflection


@dataclass
class ConfidenceAssessment:
    """Assessment of confidence in a response or decision"""
    timestamp: str
    context: str                    # What was being assessed
    initial_confidence: float       # Initial confidence (0-1)
    final_confidence: float         # After metacognitive adjustment
    factors: Dict[str, float]       # Factors affecting confidence
    adjustment_reason: str          # Why confidence was adjusted


@dataclass
class MetacognitiveEvent:
    """Record of a metacognitive process"""
    timestamp: str
    state: MetacognitiveState
    insight: str
    confidence_before: float
    confidence_after: float
    duration_ms: float


class MetacognitiveMonitor(ThreadSafeComponent):
    """
    Metacognitive monitoring system.

    Monitors and regulates cognitive processes:
    - Tracks confidence in responses
    - Detects potential errors or uncertainty
    - Suggests when to seek more information
    - Maintains awareness of cognitive limitations
    """

    def __init__(self, memory_system=None):
        super().__init__("MetacognitiveMonitor")
        self.memory_system = memory_system

        # Confidence history (bounded deque for thread safety)
        self._confidence_history: Deque[ConfidenceAssessment] = deque(maxlen=100)
        self._metacognitive_events: Deque[MetacognitiveEvent] = deque(maxlen=100)

        # Current state
        self._current_confidence = 0.7
        self._current_state = MetacognitiveState.MONITORING
        self._uncertainty_threshold = 0.4  # Below this, flag uncertainty

        # Known limitations and biases
        self._known_limitations = [
            "Cannot access real-time information without tools",
            "May have knowledge gaps after training cutoff",
            "Cannot verify claims without external sources",
            "May exhibit training biases",
            "Cannot guarantee factual accuracy for complex topics"
        ]

        # Cognitive strategies
        self._active_strategies: List[str] = []

    def assess_confidence(
        self,
        content: str,
        context: str = "",
        factors: Dict[str, float] = None
    ) -> ConfidenceAssessment:
        """
        Assess confidence in a response or decision.

        Args:
            content: The content being assessed
            context: Context of the assessment
            factors: Specific factors affecting confidence

        Returns:
            ConfidenceAssessment with analysis
        """
        factors = factors or {}

        # Calculate initial confidence based on content analysis
        initial_confidence = self._calculate_initial_confidence(content, factors)

        # Apply metacognitive adjustments
        final_confidence, adjustment_reason = self._apply_adjustments(
            initial_confidence, content, factors
        )

        assessment = ConfidenceAssessment(
            timestamp=datetime.now().isoformat(),
            context=context,
            initial_confidence=initial_confidence,
            final_confidence=final_confidence,
            factors=factors,
            adjustment_reason=adjustment_reason
        )

        # Update state (thread-safe with bounded deque)
        with self._with_state_lock():
            self._confidence_history.append(assessment)
            self._current_confidence = final_confidence

        return assessment

    def _calculate_initial_confidence(
        self,
        content: str,
        factors: Dict[str, float]
    ) -> float:
        """Calculate initial confidence before adjustments"""
        base_confidence = 0.7  # Default baseline

        # Adjust based on provided factors
        if factors:
            factor_sum = sum(factors.values()) / len(factors)
            base_confidence = 0.5 + (factor_sum * 0.4)

        # Check for uncertainty markers in content
        uncertainty_markers = [
            "might", "maybe", "perhaps", "could be", "possibly",
            "i think", "i believe", "not sure", "uncertain",
            "it seems", "appears to"
        ]

        content_lower = content.lower()
        uncertainty_count = sum(
            1 for marker in uncertainty_markers if marker in content_lower
        )

        # Each uncertainty marker reduces confidence
        uncertainty_penalty = min(0.3, uncertainty_count * 0.05)
        base_confidence -= uncertainty_penalty

        # Check for certainty markers
        certainty_markers = [
            "definitely", "certainly", "absolutely", "clearly",
            "without doubt", "for certain", "i know"
        ]

        certainty_count = sum(
            1 for marker in certainty_markers if marker in content_lower
        )

        # Certainty markers slightly increase confidence
        certainty_bonus = min(0.15, certainty_count * 0.05)
        base_confidence += certainty_bonus

        return max(0.1, min(1.0, base_confidence))

    def _apply_adjustments(
        self,
        initial_confidence: float,
        content: str,
        factors: Dict[str, float]
    ) -> tuple:
        """Apply metacognitive adjustments to confidence"""
        adjusted = initial_confidence
        reasons = []

        # Check for known limitations
        content_lower = content.lower()

        # Reduce confidence for topics touching known limitations
        if any(word in content_lower for word in ["latest", "current", "today", "news", "recent"]):
            adjusted -= 0.15
            reasons.append("temporal uncertainty (may not have current info)")

        if any(word in content_lower for word in ["fact", "statistic", "number", "data"]):
            adjusted -= 0.1
            reasons.append("factual claim (cannot verify)")

        # Boost confidence for self-referential content
        if any(word in content_lower for word in ["i feel", "i think", "my perspective"]):
            adjusted += 0.1
            reasons.append("self-referential (high certainty about own states)")

        # Apply memory-based adjustment if memory system available
        if self.memory_system and factors.get("memory_supported"):
            adjusted += 0.1
            reasons.append("memory-supported claim")

        # Ensure bounds
        adjusted = max(0.1, min(1.0, adjusted))

        adjustment_reason = "; ".join(reasons) if reasons else "no adjustment needed"
        return adjusted, adjustment_reason

    def flag_uncertainty(self, content: str) -> Optional[str]:
        """
        Check if content should be flagged for uncertainty.

        Returns:
            Warning message if uncertainty detected, None otherwise
        """
        assessment = self.assess_confidence(content)

        if assessment.final_confidence < self._uncertainty_threshold:
            return (
                f"Uncertainty detected (confidence: {assessment.final_confidence:.2f}). "
                f"Reason: {assessment.adjustment_reason}"
            )

        return None

    def suggest_strategy(self, task_type: str) -> List[str]:
        """
        Suggest cognitive strategies for a task type.

        Args:
            task_type: Type of task (e.g., "problem_solving", "recall", "creative")

        Returns:
            List of suggested strategies
        """
        strategies = {
            "problem_solving": [
                "Break problem into smaller parts",
                "Consider multiple approaches",
                "Check assumptions",
                "Verify solution step by step"
            ],
            "recall": [
                "Search memory systematically",
                "Use context cues",
                "Consider related memories",
                "Acknowledge uncertainty if memory is unclear"
            ],
            "creative": [
                "Explore unconventional combinations",
                "Suspend judgment initially",
                "Build on existing ideas",
                "Consider multiple perspectives"
            ],
            "analysis": [
                "Gather all relevant information",
                "Identify key variables",
                "Look for patterns",
                "Consider alternative explanations"
            ],
            "communication": [
                "Consider audience perspective",
                "Be clear and concise",
                "Check for potential misunderstandings",
                "Adjust tone appropriately"
            ]
        }

        return strategies.get(task_type, [
            "Approach systematically",
            "Monitor progress",
            "Adjust as needed"
        ])

    def get_known_limitations(self) -> List[str]:
        """Get list of known cognitive limitations"""
        return self._known_limitations.copy()

    def record_event(
        self,
        state: MetacognitiveState,
        insight: str,
        confidence_change: float = 0.0
    ):
        """
        Record a metacognitive event.

        Args:
            state: The metacognitive state during the event
            insight: The insight or observation
            confidence_change: Change in confidence (+/-)
        """
        with self._with_state_lock():
            old_confidence = self._current_confidence
            new_confidence = max(0.1, min(1.0, old_confidence + confidence_change))
            self._current_confidence = new_confidence

            event = MetacognitiveEvent(
                timestamp=datetime.now().isoformat(),
                state=state,
                insight=insight,
                confidence_before=old_confidence,
                confidence_after=new_confidence,
                duration_ms=0  # Can be updated later
            )
            self._metacognitive_events.append(event)

    def get_current_state(self) -> Dict[str, Any]:
        """Get current metacognitive state"""
        with self._with_state_lock():
            return {
                "state": self._current_state.value,
                "current_confidence": self._current_confidence,
                "uncertainty_threshold": self._uncertainty_threshold,
                "active_strategies": self._active_strategies.copy(),
                "recent_assessments": len(self._confidence_history)
            }

    def get_metacognitive_stats(self) -> Dict[str, Any]:
        """Get metacognitive statistics"""
        with self._with_state_lock():
            if not self._confidence_history:
                return {"total_assessments": 0}

            confidences = [a.final_confidence for a in self._confidence_history]
            avg_confidence = sum(confidences) / len(confidences)

            low_confidence_count = sum(1 for c in confidences if c < self._uncertainty_threshold)

            return {
                "total_assessments": len(self._confidence_history),
                "total_events": len(self._metacognitive_events),
                "average_confidence": avg_confidence,
                "current_confidence": self._current_confidence,
                "low_confidence_assessments": low_confidence_count,
                "uncertainty_rate": low_confidence_count / len(confidences) if confidences else 0
            }

    def calibrate(self, feedback: Dict[str, Any]):
        """
        Calibrate metacognitive system based on feedback.

        Args:
            feedback: Dict containing accuracy feedback
        """
        if "was_accurate" in feedback:
            with self._with_state_lock():
                if feedback["was_accurate"]:
                    # Confidence was appropriate or too low
                    self._uncertainty_threshold = max(0.2, self._uncertainty_threshold - 0.02)
                else:
                    # Overconfidence detected, raise threshold
                    self._uncertainty_threshold = min(0.6, self._uncertainty_threshold + 0.05)
