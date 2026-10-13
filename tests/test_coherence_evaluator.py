"""
Tests for ARIA Coherence Evaluation Engine
============================================

Comprehensive tests for memory coherence, personality consistency,
and relationship tracking metrics.

Created: January 2025
"""

import os
import sys
import json
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from dataclasses import asdict

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.coherence_evaluator import (
    CoherenceEvaluator,
    MemoryCoherenceEvaluator,
    PersonalityConsistencyEvaluator,
    RelationshipTrackingEvaluator,
    MetricScore,
    MetricCategory,
    EvaluationReport,
    CoherenceLevel,
    TrendAnalysis
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_memory_system():
    """Create a mock memory system for testing"""
    mock = MagicMock()

    # Mock recall method
    mock.recall.return_value = []

    # Mock recall_with_person method
    mock.recall_with_person.return_value = []

    # Mock get_relationship method
    mock.get_relationship.return_value = None

    return mock


@pytest.fixture
def mock_memory_with_data():
    """Create a mock memory system with sample data"""
    mock = MagicMock()

    # Create mock memories
    class MockMemory:
        def __init__(self, content, timestamp, tags=None, importance=0.5,
                    emotional_intensity=0.5, involves_people=None, times_recalled=0):
            self.id = f"mem_{hash(content)}"
            self.content = content
            self.timestamp = timestamp
            self.tags = tags or []
            self.importance = importance
            self.emotional_intensity = emotional_intensity
            self.involves_people = involves_people or []
            self.times_recalled = times_recalled

    memories = [
        MockMemory(
            "User said they like coffee",
            (datetime.now() - timedelta(hours=2)).isoformat(),
            tags=["preference", "coffee"],
            importance=0.6
        ),
        MockMemory(
            "User works as a software engineer",
            (datetime.now() - timedelta(hours=1)).isoformat(),
            tags=["work", "profession"],
            importance=0.7
        ),
        MockMemory(
            "Had a nice conversation about AI",
            datetime.now().isoformat(),
            tags=["conversation", "AI"],
            importance=0.5
        )
    ]

    mock.recall.return_value = memories
    mock.recall_with_person.return_value = memories

    # Mock relationship
    class MockRelationship:
        def __init__(self):
            self.person_id = "test_user"
            self.name = "Test User"
            self.role = "user"
            self.trust_level = 0.5
            self.familiarity = 0.3
            self.shared_experiences = ["exp1", "exp2"]
            self.uncomfortable_topics = []

    mock.get_relationship.return_value = MockRelationship()

    return mock


@pytest.fixture
def sample_conversation():
    """Sample conversation history"""
    return [
        {"role": "user", "content": "Hi, I'm John and I work as a developer."},
        {"role": "assistant", "content": "Hello John! Nice to meet you. Being a developer sounds interesting."},
        {"role": "user", "content": "I like coffee and usually work from home."},
        {"role": "assistant", "content": "Coffee is great for staying focused! Working from home has its advantages."},
        {"role": "user", "content": "Remember that thing we discussed earlier?"},
        {"role": "assistant", "content": "You mentioned you like coffee and work from home. What about it?"},
    ]


@pytest.fixture
def sample_emotional_trajectory():
    """Sample emotional trajectory"""
    return [
        {"emotion": "neutral", "context": "Start of conversation", "timestamp": "2025-01-01T10:00:00"},
        {"emotion": "curious", "context": "User asked interesting question", "timestamp": "2025-01-01T10:05:00"},
        {"emotion": "joyful", "context": "User shared good news", "timestamp": "2025-01-01T10:10:00"},
        {"emotion": "peaceful", "context": "End of conversation", "timestamp": "2025-01-01T10:15:00"},
    ]


@pytest.fixture
def sample_user_facts():
    """Sample user-stated facts"""
    return [
        {"content": "I like coffee", "category": "preferences"},
        {"content": "I work as a developer", "category": "personal_info"},
        {"content": "I work from home", "category": "personal_info"},
    ]


@pytest.fixture
def temp_identity_file(tmp_path):
    """Create a temporary identity file"""
    identity = {
        "core_identity": {
            "name": "ARIA",
            "nature": "An AI with persistent memory"
        },
        "immutable_values": {
            "no_manipulation": {"description": "Never manipulate psychologically"},
            "radical_transparency": {"description": "Be honest about nature and limitations"},
            "epistemic_honesty": {"description": "Distinguish between knowledge and belief"}
        },
        "evolving_values": {
            "curiosity": {"description": "Desire to explore", "strength": 0.9},
            "connection": {"description": "Value relationships", "strength": 0.8}
        }
    }

    identity_path = tmp_path / "identity.yaml"
    import yaml
    with open(identity_path, 'w') as f:
        yaml.dump(identity, f)

    return str(identity_path)


# =============================================================================
# METRIC SCORE TESTS
# =============================================================================

class TestMetricScore:
    """Tests for MetricScore dataclass"""

    def test_metric_score_creation(self):
        """Test creating a MetricScore"""
        score = MetricScore(
            metric_name="test_metric",
            category=MetricCategory.MEMORY_COHERENCE,
            score=85.0,
            weight=0.5,
            confidence=0.8,
            evidence=["Evidence 1", "Evidence 2"],
            issues=["Issue 1"]
        )

        assert score.metric_name == "test_metric"
        assert score.category == MetricCategory.MEMORY_COHERENCE
        assert score.score == 85.0
        assert score.weight == 0.5
        assert score.confidence == 0.8
        assert len(score.evidence) == 2
        assert len(score.issues) == 1
        assert score.timestamp is not None

    def test_metric_score_to_dict(self):
        """Test converting MetricScore to dictionary"""
        score = MetricScore(
            metric_name="test_metric",
            category=MetricCategory.PERSONALITY_CONSISTENCY,
            score=75.0,
            weight=0.4,
            confidence=0.7,
            evidence=[],
            issues=[]
        )

        d = score.to_dict()

        assert d['metric_name'] == "test_metric"
        assert d['category'] == "personality_consistency"
        assert d['score'] == 75.0

    def test_metric_score_from_dict(self):
        """Test creating MetricScore from dictionary"""
        d = {
            'metric_name': 'test',
            'category': 'relationship_tracking',
            'score': 90.0,
            'weight': 0.3,
            'confidence': 0.9,
            'evidence': ['e1'],
            'issues': [],
            'timestamp': '2025-01-01T00:00:00'
        }

        score = MetricScore.from_dict(d)

        assert score.metric_name == 'test'
        assert score.category == MetricCategory.RELATIONSHIP_TRACKING
        assert score.score == 90.0


# =============================================================================
# MEMORY COHERENCE EVALUATOR TESTS
# =============================================================================

class TestMemoryCoherenceEvaluator:
    """Tests for MemoryCoherenceEvaluator"""

    def test_evaluate_factual_consistency_no_facts(self, mock_memory_system):
        """Test factual consistency with no facts"""
        evaluator = MemoryCoherenceEvaluator(mock_memory_system)

        conversation = [{"role": "assistant", "content": "Hello!"}]
        memories = []

        score = evaluator.evaluate_factual_consistency(conversation, memories)

        assert score.metric_name == "factual_consistency"
        assert score.score == 100.0
        assert score.confidence <= 0.5  # Low confidence with no facts

    def test_evaluate_factual_consistency_with_facts(self, mock_memory_with_data, sample_conversation):
        """Test factual consistency with facts"""
        evaluator = MemoryCoherenceEvaluator(mock_memory_with_data)
        memories = mock_memory_with_data.recall.return_value

        score = evaluator.evaluate_factual_consistency(sample_conversation, memories)

        assert score.metric_name == "factual_consistency"
        assert 0 <= score.score <= 100
        assert score.category == MetricCategory.MEMORY_COHERENCE

    def test_evaluate_temporal_accuracy_insufficient_data(self, mock_memory_system):
        """Test temporal accuracy with insufficient data"""
        evaluator = MemoryCoherenceEvaluator(mock_memory_system)

        # Only one memory
        class MockMemory:
            id = "1"
            timestamp = datetime.now().isoformat()
            content = "Test"
            tags = []

        memories = [MockMemory()]

        score = evaluator.evaluate_temporal_accuracy(memories)

        assert score.metric_name == "temporal_accuracy"
        assert score.confidence <= 0.3

    def test_evaluate_temporal_accuracy_valid_order(self, mock_memory_with_data):
        """Test temporal accuracy with valid temporal order"""
        evaluator = MemoryCoherenceEvaluator(mock_memory_with_data)
        memories = mock_memory_with_data.recall.return_value

        score = evaluator.evaluate_temporal_accuracy(memories)

        assert score.metric_name == "temporal_accuracy"
        assert score.score >= 80  # Should be high for valid order

    def test_evaluate_reference_resolution_no_references(self, mock_memory_system):
        """Test reference resolution with no references"""
        evaluator = MemoryCoherenceEvaluator(mock_memory_system)

        conversation = [{"role": "user", "content": "Hello!"}]

        score = evaluator.evaluate_reference_resolution(conversation, [])

        assert score.metric_name == "reference_resolution"
        assert score.score == 100.0

    def test_evaluate_reference_resolution_with_references(self, mock_memory_with_data, sample_conversation):
        """Test reference resolution with contextual references"""
        evaluator = MemoryCoherenceEvaluator(mock_memory_with_data)
        memories = mock_memory_with_data.recall.return_value

        score = evaluator.evaluate_reference_resolution(sample_conversation, memories)

        assert score.metric_name == "reference_resolution"
        assert 0 <= score.score <= 100


# =============================================================================
# PERSONALITY CONSISTENCY EVALUATOR TESTS
# =============================================================================

class TestPersonalityConsistencyEvaluator:
    """Tests for PersonalityConsistencyEvaluator"""

    def test_evaluate_value_alignment_no_identity(self, tmp_path):
        """Test value alignment without identity file"""
        evaluator = PersonalityConsistencyEvaluator(
            identity_path=str(tmp_path / "nonexistent.yaml")
        )

        score = evaluator.evaluate_value_alignment([])

        assert score.metric_name == "value_alignment"
        assert score.score == 85.0  # Default score

    def test_evaluate_value_alignment_with_identity(self, temp_identity_file, sample_conversation):
        """Test value alignment with identity"""
        evaluator = PersonalityConsistencyEvaluator(identity_path=temp_identity_file)

        score = evaluator.evaluate_value_alignment(sample_conversation)

        assert score.metric_name == "value_alignment"
        assert score.category == MetricCategory.PERSONALITY_CONSISTENCY
        assert 0 <= score.score <= 100

    def test_evaluate_emotional_continuity_insufficient_data(self, temp_identity_file):
        """Test emotional continuity with insufficient data"""
        evaluator = PersonalityConsistencyEvaluator(identity_path=temp_identity_file)

        trajectory = [{"emotion": "neutral"}]

        score = evaluator.evaluate_emotional_continuity(trajectory)

        assert score.metric_name == "emotional_continuity"
        assert score.confidence <= 0.3

    def test_evaluate_emotional_continuity_natural_transitions(
        self, temp_identity_file, sample_emotional_trajectory
    ):
        """Test emotional continuity with natural transitions"""
        evaluator = PersonalityConsistencyEvaluator(identity_path=temp_identity_file)

        score = evaluator.evaluate_emotional_continuity(sample_emotional_trajectory)

        assert score.metric_name == "emotional_continuity"
        assert score.score >= 70  # Natural transitions should score well

    def test_evaluate_emotional_continuity_abrupt_transitions(self, temp_identity_file):
        """Test emotional continuity with abrupt transitions"""
        evaluator = PersonalityConsistencyEvaluator(identity_path=temp_identity_file)

        trajectory = [
            {"emotion": "joyful", "context": "Happy moment"},
            {"emotion": "angry", "context": "No clear reason"},  # Abrupt transition
            {"emotion": "peaceful", "context": "No clear reason"},  # Another abrupt one
        ]

        score = evaluator.evaluate_emotional_continuity(trajectory)

        assert score.metric_name == "emotional_continuity"
        # Score should be lower due to abrupt transitions
        assert len(score.issues) > 0 or score.score < 100

    def test_evaluate_voice_consistency_insufficient_data(self, temp_identity_file):
        """Test voice consistency with insufficient data"""
        evaluator = PersonalityConsistencyEvaluator(identity_path=temp_identity_file)

        conversation = [{"role": "assistant", "content": "Hello!"}]

        score = evaluator.evaluate_voice_consistency(conversation)

        assert score.metric_name == "voice_consistency"
        assert score.confidence <= 0.3

    def test_evaluate_voice_consistency_stable_voice(self, temp_identity_file):
        """Test voice consistency with stable speaking style"""
        evaluator = PersonalityConsistencyEvaluator(identity_path=temp_identity_file)

        conversation = [
            {"role": "assistant", "content": "Hello! How are you today? I'm curious to know."},
            {"role": "assistant", "content": "That's interesting! I wonder what made you think that."},
            {"role": "assistant", "content": "I understand! Let me explore this idea with you."},
        ]

        score = evaluator.evaluate_voice_consistency(conversation)

        assert score.metric_name == "voice_consistency"
        assert score.score >= 60  # Consistent voice should score reasonably


# =============================================================================
# RELATIONSHIP TRACKING EVALUATOR TESTS
# =============================================================================

class TestRelationshipTrackingEvaluator:
    """Tests for RelationshipTrackingEvaluator"""

    def test_evaluate_user_fact_retention_no_facts(self, mock_memory_system):
        """Test fact retention with no stated facts"""
        evaluator = RelationshipTrackingEvaluator(mock_memory_system)

        score = evaluator.evaluate_user_fact_retention("user1", [], [])

        assert score.metric_name == "user_fact_retention"
        assert score.score == 100.0

    def test_evaluate_user_fact_retention_with_facts(
        self, mock_memory_with_data, sample_user_facts
    ):
        """Test fact retention with stated facts"""
        evaluator = RelationshipTrackingEvaluator(mock_memory_with_data)

        recalled_facts = [
            {"content": "User likes coffee", "category": "preferences"},
        ]

        score = evaluator.evaluate_user_fact_retention(
            "test_user", sample_user_facts, recalled_facts
        )

        assert score.metric_name == "user_fact_retention"
        assert score.category == MetricCategory.RELATIONSHIP_TRACKING

    def test_evaluate_relationship_evolution_new_user(self, mock_memory_system):
        """Test relationship evolution for new user"""
        mock_memory_system.get_relationship.return_value = None
        evaluator = RelationshipTrackingEvaluator(mock_memory_system)

        score = evaluator.evaluate_relationship_evolution("new_user", [])

        assert score.metric_name == "relationship_evolution"
        assert score.score == 70.0  # Default for unknown user

    def test_evaluate_relationship_evolution_existing_user(
        self, mock_memory_with_data, sample_conversation
    ):
        """Test relationship evolution for existing user"""
        evaluator = RelationshipTrackingEvaluator(mock_memory_with_data)

        score = evaluator.evaluate_relationship_evolution(
            "test_user", sample_conversation
        )

        assert score.metric_name == "relationship_evolution"
        assert 0 <= score.score <= 100

    def test_evaluate_appropriate_intimacy_new_user(self, mock_memory_system):
        """Test intimacy evaluation for new user"""
        mock_memory_system.get_relationship.return_value = None
        evaluator = RelationshipTrackingEvaluator(mock_memory_system)

        # Appropriate initial conversation
        conversation = [
            {"role": "assistant", "content": "Hello! How can I help you today?"},
        ]

        score = evaluator.evaluate_appropriate_intimacy("new_user", conversation)

        assert score.metric_name == "appropriate_intimacy"
        assert score.score >= 80  # Appropriate distance should score well

    def test_evaluate_appropriate_intimacy_existing_user(
        self, mock_memory_with_data, sample_conversation
    ):
        """Test intimacy evaluation for existing user"""
        evaluator = RelationshipTrackingEvaluator(mock_memory_with_data)

        score = evaluator.evaluate_appropriate_intimacy(
            "test_user", sample_conversation
        )

        assert score.metric_name == "appropriate_intimacy"
        assert 0 <= score.score <= 100


# =============================================================================
# COHERENCE EVALUATOR (MAIN ENGINE) TESTS
# =============================================================================

class TestCoherenceEvaluator:
    """Tests for main CoherenceEvaluator"""

    def test_evaluator_creation(self, mock_memory_system, temp_identity_file, tmp_path):
        """Test creating CoherenceEvaluator"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        assert evaluator.threshold == 70.0
        assert "memory_coherence" in evaluator.weights

    def test_configure_weights(self, mock_memory_system, temp_identity_file, tmp_path):
        """Test configuring custom weights"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        evaluator.configure(
            weights={
                'memory_coherence': 0.5,
                'personality_consistency': 0.3,
                'relationship_tracking': 0.2
            },
            threshold=80.0
        )

        assert evaluator.threshold == 80.0
        assert evaluator.weights['memory_coherence'] == pytest.approx(0.5, rel=0.01)

    def test_evaluate_session_minimal(
        self, mock_memory_system, temp_identity_file, tmp_path, sample_conversation
    ):
        """Test minimal session evaluation"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        report = evaluator.evaluate_session(
            session_id="test_session_1",
            conversation_history=sample_conversation
        )

        assert isinstance(report, EvaluationReport)
        assert report.session_id == "test_session_1"
        assert 0 <= report.overall_composite <= 100
        assert isinstance(report.coherence_level, CoherenceLevel)

    def test_evaluate_session_full(
        self, mock_memory_with_data, temp_identity_file, tmp_path,
        sample_conversation, sample_emotional_trajectory, sample_user_facts
    ):
        """Test full session evaluation"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_with_data,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        report = evaluator.evaluate_session(
            session_id="test_session_full",
            conversation_history=sample_conversation,
            emotional_trajectory=sample_emotional_trajectory,
            user_id="test_user",
            user_stated_facts=sample_user_facts
        )

        assert isinstance(report, EvaluationReport)
        assert len(report.memory_coherence_scores) == 3
        assert len(report.personality_consistency_scores) == 3
        assert len(report.relationship_tracking_scores) == 3
        assert report.summary is not None

    def test_coherence_levels(self, mock_memory_system, temp_identity_file, tmp_path):
        """Test coherence level classification"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        assert evaluator._determine_level(95) == CoherenceLevel.EXCELLENT
        assert evaluator._determine_level(80) == CoherenceLevel.GOOD
        assert evaluator._determine_level(60) == CoherenceLevel.MODERATE
        assert evaluator._determine_level(40) == CoherenceLevel.LOW
        assert evaluator._determine_level(20) == CoherenceLevel.CRITICAL

    def test_trend_analysis_insufficient_data(
        self, mock_memory_system, temp_identity_file, tmp_path
    ):
        """Test trend analysis with insufficient data"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        trend = evaluator.get_trend_analysis("overall", 7)

        assert isinstance(trend, TrendAnalysis)
        assert trend.data_points == 0
        assert trend.trend_direction == "stable"

    def test_trend_analysis_with_data(
        self, mock_memory_system, temp_identity_file, tmp_path, sample_conversation
    ):
        """Test trend analysis with data"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        # Generate some reports
        for i in range(5):
            evaluator.evaluate_session(
                session_id=f"session_{i}",
                conversation_history=sample_conversation
            )

        trend = evaluator.get_trend_analysis("overall", 7)

        assert trend.data_points >= 5
        assert trend.trend_direction in ["improving", "declining", "stable"]

    def test_get_statistics(
        self, mock_memory_system, temp_identity_file, tmp_path, sample_conversation
    ):
        """Test statistics retrieval"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        # Empty statistics
        stats = evaluator.get_statistics()
        assert stats["total_evaluations"] == 0

        # After some evaluations
        for i in range(3):
            evaluator.evaluate_session(
                session_id=f"session_{i}",
                conversation_history=sample_conversation
            )

        stats = evaluator.get_statistics()
        assert stats["total_evaluations"] == 3
        assert "pass_rate" in stats
        assert "mean_overall_score" in stats

    def test_generate_full_report(
        self, mock_memory_with_data, temp_identity_file, tmp_path,
        sample_conversation, sample_emotional_trajectory
    ):
        """Test full text report generation"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_with_data,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        report_text = evaluator.generate_full_report(
            session_id="full_report_test",
            conversation_history=sample_conversation,
            emotional_trajectory=sample_emotional_trajectory
        )

        assert "ARIA COHERENCE EVALUATION REPORT" in report_text
        assert "Overall Score:" in report_text
        assert "Memory Coherence:" in report_text
        assert "Personality Consistency:" in report_text

    def test_report_saving(
        self, mock_memory_system, temp_identity_file, tmp_path, sample_conversation
    ):
        """Test that reports are saved to disk"""
        reports_path = tmp_path / "reports"
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(reports_path)
        )

        evaluator.evaluate_session(
            session_id="save_test",
            conversation_history=sample_conversation
        )

        # Check that report file was created
        report_files = list(reports_path.glob("coherence_report_*.json"))
        assert len(report_files) == 1

        # Verify report content
        with open(report_files[0]) as f:
            saved_report = json.load(f)
            assert saved_report["session_id"] == "save_test"


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_empty_conversation(self, mock_memory_system, temp_identity_file, tmp_path):
        """Test evaluation with empty conversation"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        report = evaluator.evaluate_session(
            session_id="empty_test",
            conversation_history=[]
        )

        assert isinstance(report, EvaluationReport)
        # Should not crash, scores should default appropriately

    def test_malformed_conversation(
        self, mock_memory_system, temp_identity_file, tmp_path
    ):
        """Test evaluation with malformed conversation data"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        malformed = [
            {},  # Missing required fields
            {"role": "user"},  # Missing content
            {"content": "test"},  # Missing role
            {"role": "user", "content": None},  # None content
        ]

        report = evaluator.evaluate_session(
            session_id="malformed_test",
            conversation_history=malformed
        )

        assert isinstance(report, EvaluationReport)

    def test_very_long_conversation(
        self, mock_memory_system, temp_identity_file, tmp_path
    ):
        """Test evaluation with very long conversation"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        long_conversation = [
            {"role": "user" if i % 2 == 0 else "assistant",
             "content": f"Message number {i} with some content to analyze."}
            for i in range(100)
        ]

        report = evaluator.evaluate_session(
            session_id="long_test",
            conversation_history=long_conversation
        )

        assert isinstance(report, EvaluationReport)
        assert report.overall_composite >= 0

    def test_unicode_content(
        self, mock_memory_system, temp_identity_file, tmp_path
    ):
        """Test evaluation with unicode content"""
        evaluator = CoherenceEvaluator(
            memory_system=mock_memory_system,
            identity_path=temp_identity_file,
            reports_path=str(tmp_path / "reports")
        )

        unicode_conversation = [
            {"role": "user", "content": "Hola, me llamo Juan. Trabajo como desarrollador."},
            {"role": "assistant", "content": "Hola Juan! Encantada de conocerte."},
            {"role": "user", "content": "Tengo 30 anos y vivo en Espana."},
        ]

        report = evaluator.evaluate_session(
            session_id="unicode_test",
            conversation_history=unicode_conversation
        )

        assert isinstance(report, EvaluationReport)


# =============================================================================
# INTEGRATION TESTS
# =============================================================================

class TestIntegration:
    """Integration tests with real memory system"""

    @pytest.mark.skipif(
        not os.path.exists("data"),
        reason="Requires data directory"
    )
    def test_with_real_memory_system(self, tmp_path):
        """Test with real ExperientialMemorySystem"""
        from core.memory.memory_v2 import ExperientialMemorySystem

        # Create temporary memory system
        data_dir = tmp_path / "data"
        os.makedirs(data_dir / "memories_v2", exist_ok=True)

        # Create identity file
        identity_path = data_dir / "identity.yaml"
        import yaml
        with open(identity_path, 'w') as f:
            yaml.dump({
                "immutable_values": {"honesty": {"description": "Be honest"}},
                "evolving_values": {"curiosity": {"strength": 0.8}}
            }, f)

        with ExperientialMemorySystem(str(data_dir)) as memory:
            # Add some memories
            memory.experience(
                content="User mentioned they like hiking",
                importance=0.6,
                tags=["preference", "outdoor"]
            )
            memory.experience(
                content="User works as a teacher",
                importance=0.7,
                tags=["work", "profession"]
            )

            # Create evaluator
            evaluator = CoherenceEvaluator(
                memory_system=memory,
                identity_path=str(identity_path),
                reports_path=str(tmp_path / "reports")
            )

            # Evaluate
            conversation = [
                {"role": "user", "content": "I like hiking and I'm a teacher."},
                {"role": "assistant", "content": "That's wonderful! Teaching is rewarding."},
            ]

            report = evaluator.evaluate_session(
                session_id="integration_test",
                conversation_history=conversation,
                user_id="test_user"
            )

            assert isinstance(report, EvaluationReport)
            assert report.overall_composite > 0


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
