"""
Unit tests for ARIA's neuroscience module
==========================================

Tests for consolidation, DMN, metacognition, mind_wandering, and unified modules.
Uses MockMemorySystem and MockExperientialMemory from conftest.py.
Does NOT duplicate _find_connections tests from test_swr_connections.py.

Created: April 2026
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
from typing import List, Optional


# =============================================================================
# CONSOLIDATION TESTS
# =============================================================================

class TestConsolidationEnumsAndDataclasses:
    """Tests for ConsolidationPhase enum and dataclass construction."""

    def test_consolidation_phase_enum_values(self):
        """ConsolidationPhase enum has all expected members."""
        from core.neuroscience.consolidation import ConsolidationPhase

        assert ConsolidationPhase.ENCODING.value == "encoding"
        assert ConsolidationPhase.EARLY_CONSOLIDATION.value == "early"
        assert ConsolidationPhase.SWR_REPLAY.value == "swr_replay"
        assert ConsolidationPhase.INTEGRATION.value == "integration"
        assert ConsolidationPhase.STABILIZATION.value == "stabilization"
        assert len(ConsolidationPhase) == 5

    def test_consolidation_event_construction(self):
        """ConsolidationEvent dataclass constructs correctly."""
        from core.neuroscience.consolidation import ConsolidationEvent, ConsolidationPhase

        event = ConsolidationEvent(
            timestamp="2026-04-13T12:00:00",
            phase=ConsolidationPhase.INTEGRATION,
            memories_processed=10,
            memories_strengthened=5,
            memories_linked=3,
            duration_ms=150.0,
            metadata={"test": True}
        )
        assert event.memories_processed == 10
        assert event.memories_strengthened == 5
        assert event.memories_linked == 3
        assert event.phase == ConsolidationPhase.INTEGRATION
        assert event.metadata == {"test": True}

    def test_swr_event_construction(self):
        """SWREvent dataclass constructs correctly with defaults."""
        from core.neuroscience.consolidation import SWREvent

        event = SWREvent(
            timestamp="2026-04-13T12:00:00",
            memory_ids=["m1", "m2"],
            replay_strength=0.8,
            new_connections=[("m1", "m2", 0.5)],
            duration_ms=100.0
        )
        assert event.memory_ids == ["m1", "m2"]
        assert event.replay_strength == 0.8
        assert len(event.new_connections) == 1


class TestWeightedSample:
    """Tests for SharpWaveRippleSimulator._weighted_sample()."""

    def setup_method(self):
        from core.neuroscience.consolidation import SharpWaveRippleSimulator
        self.swr = SharpWaveRippleSimulator()

    def test_returns_correct_number_of_items(self):
        """_weighted_sample returns exactly k items when population is large enough."""
        result = self.swr._weighted_sample(range(10), [0.1] * 10, 3)
        assert len(result) == 3

    def test_returns_fewer_when_population_small(self):
        """_weighted_sample returns min(k, len(population)) items."""
        result = self.swr._weighted_sample(range(2), [0.5, 0.5], 5)
        assert len(result) == 2

    def test_handles_zero_weights(self):
        """_weighted_sample handles all-zero weights without error."""
        result = self.swr._weighted_sample(range(5), [0.0] * 5, 3)
        assert len(result) == 3
        # All indices should be valid
        for idx in result:
            assert 0 <= idx < 5

    def test_no_duplicates(self):
        """_weighted_sample returns unique indices (sampling without replacement)."""
        result = self.swr._weighted_sample(range(5), [0.2] * 5, 5)
        assert len(result) == len(set(result))


class TestMemoryConsolidator:
    """Tests for MemoryConsolidator.should_consolidate() and get_consolidation_stats()."""

    def setup_method(self):
        from core.neuroscience.consolidation import MemoryConsolidator
        self.consolidator = MemoryConsolidator()

    def test_should_consolidate_true_initially(self):
        """should_consolidate returns True when no consolidation has occurred."""
        assert self.consolidator.should_consolidate() is True

    def test_should_consolidate_false_after_recent(self):
        """should_consolidate returns False right after consolidation timestamp is set."""
        self.consolidator._last_consolidation = datetime.now().isoformat()
        assert self.consolidator.should_consolidate() is False

    def test_should_consolidate_respects_interval(self):
        """should_consolidate returns True after the interval has elapsed."""
        past = datetime.now() - timedelta(seconds=self.consolidator.consolidation_interval + 1)
        self.consolidator._last_consolidation = past.isoformat()
        assert self.consolidator.should_consolidate() is True

    def test_get_consolidation_stats_structure(self):
        """get_consolidation_stats returns dict with expected keys."""
        stats = self.consolidator.get_consolidation_stats()
        expected_keys = {
            "total_consolidation_cycles",
            "total_memories_processed",
            "total_memories_strengthened",
            "total_connections_created",
            "last_consolidation",
            "is_consolidating",
            "swr_stats",
        }
        assert expected_keys.issubset(stats.keys())
        assert stats["total_consolidation_cycles"] == 0
        assert stats["is_consolidating"] is False


# =============================================================================
# DMN TESTS
# =============================================================================

class TestDMNModeEnum:
    """Tests for DMNMode enum."""

    def test_dmn_mode_values(self):
        from core.neuroscience.dmn import DMNMode

        assert DMNMode.IDLE.value == "idle"
        assert DMNMode.SELF_REFLECTION.value == "reflection"
        assert DMNMode.MEMORY_RETRIEVAL.value == "retrieval"
        assert DMNMode.FUTURE_THINKING.value == "future"
        assert DMNMode.SOCIAL_COGNITION.value == "social"
        assert len(DMNMode) == 5


class TestMPFCModule:
    """Tests for MPFCModule._evaluate_significance() and _check_value_alignment()."""

    def setup_method(self):
        from core.neuroscience.dmn import MPFCModule
        self.mpfc = MPFCModule()

    def test_evaluate_significance_high_self_referential(self):
        """Content with self-referential keywords scores higher significance."""
        score = self.mpfc._evaluate_significance(
            "I think about myself and what I believe and feel"
        )
        # Multiple self-keywords: "i ", "myself", "i " (in "i believe"), "feel", "think", "believe"
        assert score > 0.3

    def test_evaluate_significance_low_for_neutral(self):
        """Content without self-referential or emotional keywords scores low."""
        score = self.mpfc._evaluate_significance(
            "The weather forecast says rain tomorrow"
        )
        assert score < 0.2

    def test_evaluate_significance_emotional_boost(self):
        """Content with emotional keywords gets a boost."""
        base_score = self.mpfc._evaluate_significance("A simple statement")
        emotional_score = self.mpfc._evaluate_significance(
            "A simple statement that makes me happy and excited"
        )
        assert emotional_score > base_score

    def test_check_value_alignment_with_values(self):
        """Content mentioning core values scores higher."""
        score = self.mpfc._check_value_alignment(
            "I value honesty and curiosity in all things"
        )
        # "honesty" and "curiosity" are core values, each adds 0.2
        assert score >= 0.4

    def test_check_value_alignment_no_values(self):
        """Content without core values scores zero."""
        score = self.mpfc._check_value_alignment(
            "The database query returned 42 rows"
        )
        assert score == 0.0


class TestPrecuneusModule:
    """Tests for PrecuneusModule._extract_visual_elements()."""

    def setup_method(self):
        from core.neuroscience.dmn import PrecuneusModule
        self.precuneus = PrecuneusModule()

    def test_extract_visual_elements_finds_keywords(self):
        """Extracts visual keywords from text."""
        elements = self.precuneus._extract_visual_elements(
            "I can see the bright light in the dark room"
        )
        assert "see" in elements
        assert "bright" in elements
        assert "light" in elements
        assert "dark" in elements
        assert "room" in elements

    def test_extract_visual_elements_empty_for_abstract(self):
        """Returns empty list for abstract content without visual words."""
        elements = self.precuneus._extract_visual_elements(
            "The algorithm complexity is polynomial"
        )
        assert elements == []


class TestDefaultModeNetwork:
    """Tests for DefaultModeNetwork.get_current_state()."""

    def test_get_current_state_structure(self):
        """get_current_state returns dict with expected keys and defaults."""
        from core.neuroscience.dmn import DefaultModeNetwork

        dmn = DefaultModeNetwork()
        state = dmn.get_current_state()

        assert "mode" in state
        assert "is_active" in state
        assert "mpfc_activity" in state
        assert "pcc_activity" in state
        assert "precuneus_activity" in state
        assert "total_activations" in state
        assert state["mode"] == "idle"
        assert state["is_active"] is False
        assert state["total_activations"] == 0


# =============================================================================
# METACOGNITION TESTS
# =============================================================================

class TestConfidenceLevelEnum:
    """Tests for ConfidenceLevel enum."""

    def test_confidence_level_values(self):
        from core.neuroscience.metacognition import ConfidenceLevel

        assert ConfidenceLevel.VERY_LOW.value == 0.1
        assert ConfidenceLevel.LOW.value == 0.3
        assert ConfidenceLevel.MODERATE.value == 0.5
        assert ConfidenceLevel.HIGH.value == 0.7
        assert ConfidenceLevel.VERY_HIGH.value == 0.9

    def test_confidence_level_ordering(self):
        """Enum values increase monotonically."""
        from core.neuroscience.metacognition import ConfidenceLevel

        levels = [
            ConfidenceLevel.VERY_LOW,
            ConfidenceLevel.LOW,
            ConfidenceLevel.MODERATE,
            ConfidenceLevel.HIGH,
            ConfidenceLevel.VERY_HIGH,
        ]
        for i in range(len(levels) - 1):
            assert levels[i].value < levels[i + 1].value


class TestMetacognitiveMonitor:
    """Tests for MetacognitiveMonitor methods."""

    def setup_method(self):
        from core.neuroscience.metacognition import MetacognitiveMonitor
        self.monitor = MetacognitiveMonitor()

    def test_assess_confidence_high_for_clear_statement(self):
        """Clear, definite statements yield higher confidence."""
        assessment = self.monitor.assess_confidence(
            "I definitely know that Python is a programming language"
        )
        assert assessment.final_confidence >= 0.6

    def test_assess_confidence_lower_for_hedging(self):
        """Hedging language lowers confidence."""
        clear = self.monitor.assess_confidence("This is a fact")
        hedged = self.monitor.assess_confidence(
            "Maybe I think this could possibly be uncertain, perhaps not sure"
        )
        assert hedged.final_confidence < clear.final_confidence

    def test_flag_uncertainty_returns_warning_below_threshold(self):
        """flag_uncertainty returns a warning string for low-confidence content."""
        # Content with many uncertainty markers + temporal uncertainty
        warning = self.monitor.flag_uncertainty(
            "Maybe I think perhaps the latest current news might possibly not be certain"
        )
        assert warning is not None
        assert "Uncertainty detected" in warning

    def test_flag_uncertainty_returns_none_above_threshold(self):
        """flag_uncertainty returns None for confident content."""
        result = self.monitor.flag_uncertainty(
            "I definitely know this for certain"
        )
        # High certainty content should not trigger warning
        assert result is None

    def test_suggest_strategy_known_task_type(self):
        """suggest_strategy returns non-empty list for known task types."""
        strategies = self.monitor.suggest_strategy("problem_solving")
        assert isinstance(strategies, list)
        assert len(strategies) > 0
        assert any("Break" in s or "problem" in s.lower() for s in strategies)

    def test_suggest_strategy_unknown_task_type(self):
        """suggest_strategy returns default strategies for unknown task types."""
        strategies = self.monitor.suggest_strategy("unknown_xyz_task")
        assert isinstance(strategies, list)
        assert len(strategies) > 0

    def test_get_known_limitations(self):
        """get_known_limitations returns a non-empty list of strings."""
        limitations = self.monitor.get_known_limitations()
        assert isinstance(limitations, list)
        assert len(limitations) > 0
        assert all(isinstance(s, str) for s in limitations)

    def test_calibrate_adjusts_threshold(self):
        """calibrate adjusts uncertainty_threshold based on feedback."""
        original = self.monitor._uncertainty_threshold

        # Inaccurate feedback raises threshold
        self.monitor.calibrate({"was_accurate": False})
        raised = self.monitor._uncertainty_threshold
        assert raised > original

        # Accurate feedback lowers threshold
        self.monitor.calibrate({"was_accurate": True})
        lowered = self.monitor._uncertainty_threshold
        assert lowered < raised


# =============================================================================
# MIND WANDERING TESTS
# =============================================================================

class TestMindWanderingEnums:
    """Tests for WanderingType and WanderingDepth enums."""

    def test_wandering_type_values(self):
        from core.neuroscience.mind_wandering import WanderingType

        assert WanderingType.SPONTANEOUS.value == "spontaneous"
        assert WanderingType.DELIBERATE.value == "deliberate"
        assert WanderingType.PROBLEM_FOCUSED.value == "problem"
        assert WanderingType.MEMORY_TRIGGERED.value == "memory"
        assert WanderingType.CREATIVE.value == "creative"

    def test_wandering_depth_values(self):
        from core.neuroscience.mind_wandering import WanderingDepth

        assert WanderingDepth.SHALLOW.value == "shallow"
        assert WanderingDepth.MODERATE.value == "moderate"
        assert WanderingDepth.DEEP.value == "deep"


class TestMindWanderingEngine:
    """Tests for MindWanderingEngine methods."""

    def setup_method(self):
        from core.neuroscience.mind_wandering import MindWanderingEngine
        self.engine = MindWanderingEngine()

    def test_add_concern(self):
        """add_concern adds to the concern list."""
        self.engine.add_concern("test concern", importance=0.8)
        concerns = self.engine.get_current_concerns()
        assert len(concerns) == 1
        assert concerns[0]["content"] == "test concern"
        assert concerns[0]["importance"] == 0.8

    def test_get_current_concerns_returns_added(self):
        """get_current_concerns returns all added concerns."""
        self.engine.add_concern("concern A", 0.5)
        self.engine.add_concern("concern B", 0.9)
        concerns = self.engine.get_current_concerns()
        assert len(concerns) == 2
        contents = [c["content"] for c in concerns]
        assert "concern A" in contents
        assert "concern B" in contents

    def test_wander_returns_episode_with_thought_chain(self):
        """wander returns a WanderingEpisode with a non-empty thought_chain."""
        from core.neuroscience.mind_wandering import WanderingType, WanderingEpisode

        episode = self.engine.wander(
            wandering_type=WanderingType.SPONTANEOUS,
            starting_thought="What is consciousness?",
            max_duration_ms=2000
        )
        assert isinstance(episode, WanderingEpisode)
        assert len(episode.thought_chain) >= 1
        assert episode.thought_chain[0] == "What is consciousness?"
        assert episode.starting_thought == "What is consciousness?"
        assert episode.ending_thought == episode.thought_chain[-1]

    def test_get_wandering_stats_structure(self):
        """get_wandering_stats returns dict with expected keys after wandering."""
        from core.neuroscience.mind_wandering import WanderingType

        # No episodes yet
        stats = self.engine.get_wandering_stats()
        assert stats["total_episodes"] == 0

        # After one episode
        self.engine.wander(WanderingType.SPONTANEOUS, max_duration_ms=500)
        stats = self.engine.get_wandering_stats()
        assert stats["total_episodes"] == 1
        assert "episodes_by_type" in stats
        assert "average_chain_length" in stats

    def test_clear_concerns(self):
        """clear_concerns empties the concern list."""
        self.engine.add_concern("will be cleared", 0.5)
        assert len(self.engine.get_current_concerns()) == 1

        self.engine.clear_concerns()
        assert len(self.engine.get_current_concerns()) == 0

    def test_concern_importance_clamped(self):
        """Concern importance is clamped to [0, 1]."""
        self.engine.add_concern("over", importance=5.0)
        self.engine.add_concern("under", importance=-1.0)
        concerns = self.engine.get_current_concerns()
        assert concerns[0]["importance"] == 1.0
        assert concerns[1]["importance"] == 0.0


# =============================================================================
# UNIFIED MEMORY ARCHITECTURE TESTS
# =============================================================================

class TestSystemStateEnum:
    """Tests for SystemState enum."""

    def test_system_state_values(self):
        from core.neuroscience.unified import SystemState

        assert SystemState.IDLE.value == "idle"
        assert SystemState.INTERACTIVE.value == "interactive"
        assert SystemState.AUTONOMOUS.value == "autonomous"
        assert SystemState.CONSOLIDATING.value == "consolidating"
        assert SystemState.WANDERING.value == "wandering"
        assert len(SystemState) == 5


class TestUnifiedMemoryArchitecture:
    """Tests for UnifiedMemoryArchitecture methods."""

    def setup_method(self):
        from core.neuroscience.unified import UnifiedMemoryArchitecture
        self.uma = UnifiedMemoryArchitecture()

    def test_is_idle_true_when_no_interaction(self):
        """_is_idle returns True when no interaction has occurred."""
        assert self.uma._is_idle() is True

    def test_is_idle_false_during_interaction(self):
        """_is_idle returns False right after an interaction timestamp is set."""
        self.uma._last_interaction = datetime.now().isoformat()
        assert self.uma._is_idle() is False

    def test_is_idle_true_after_threshold(self):
        """_is_idle returns True after idle_threshold_seconds have elapsed."""
        past = datetime.now() - timedelta(seconds=self.uma.idle_threshold_seconds + 1)
        self.uma._last_interaction = past.isoformat()
        assert self.uma._is_idle() is True

    def test_get_system_state_structure(self):
        """get_system_state returns dict with expected top-level keys."""
        state = self.uma.get_system_state()
        assert "state" in state
        assert "last_interaction" in state
        assert "is_running" in state
        assert "consolidator" in state
        assert "dmn" in state
        assert "metacognition" in state
        assert "mind_wanderer" in state
        assert state["state"] == "idle"

    def test_assess_confidence_delegates_to_metacognition(self):
        """assess_confidence returns a float from metacognition module."""
        result = self.uma.assess_confidence("I know this for certain")
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_add_concern_delegates_to_mind_wanderer(self):
        """add_concern adds to mind_wanderer's concern list."""
        self.uma.add_concern("unified concern", importance=0.7)
        concerns = self.uma.mind_wanderer.get_current_concerns()
        assert len(concerns) == 1
        assert concerns[0]["content"] == "unified concern"
        assert concerns[0]["importance"] == 0.7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
