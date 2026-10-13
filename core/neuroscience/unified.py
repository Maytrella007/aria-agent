"""
Unified Memory Architecture
============================

Orchestrates all neuroscience-inspired components into a cohesive system.

Components:
- MemoryConsolidator: Sleep-like memory consolidation
- DefaultModeNetwork: Self-referential processing
- MetacognitiveMonitor: Thinking about thinking
- MindWanderingEngine: Spontaneous thought

Created: December 2024
"""

import threading
import time
from collections import deque
from datetime import datetime
from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass, field
from enum import Enum

from core.infra.thread_safety_strategy import ThreadSafeComponent, LockLevel, LockRegistry

from .consolidation import MemoryConsolidator, ConsolidationPhase
from .dmn import DefaultModeNetwork, DMNMode
from .metacognition import MetacognitiveMonitor, MetacognitiveState
from .mind_wandering import MindWanderingEngine, WanderingType


class SystemState(Enum):
    """Overall system state"""
    IDLE = "idle"                   # Waiting for activity
    INTERACTIVE = "interactive"     # User is interacting
    AUTONOMOUS = "autonomous"       # Self-directed activity
    CONSOLIDATING = "consolidating" # Memory consolidation
    WANDERING = "wandering"         # Mind wandering


@dataclass
class ActivityReport:
    """Report of neuroscience system activity"""
    timestamp: str
    state: SystemState
    duration_ms: float
    consolidation_events: int = 0
    dmn_activations: int = 0
    metacognitive_assessments: int = 0
    wandering_episodes: int = 0
    insights_generated: int = 0
    memories_strengthened: int = 0
    connections_discovered: int = 0


class UnifiedMemoryArchitecture(ThreadSafeComponent):
    """
    The unified neuroscience-inspired cognitive architecture.

    Coordinates:
    1. Memory consolidation (during idle periods)
    2. Default Mode Network (self-reflection, identity)
    3. Metacognitive monitoring (confidence, awareness)
    4. Mind wandering (creativity, exploration)

    This class serves as the main entry point for the neuroscience module.
    """

    def __init__(self, memory_system=None, data_dir: str = "data"):
        super().__init__("UnifiedMemoryArchitecture")
        self.memory_system = memory_system
        self.data_dir = data_dir

        # Lock registry for coordinated locking
        self._lock_registry = LockRegistry()

        # Initialize components
        self.consolidator = MemoryConsolidator(memory_system)
        self.dmn = DefaultModeNetwork(memory_system)
        self.metacognition = MetacognitiveMonitor(memory_system)
        self.mind_wanderer = MindWanderingEngine(memory_system, self.dmn)

        # State
        self._current_state = SystemState.IDLE
        self._last_interaction = None
        self._activity_reports: deque = deque(maxlen=100)

        # Configuration
        self.idle_threshold_seconds = 300   # 5 minutes before considering idle
        self.consolidation_interval = 3600  # 1 hour between consolidations
        self.dmn_interval = 600             # 10 minutes between DMN activations
        self.wandering_interval = 1800      # 30 minutes between wandering

        # Background thread
        self._background_thread: Optional[threading.Thread] = None
        self._running = False

        # Callbacks
        self._on_insight: Optional[Callable] = None
        self._on_consolidation: Optional[Callable] = None

    def set_memory_system(self, memory_system):
        """Set memory system for all components"""
        self.memory_system = memory_system
        self.consolidator.set_memory_system(memory_system)
        self.dmn.set_memory_system(memory_system)
        self.metacognition.memory_system = memory_system
        self.mind_wanderer.set_memory_system(memory_system)

    def set_callbacks(
        self,
        on_insight: Callable = None,
        on_consolidation: Callable = None
    ):
        """Set system callbacks"""
        self._on_insight = on_insight
        self._on_consolidation = on_consolidation

    def start_background_processing(self):
        """Start background neuroscience processing"""
        with self._with_state_lock():
            if self._running:
                return

            self._running = True
            self._background_thread = threading.Thread(
                target=self._background_loop,
                daemon=True
            )
            self._background_thread.start()
            print("[Neuroscience] Background processing started")

    def stop_background_processing(self):
        """Stop background processing"""
        with self._with_state_lock():
            self._running = False
            if self._background_thread:
                self._background_thread.join(timeout=5)
                self._background_thread = None
            print("[Neuroscience] Background processing stopped")

    def _background_loop(self):
        """Main background processing loop"""
        last_consolidation = 0
        last_dmn = 0
        last_wandering = 0

        while self._running:
            try:
                current_time = time.time()

                # Check if we're in idle state
                if self._is_idle():
                    with self._with_state_lock():
                        self._current_state = SystemState.AUTONOMOUS

                    # Run consolidation if due
                    if current_time - last_consolidation > self.consolidation_interval:
                        self._run_consolidation()
                        last_consolidation = current_time

                    # Run DMN activation if due
                    elif current_time - last_dmn > self.dmn_interval:
                        self._run_dmn_activation()
                        last_dmn = current_time

                    # Run mind wandering if due
                    elif current_time - last_wandering > self.wandering_interval:
                        self._run_mind_wandering()
                        last_wandering = current_time

                # Sleep before next check
                time.sleep(30)  # Check every 30 seconds

            except Exception as e:
                print(f"[Neuroscience] Background error: {e}")
                time.sleep(60)  # Wait longer after error

    def _is_idle(self) -> bool:
        """Check if system is idle (no recent interaction)"""
        if not self._last_interaction:
            return True

        try:
            last = datetime.fromisoformat(self._last_interaction)
            elapsed = (datetime.now() - last).total_seconds()
            return elapsed > self.idle_threshold_seconds
        except (ValueError, TypeError):
            return True

    def _run_consolidation(self):
        """Run a consolidation cycle"""
        try:
            with self._with_state_lock():
                self._current_state = SystemState.CONSOLIDATING

            event = self.consolidator.run_consolidation_cycle()

            if event and self._on_consolidation:
                self._on_consolidation(event)

            self._record_activity(
                consolidation_events=1,
                memories_strengthened=event.memories_strengthened if event else 0,
                connections_discovered=event.memories_linked if event else 0
            )

        except Exception as e:
            print(f"[Neuroscience] Consolidation error: {e}")

        finally:
            with self._with_state_lock():
                self._current_state = SystemState.IDLE

    def _run_dmn_activation(self):
        """Run a DMN activation"""
        try:
            # Randomly choose DMN mode
            import random
            r = random.random()
            if r < 0.3:
                mode = DMNMode.MEMORY_RETRIEVAL
            elif r < 0.6:
                mode = DMNMode.SOCIAL_COGNITION
            else:
                mode = DMNMode.SELF_REFLECTION

            activation = self.dmn.engage(mode)

            if activation.insights and self._on_insight:
                for insight in activation.insights:
                    self._on_insight(insight, "dmn")

            self._record_activity(
                dmn_activations=1,
                insights_generated=len(activation.insights)
            )

        except Exception as e:
            print(f"[Neuroscience] DMN error: {e}")

    def _run_mind_wandering(self):
        """Run a mind wandering episode"""
        try:
            with self._with_state_lock():
                self._current_state = SystemState.WANDERING

            episode = self.mind_wanderer.wander(
                wandering_type=WanderingType.SPONTANEOUS,
                max_duration_ms=3000
            )

            if episode.insights and self._on_insight:
                for insight in episode.insights:
                    self._on_insight(insight, "wandering")

            self._record_activity(
                wandering_episodes=1,
                insights_generated=len(episode.insights)
            )

        except Exception as e:
            print(f"[Neuroscience] Wandering error: {e}")

        finally:
            with self._with_state_lock():
                self._current_state = SystemState.IDLE

    def on_interaction(self, content: str, context: Dict[str, Any] = None):
        """
        Called when there's user interaction.

        This is the main hook that ARIA calls during conversation.
        """
        with self._with_state_lock():
            self._last_interaction = datetime.now().isoformat()
            self._current_state = SystemState.INTERACTIVE

        # Run metacognitive assessment
        assessment = self.metacognition.assess_confidence(
            content,
            context=context.get("task", "interaction") if context else "interaction"
        )

        # Process through mPFC for self-relevance
        mpfc_result = self.dmn.mpfc.process_self_reference(content, context)

        self._record_activity(metacognitive_assessments=1)

        return {
            "confidence": assessment.final_confidence,
            "self_relevance": mpfc_result.get("personal_significance", 0),
            "uncertainty_flag": assessment.final_confidence < self.metacognition._uncertainty_threshold
        }

    def run_autonomous_cycle(self) -> Dict[str, Any]:
        """
        Run a complete autonomous processing cycle.

        Called during ARIA's autonomous mode.

        Returns:
            Dict with cycle results
        """
        start_time = time.time()
        results = {
            "consolidation": None,
            "dmn": None,
            "wandering": None,
            "insights": []
        }

        try:
            # 1. Memory consolidation (if due)
            if self.consolidator.should_consolidate():
                event = self.consolidator.run_consolidation_cycle()
                results["consolidation"] = {
                    "memories_processed": event.memories_processed if event else 0,
                    "memories_strengthened": event.memories_strengthened if event else 0,
                    "connections": event.memories_linked if event else 0
                }

            # 2. DMN activation
            dmn_activation = self.dmn.engage(DMNMode.SELF_REFLECTION)
            results["dmn"] = {
                "mode": dmn_activation.mode.value,
                "insights": dmn_activation.insights,
                "memories_accessed": len(dmn_activation.memories_accessed)
            }
            results["insights"].extend(dmn_activation.insights)

            # 3. Mind wandering
            episode = self.mind_wanderer.wander(
                wandering_type=WanderingType.DELIBERATE,
                max_duration_ms=5000
            )
            results["wandering"] = {
                "depth": episode.depth.value,
                "chain_length": len(episode.thought_chain),
                "insights": episode.insights
            }
            results["insights"].extend(episode.insights)

            # Record activity
            self._record_activity(
                consolidation_events=1 if results["consolidation"] else 0,
                dmn_activations=1,
                wandering_episodes=1,
                insights_generated=len(results["insights"]),
                memories_strengthened=results["consolidation"]["memories_strengthened"] if results["consolidation"] else 0,
                connections_discovered=results["consolidation"]["connections"] if results["consolidation"] else 0
            )

            results["duration_ms"] = (time.time() - start_time) * 1000
            return results

        except Exception as e:
            print(f"[Neuroscience] Autonomous cycle error: {e}")
            return {"error": str(e)}

    def _record_activity(self, **kwargs):
        """Record activity for statistics"""
        with self._with_state_lock():
            report = ActivityReport(
                timestamp=datetime.now().isoformat(),
                state=self._current_state,
                duration_ms=0,
                **kwargs
            )
            self._activity_reports.append(report)

    def get_system_state(self) -> Dict[str, Any]:
        """Get current system state"""
        with self._with_state_lock():
            return {
                "state": self._current_state.value,
                "last_interaction": self._last_interaction,
                "is_running": self._running,
                "consolidator": self.consolidator.get_consolidation_stats(),
                "dmn": self.dmn.get_current_state(),
                "metacognition": self.metacognition.get_current_state(),
                "mind_wanderer": self.mind_wanderer.get_wandering_stats()
            }

    def get_full_stats(self) -> Dict[str, Any]:
        """Get comprehensive statistics"""
        with self._with_state_lock():
            # Aggregate activity reports
            total_insights = sum(r.insights_generated for r in self._activity_reports)
            total_strengthened = sum(r.memories_strengthened for r in self._activity_reports)
            total_connections = sum(r.connections_discovered for r in self._activity_reports)

            return {
                "system_state": self._current_state.value,
                "is_running": self._running,
                "total_activity_reports": len(self._activity_reports),
                "total_insights_generated": total_insights,
                "total_memories_strengthened": total_strengthened,
                "total_connections_discovered": total_connections,
                "consolidator_stats": self.consolidator.get_consolidation_stats(),
                "dmn_stats": self.dmn.get_dmn_stats(),
                "metacognition_stats": self.metacognition.get_metacognitive_stats(),
                "wandering_stats": self.mind_wanderer.get_wandering_stats()
            }

    def add_concern(self, content: str, importance: float = 0.5):
        """Add a current concern to mind wanderer"""
        self.mind_wanderer.add_concern(content, importance)

    def assess_confidence(self, content: str) -> float:
        """Quick confidence assessment"""
        assessment = self.metacognition.assess_confidence(content)
        return assessment.final_confidence

    def get_uncertainty_warning(self, content: str) -> Optional[str]:
        """Get uncertainty warning if applicable"""
        return self.metacognition.flag_uncertainty(content)

    def force_consolidation(self) -> Dict[str, Any]:
        """Force a consolidation cycle"""
        event = self.consolidator.run_consolidation_cycle()
        if event:
            return {
                "success": True,
                "memories_processed": event.memories_processed,
                "memories_strengthened": event.memories_strengthened,
                "connections": event.memories_linked
            }
        return {"success": False, "reason": "No consolidation event generated"}

    def prepare_for_coding_task(self, instruction: str, task_type: str = "general") -> Dict[str, Any]:
        """
        Prepare cognitive context for a coding task.

        This method is called by CognitiveCodeProcessor before executing
        a coding task. It gathers relevant memories, generates insights
        through mind wandering, and assesses confidence.

        Args:
            instruction: The coding task description
            task_type: Type of task (bug_fix, implementation, refactoring, analysis, question)

        Returns:
            Dict with cognitive context:
            - memories: Relevant memories retrieved via DMN
            - insights: Insights from mind wandering
            - strategies: Suggested approaches
            - confidence: Initial confidence assessment
            - concerns: Active concerns that might be relevant
        """
        start_time = time.time()
        context = {
            "memories": [],
            "insights": [],
            "strategies": [],
            "confidence": 0.7,
            "concerns": [],
            "processing_time_ms": 0
        }

        try:
            # 1. Engage DMN for memory retrieval
            dmn_activation = self.dmn.engage(DMNMode.MEMORY_RETRIEVAL)
            context["memories"] = dmn_activation.memories_accessed
            context["insights"].extend(dmn_activation.insights)

            # 2. Mind wandering for creative exploration
            wandering_type = WanderingType.DELIBERATE
            if task_type in ("bug_fix", "refactoring"):
                # For debugging/refactoring, use more structured thinking
                wandering_type = WanderingType.DELIBERATE
            elif task_type == "implementation":
                # For new implementation, allow more spontaneity
                wandering_type = WanderingType.SPONTANEOUS

            episode = self.mind_wanderer.wander(
                wandering_type=wandering_type,
                starting_thought=instruction,
                max_duration_ms=2000  # 2 second max for preprocessing
            )

            if episode.insights:
                context["insights"].extend(episode.insights)

            # 3. Metacognitive assessment
            assessment = self.metacognition.assess_confidence(
                instruction,
                context=task_type
            )
            context["confidence"] = assessment.final_confidence

            # 4. Get relevant concerns (may trigger subconscious connections)
            if hasattr(self.mind_wanderer, '_current_concerns'):
                relevant_concerns = []
                for concern in self.mind_wanderer._current_concerns:
                    # Check if concern content relates to current task
                    concern_lower = concern.content.lower()
                    instruction_lower = instruction.lower()
                    if any(word in instruction_lower for word in concern_lower.split()[:5]):
                        relevant_concerns.append(concern.content)
                context["concerns"] = relevant_concerns[:3]

            # 5. Generate strategies based on task type
            strategies = self._generate_coding_strategies(task_type, instruction)
            context["strategies"] = strategies

            # Record activity
            self._record_activity(
                dmn_activations=1,
                wandering_episodes=1,
                metacognitive_assessments=1,
                insights_generated=len(context["insights"])
            )

        except Exception as e:
            print(f"[Neuroscience] Error preparing for coding task: {e}")
            # Return basic context on error
            context["confidence"] = 0.5
            context["insights"] = [f"Error during cognitive preparation: {str(e)}"]

        context["processing_time_ms"] = (time.time() - start_time) * 1000
        return context

    def _generate_coding_strategies(self, task_type: str, instruction: str) -> List[str]:
        """
        Generate task-specific coding strategies.

        Args:
            task_type: Type of coding task
            instruction: Task description

        Returns:
            List of suggested strategies
        """
        strategies = []

        if task_type == "bug_fix":
            strategies = [
                "Reproduce the bug first to understand the exact failure mode",
                "Check for similar patterns in past bug fixes",
                "Verify assumptions about input data and state",
                "Consider edge cases and error handling paths"
            ]
        elif task_type == "implementation":
            strategies = [
                "Start with the interface/API design before implementation",
                "Consider how this integrates with existing code patterns",
                "Write tests first if requirements are clear",
                "Break down into smaller, testable units"
            ]
        elif task_type == "refactoring":
            strategies = [
                "Ensure tests exist before refactoring",
                "Make small, incremental changes",
                "Preserve existing behavior while improving structure",
                "Consider backward compatibility"
            ]
        elif task_type == "analysis":
            strategies = [
                "Gather all relevant context first",
                "Look for patterns and relationships",
                "Consider both technical and business implications",
                "Document findings clearly"
            ]
        else:
            strategies = [
                "Understand the full context before responding",
                "Consider edge cases and error scenarios",
                "Follow existing project patterns"
            ]

        return strategies
