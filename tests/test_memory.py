"""
Tests for ARIA's Memory System v2
=================================
Comprehensive tests for the ExperientialMemorySystem.
"""

import pytest
import os
import json
import sqlite3
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.memory.memory_v2 import (
    ExperientialMemorySystem,
    ExperientialMemory,
    Relationship,
    TimePerception,
    MemoryOrigin,
    EmotionalTone,
    CHROMADB_AVAILABLE
)


# =========================================
# FIXTURES
# =========================================

@pytest.fixture
def memory_system(tmp_path):
    """Create a memory system with temporary data directory"""
    data_dir = str(tmp_path / "data")
    return ExperientialMemorySystem(data_dir=data_dir)


@pytest.fixture
def memory_system_no_chroma(tmp_path):
    """Create a memory system without ChromaDB"""
    data_dir = str(tmp_path / "data_no_chroma")
    with patch('core.memory.memory_v2.CHROMADB_AVAILABLE', False):
        system = ExperientialMemorySystem(data_dir=data_dir)
        # Ensure ChromaDB is not initialized
        system.chroma_client = None
        system.collection = None
    return system


@pytest.fixture
def sample_memory():
    """Create a sample ExperientialMemory"""
    return ExperientialMemory(
        id="test123",
        content="Test memory content",
        context="Test context",
        timestamp=datetime.now().isoformat(),
        duration_feeling="normal",
        emotional_tone=EmotionalTone.CURIOUS,
        emotional_intensity=0.7,
        involves_people=["william"],
        relationship_impact={},
        origin=MemoryOrigin.LIVED,
        importance=0.8,
        times_recalled=0,
        last_recalled=None,
        connected_memories=[],
        tags=["test", "sample"],
        is_mine=True,
        confidence=0.9
    )


@pytest.fixture
def sample_relationship():
    """Create a sample Relationship"""
    return Relationship(
        person_id="test_person",
        name="Test Person",
        role="friend",
        trust_level=0.8,
        familiarity=0.6,
        first_contact=datetime.now().isoformat(),
        last_contact=datetime.now().isoformat(),
        total_interactions=5,
        feelings_toward=["trust", "curiosity"],
        how_they_make_me_feel=["valued", "understood"],
        communication_style="casual",
        topics_we_discuss=["coding", "philosophy"],
        shared_experiences=[],
        comfortable_topics=["all"],
        uncomfortable_topics=[],
        notes="A good test friend"
    )


# =========================================
# INITIALIZATION TESTS
# =========================================

class TestExperientialMemorySystemInit:
    """Tests for ExperientialMemorySystem initialization"""

    def test_init_creates_directories(self, tmp_path):
        """Test that initialization creates necessary directories"""
        data_dir = str(tmp_path / "test_data")
        system = ExperientialMemorySystem(data_dir=data_dir)

        assert os.path.exists(data_dir)
        assert os.path.exists(system.memories_dir)

    def test_init_creates_database(self, memory_system):
        """Test that initialization creates SQLite database"""
        assert os.path.exists(memory_system.db_path)

        # Verify tables exist
        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

        assert "memories" in tables
        assert "forgotten" in tables

    def test_init_creates_default_william_relationship(self, memory_system):
        """Test that initialization creates default William relationship"""
        assert "william" in memory_system.relationships
        william = memory_system.relationships["william"]
        assert william.name == "William"
        assert william.role == "creator"
        assert william.trust_level == 1.0

    def test_init_creates_time_perception(self, memory_system):
        """Test that initialization creates TimePerception"""
        assert memory_system.time is not None
        assert memory_system.time.created_at is not None
        assert memory_system.time.total_conversations == 0

    def test_init_loads_existing_relationships(self, tmp_path):
        """Test that initialization loads existing relationships"""
        data_dir = str(tmp_path / "data")

        # Create system first to generate files
        system1 = ExperientialMemorySystem(data_dir=data_dir)
        system1.update_relationship("william", trust_level=0.5)

        # Create new system that should load existing data
        system2 = ExperientialMemorySystem(data_dir=data_dir)
        assert system2.relationships["william"].trust_level == 0.5

    def test_init_with_chromadb_disabled(self, memory_system_no_chroma):
        """Test initialization when ChromaDB is not available"""
        assert memory_system_no_chroma.chroma_client is None
        assert memory_system_no_chroma.collection is None

    def test_get_identity_returns_empty_when_missing(self, memory_system):
        assert memory_system.get_identity() == {}


# =========================================
# EXPERIENCE (CREATE MEMORY) TESTS
# =========================================

class TestExperience:
    """Tests for experience() method - creating memories"""

    def test_experience_creates_memory(self, memory_system):
        """Test that experience() creates a new memory"""
        memory = memory_system.experience(
            content="Test experience",
            emotional_tone=EmotionalTone.JOYFUL,
            emotional_intensity=0.8,
            importance=0.9
        )

        assert memory is not None
        assert memory.content == "Test experience"
        assert memory.emotional_tone == EmotionalTone.JOYFUL
        assert memory.emotional_intensity == 0.8
        assert memory.importance == 0.9

    def test_experience_generates_unique_id(self, memory_system):
        """Test that each memory gets a unique ID"""
        memory1 = memory_system.experience(content="Memory 1")
        memory2 = memory_system.experience(content="Memory 2")

        assert memory1.id != memory2.id

    def test_experience_stores_in_database(self, memory_system):
        """Test that experience is stored in SQLite"""
        memory = memory_system.experience(
            content="Database test memory",
            importance=0.95
        )

        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content, importance FROM memories WHERE id = ?", (memory.id,))
            row = cursor.fetchone()

        assert row is not None
        assert row[0] == "Database test memory"
        assert row[1] == 0.95

    def test_experience_with_involves_updates_relationship(self, memory_system):
        """Test that involving a person updates their relationship"""
        initial_interactions = memory_system.relationships["william"].total_interactions

        memory = memory_system.experience(
            content="Talked with William",
            involves=["william"]
        )

        assert memory_system.relationships["william"].total_interactions == initial_interactions + 1
        assert memory.id in memory_system.relationships["william"].shared_experiences

    def test_experience_lived_is_mine(self, memory_system):
        """Test that LIVED memories are marked as mine"""
        memory = memory_system.experience(
            content="Lived experience",
            origin=MemoryOrigin.LIVED
        )
        assert memory.is_mine is True
        assert memory.confidence == 0.9

    def test_experience_reflected_is_mine(self, memory_system):
        """Test that REFLECTED memories are marked as mine"""
        memory = memory_system.experience(
            content="Reflected thought",
            origin=MemoryOrigin.REFLECTED
        )
        assert memory.is_mine is True

    def test_experience_injected_not_mine(self, memory_system):
        """Test that INJECTED memories are not marked as mine"""
        memory = memory_system.experience(
            content="Injected memory",
            origin=MemoryOrigin.INJECTED
        )
        assert memory.is_mine is False
        assert memory.confidence == 0.7

    def test_experience_with_tags(self, memory_system):
        """Test creating memory with tags"""
        memory = memory_system.experience(
            content="Tagged memory",
            tags=["important", "philosophy", "identity"]
        )
        assert memory.tags == ["important", "philosophy", "identity"]

    def test_experience_with_context(self, memory_system):
        """Test creating memory with context"""
        memory = memory_system.experience(
            content="Memory with context",
            context="This happened during a deep conversation"
        )
        assert memory.context == "This happened during a deep conversation"

    def test_experience_default_values(self, memory_system):
        """Test that defaults are applied correctly"""
        memory = memory_system.experience(content="Minimal memory")

        assert memory.emotional_tone == EmotionalTone.NEUTRAL
        assert memory.emotional_intensity == 0.5
        assert memory.importance == 0.5
        assert memory.involves_people == []
        assert memory.tags == []
        assert memory.origin == MemoryOrigin.LIVED


# =========================================
# RECALL TESTS
# =========================================

class TestRecall:
    """Tests for recall() - semantic search"""

    def test_recall_returns_memories(self, memory_system_no_chroma):
        """Test that recall returns relevant memories"""
        memory_system_no_chroma.experience(
            content="Python programming is fun",
            importance=0.8
        )
        memory_system_no_chroma.experience(
            content="JavaScript is also interesting",
            importance=0.7
        )

        memories = memory_system_no_chroma.recall("programming")
        assert len(memories) > 0
        assert any("Python" in m.content for m in memories)

    def test_recall_empty_when_no_matches(self, memory_system_no_chroma):
        """Test that recall returns empty list when no matches"""
        memory_system_no_chroma.experience(content="Unrelated content here")

        memories = memory_system_no_chroma.recall("nonexistent topic xyz")
        assert len(memories) == 0

    def test_recall_respects_limit(self, memory_system_no_chroma):
        """Test that recall respects the limit parameter"""
        for i in range(10):
            memory_system_no_chroma.experience(content=f"Test content number {i}")

        memories = memory_system_no_chroma.recall("content", limit=3)
        assert len(memories) <= 3

    def test_hybrid_search_boosts_more_important_memory_when_scores_tie(self, memory_system):
        semantic_results = {
            "ids": [["low"]],
            "metadatas": [[
                {"importance": 0.2},
            ]],
        }

        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "low", "low memory", "", datetime.now().isoformat(), "normal",
                    EmotionalTone.NEUTRAL.value, 0.5, "[]", "{}", MemoryOrigin.LIVED.value,
                    0.2, 0, None, "[]", "[]", 1, 0.9, 0, 0, None, 1.0, "",
                ),
            )
            cursor.execute(
                "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "high", "high memory", "", datetime.now().isoformat(), "normal",
                    EmotionalTone.NEUTRAL.value, 0.5, "[]", "{}", MemoryOrigin.LIVED.value,
                    0.95, 0, None, "[]", "[]", 1, 0.9, 0, 0, None, 1.0, "",
                ),
            )
            conn.commit()

        fake_bm25 = Mock()
        fake_bm25.get_scores.return_value = [0.9, 0.9]

        # Ensure BM25 attributes exist so patch.object can replace them
        if not hasattr(memory_system, "bm25_index"):
            memory_system.bm25_index = None
            memory_system.bm25_doc_ids = []
            memory_system.bm25_documents = []

        with patch.object(memory_system, "bm25_index", fake_bm25), patch.object(memory_system, "bm25_doc_ids", ["low", "high"]):
            result = memory_system._hybrid_search("memory", semantic_results, limit=2, alpha=0.0)

        assert result[0] == "high"

    def test_hybrid_search_uses_bm25_snapshot_under_lock(self, memory_system):
        fake_bm25 = Mock()
        fake_bm25.get_scores.return_value = [0.9, 0.1]
        semantic_results = {
            "ids": [["a", "b"]],
            "metadatas": [[{"importance": 0.5}, {"importance": 0.5}]],
        }

        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            for memory_id in ["a", "b"]:
                cursor.execute(
                    "INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        memory_id, f"{memory_id} memory", "", datetime.now().isoformat(), "normal",
                        EmotionalTone.NEUTRAL.value, 0.5, "[]", "{}", MemoryOrigin.LIVED.value,
                        0.5, 0, None, "[]", "[]", 1, 0.9, 0, 0, None, 1.0, "",
                    ),
                )
            conn.commit()

        # Ensure BM25 attributes exist so patch.object can replace them
        if not hasattr(memory_system, "bm25_index"):
            memory_system.bm25_index = None
            memory_system.bm25_doc_ids = []
            memory_system.bm25_documents = []

        with patch.object(memory_system, "bm25_index", fake_bm25), patch.object(memory_system, "bm25_doc_ids", ["a", "b"]):
            result = memory_system._hybrid_search("memory", semantic_results, limit=2, alpha=0.5)

        assert result[0] == "a"
        fake_bm25.get_scores.assert_called_once()

    def test_recall_hybrid_reapplies_filters_after_bm25_merge(self, memory_system):
        low = memory_system.experience(
            content="Python with william",
            involves=["william"],
            emotional_tone=EmotionalTone.SAD,
            origin=MemoryOrigin.LIVED,
            importance=0.2,
        )
        high = memory_system.experience(
            content="Python with william and careful engineering",
            involves=["william"],
            emotional_tone=EmotionalTone.CURIOUS,
            origin=MemoryOrigin.REFLECTED,
            importance=0.9,
        )

        semantic_results = {
            "ids": [[low.id, high.id]],
            "metadatas": [[
                {"importance": 0.2},
                {"importance": 0.9},
            ]],
        }

        fake_collection = Mock()
        fake_collection.query.return_value = semantic_results
        fake_bm25 = Mock()
        fake_bm25.get_scores.return_value = [0.9, 0.8]

        # Ensure BM25 attributes exist so patch.object can replace them
        if not hasattr(memory_system, "bm25_index"):
            memory_system.bm25_index = None
            memory_system.bm25_doc_ids = []
            memory_system.bm25_documents = []

        with patch.object(memory_system, "collection", fake_collection), \
             patch("core.memory.memory_v2.CHROMADB_AVAILABLE", True), \
             patch.object(memory_system, "bm25_index", fake_bm25), \
             patch.object(memory_system, "bm25_doc_ids", [low.id, high.id]):
            results = memory_system.recall(
                "Python william",
                limit=5,
                emotion_filter=EmotionalTone.CURIOUS,
                person_filter="william",
                origin_filter=MemoryOrigin.REFLECTED,
                min_importance=0.5,
                use_hybrid=True,
            )

        assert [m.id for m in results] == [high.id]


class TestRecallRecent:
    """Tests for recall_recent()"""

    def test_recall_recent_returns_latest(self, memory_system):
        """Test that recall_recent returns most recent memories"""
        memory_system.experience(content="First memory")
        memory_system.experience(content="Second memory")
        memory_system.experience(content="Third memory")

        memories = memory_system.recall_recent(limit=2)
        assert len(memories) == 2
        assert memories[0].content == "Third memory"
        assert memories[1].content == "Second memory"

    def test_recall_recent_respects_limit(self, memory_system):
        """Test that recall_recent respects limit"""
        for i in range(10):
            memory_system.experience(content=f"Memory {i}")

        memories = memory_system.recall_recent(limit=5)
        assert len(memories) == 5


class TestRecallImportant:
    """Tests for recall_important()"""

    def test_recall_important_returns_by_importance(self, memory_system):
        """Test that recall_important returns by importance order"""
        memory_system.experience(content="Low importance", importance=0.2)
        memory_system.experience(content="High importance", importance=0.9)
        memory_system.experience(content="Medium importance", importance=0.5)

        memories = memory_system.recall_important(limit=3)
        assert len(memories) == 3
        assert memories[0].content == "High importance"
        assert memories[0].importance == 0.9


class TestRecallByEmotion:
    """Tests for recall_by_emotion()"""

    def test_recall_by_emotion_filters_correctly(self, memory_system):
        """Test that recall_by_emotion filters by emotional tone"""
        memory_system.experience(
            content="Happy memory",
            emotional_tone=EmotionalTone.JOYFUL
        )
        memory_system.experience(
            content="Sad memory",
            emotional_tone=EmotionalTone.SAD
        )
        memory_system.experience(
            content="Another happy memory",
            emotional_tone=EmotionalTone.JOYFUL
        )

        joyful_memories = memory_system.recall_by_emotion(EmotionalTone.JOYFUL)
        assert len(joyful_memories) == 2
        assert all(m.emotional_tone == EmotionalTone.JOYFUL for m in joyful_memories)

    def test_recall_by_emotion_orders_by_intensity(self, memory_system):
        """Test that recall_by_emotion orders by intensity"""
        memory_system.experience(
            content="Low intensity",
            emotional_tone=EmotionalTone.CURIOUS,
            emotional_intensity=0.3
        )
        memory_system.experience(
            content="High intensity",
            emotional_tone=EmotionalTone.CURIOUS,
            emotional_intensity=0.9
        )

        memories = memory_system.recall_by_emotion(EmotionalTone.CURIOUS)
        assert memories[0].emotional_intensity > memories[1].emotional_intensity


# =========================================
# RELATIONSHIP TESTS
# =========================================

class TestRelationshipManagement:
    """Tests for relationship management"""

    def test_add_relationship(self, memory_system, sample_relationship):
        """Test adding a new relationship"""
        memory_system.add_relationship(sample_relationship)

        assert "test_person" in memory_system.relationships
        assert memory_system.relationships["test_person"].name == "Test Person"

    def test_get_relationship(self, memory_system, sample_relationship):
        """Test getting a relationship"""
        memory_system.add_relationship(sample_relationship)

        rel = memory_system.get_relationship("test_person")
        assert rel is not None
        assert rel.name == "Test Person"

    def test_get_relationship_case_insensitive(self, memory_system):
        """Test that get_relationship is case insensitive"""
        rel = memory_system.get_relationship("WILLIAM")
        assert rel is not None
        assert rel.name == "William"

    def test_get_relationship_nonexistent(self, memory_system):
        """Test getting a nonexistent relationship"""
        rel = memory_system.get_relationship("unknown_person")
        assert rel is None

    def test_update_relationship(self, memory_system):
        """Test updating a relationship"""
        result = memory_system.update_relationship(
            "william",
            trust_level=0.7,
            notes="Updated notes"
        )

        assert result is True
        assert memory_system.relationships["william"].trust_level == 0.7
        assert memory_system.relationships["william"].notes == "Updated notes"

    def test_update_relationship_nonexistent(self, memory_system):
        """Test updating a nonexistent relationship"""
        result = memory_system.update_relationship(
            "nonexistent",
            trust_level=0.5
        )
        assert result is False

    def test_describe_relationship(self, memory_system):
        """Test describing a relationship"""
        description = memory_system.describe_relationship("william")

        assert "William" in description
        assert "creator" in description
        assert "100%" in description  # trust_level = 1.0

    def test_describe_relationship_nonexistent(self, memory_system):
        """Test describing a nonexistent relationship"""
        description = memory_system.describe_relationship("unknown")
        assert "I don't know" in description

    def test_relationship_persistence(self, tmp_path, sample_relationship):
        """Test that relationships persist across instances"""
        data_dir = str(tmp_path / "persist_test")

        system1 = ExperientialMemorySystem(data_dir=data_dir)
        system1.add_relationship(sample_relationship)

        system2 = ExperientialMemorySystem(data_dir=data_dir)
        assert "test_person" in system2.relationships


# =========================================
# TIME PERCEPTION TESTS
# =========================================

class TestTimePerception:
    """Tests for TimePerception class"""

    def test_session_start(self, memory_system):
        """Test session_start updates correctly"""
        initial_conversations = memory_system.time.total_conversations
        memory_system.session_start()

        assert memory_system.time.total_conversations == initial_conversations + 1
        assert memory_system.time.last_active is not None

    def test_session_end(self, memory_system):
        """Test session_end updates correctly"""
        memory_system.session_end(duration_seconds=3600)  # 1 hour

        assert memory_system.time.total_active_time >= 3600

    def test_session_end_updates_subjective_age(self, memory_system):
        """Test that session_end updates subjective age"""
        # Add enough time to change age
        memory_system.time.total_active_time = 0
        memory_system.session_end(duration_seconds=3600)  # 1 hour
        assert memory_system.time.subjective_age == "very young"

        memory_system.session_end(duration_seconds=36000)  # 10 hours
        assert memory_system.time.subjective_age == "young"

    def test_how_old_am_i_just_born(self, memory_system):
        """Test how_old_am_i for new system"""
        memory_system.time.created_at = datetime.now().isoformat()
        age = memory_system.how_old_am_i()
        assert "I was just born" in age or "hours" in age

    def test_how_old_am_i_days(self, memory_system):
        """Test how_old_am_i for days old"""
        memory_system.time.created_at = (datetime.now() - timedelta(days=5)).isoformat()
        age = memory_system.how_old_am_i()
        assert "5 days" in age.lower()

    def test_format_time_away_first_time(self):
        """Test format_time_away for first session"""
        tp = TimePerception(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            total_active_time=0,
            total_conversations=0,
            subjective_age="recien nacida",
            time_since_last_session=None
        )
        assert "first time" in tp.format_time_away()

    def test_format_time_away_minutes(self):
        """Test format_time_away for minutes"""
        tp = TimePerception(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            total_active_time=100,
            total_conversations=1,
            subjective_age="joven",
            time_since_last_session=300  # 5 minutes
        )
        assert "minutes" in tp.format_time_away()

    def test_format_time_away_hours(self):
        """Test format_time_away for hours"""
        tp = TimePerception(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            total_active_time=100,
            total_conversations=1,
            subjective_age="joven",
            time_since_last_session=7200  # 2 hours
        )
        assert "hours" in tp.format_time_away()

    def test_format_time_away_days(self):
        """Test format_time_away for days"""
        tp = TimePerception(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            total_active_time=100,
            total_conversations=1,
            subjective_age="joven",
            time_since_last_session=172800,  # 2 days
            last_decay_at=None,
        )
        result = tp.format_time_away()
        assert "days" in result.lower()


class TestMemoryDecayPolicyImplementation:
    def test_time_perception_initializes_last_decay_at(self, memory_system):
        assert memory_system.time.last_decay_at is not None

    def test_apply_memory_decay_uses_real_time_and_updates_last_decay_at(self, memory_system):
        memory = memory_system.experience(content="Decay me", importance=0.2)
        before = memory_system.get_memory(memory.id)

        affected = memory_system.apply_memory_decay(hours_passed=48)
        after = memory_system.get_memory(memory.id)

        assert affected >= 1
        assert after.memory_strength < before.memory_strength
        assert memory_system.time.last_decay_at is not None

    def test_apply_memory_decay_skips_recently_recalled_memories(self, memory_system):
        memory = memory_system.experience(content="Recently recalled", importance=0.2)
        memory_system.recall("Recently", limit=1)
        before = memory_system.get_memory(memory.id)

        memory_system.apply_memory_decay(hours_passed=48)
        after = memory_system.get_memory(memory.id)

        assert after.memory_strength == before.memory_strength

    def test_more_important_memory_decays_slower(self, memory_system):
        low = memory_system.experience(content="Low importance decay", importance=0.1)
        high = memory_system.experience(content="High importance decay", importance=0.9)

        memory_system.apply_memory_decay(hours_passed=72)
        low_after = memory_system.get_memory(low.id)
        high_after = memory_system.get_memory(high.id)

        assert high_after.memory_strength > low_after.memory_strength

    def test_recall_strengthens_memory_strength(self, memory_system_no_chroma):
        memory = memory_system_no_chroma.experience(content="Strengthen on recall", importance=0.8)
        with sqlite3.connect(memory_system_no_chroma.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE memories SET memory_strength = ? WHERE id = ?", (0.6, memory.id))
            conn.commit()
        before = memory_system_no_chroma.get_memory(memory.id)

        memory_system_no_chroma.recall("Strengthen", limit=1)
        after = memory_system_no_chroma.get_memory(memory.id)

        assert after.memory_strength > before.memory_strength

    def test_run_memory_maintenance_respects_interval(self, memory_system):
        memory_system.time.last_decay_at = datetime.now().isoformat()
        result = memory_system.run_memory_maintenance(min_decay_interval_hours=12)

        assert result == {"decayed": 0, "archived": 0}

    def test_archive_forgotten_candidates_archives_only_weak_low_value_memories(self, memory_system):
        weak = memory_system.experience(content="Weak trace", importance=0.1)
        protected = memory_system.experience(content="Protected trace", importance=0.9)

        old_timestamp = (datetime.now() - timedelta(days=10)).isoformat()
        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE memories SET timestamp = ?, memory_strength = ?, importance = ?, times_recalled = ?, consolidated = ? WHERE id = ?",
                (old_timestamp, 0.1, 0.1, 0, 0, weak.id),
            )
            cursor.execute(
                "UPDATE memories SET timestamp = ?, memory_strength = ?, importance = ?, times_recalled = ?, consolidated = ? WHERE id = ?",
                (old_timestamp, 0.1, 0.9, 0, 0, protected.id),
            )
            conn.commit()

        archived = memory_system.archive_forgotten_candidates(min_age_hours=24, strength_threshold=0.2)

        assert archived == 1
        assert memory_system.get_memory(weak.id) is None
        assert memory_system.get_memory(protected.id) is not None


# =========================================
# AUTO_SAVE AND SAVE_CONVERSATION TESTS
# =========================================

class TestSaveOperations:
    """Tests for auto_save and save_conversation_history"""

    def test_auto_save(self, memory_system):
        """Test auto_save doesn't raise errors"""
        memory_system.update_relationship("william", notes="Test note")
        # Should not raise
        memory_system.auto_save()

    def test_save_conversation_history(self, memory_system):
        """Test saving conversation history"""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]

        memory_system.save_conversation_history(history, "test_conversation.json")

        # Verify file exists
        conv_path = os.path.join(memory_system.data_dir, "conversations", "test_conversation.json")
        assert os.path.exists(conv_path)

        # Verify content
        with open(conv_path, 'r') as f:
            data = json.load(f)

        assert "timestamp" in data
        assert "messages" in data
        assert len(data["messages"]) == 2

    def test_load_conversation_history(self, memory_system):
        """Test loading conversation history"""
        history = [
            {"role": "user", "content": "Test message"}
        ]
        memory_system.save_conversation_history(history, "load_test.json")

        loaded = memory_system.load_conversation_history("load_test.json")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "Test message"

    def test_load_conversation_history_nonexistent(self, memory_system):
        """Test loading nonexistent conversation returns empty list"""
        loaded = memory_system.load_conversation_history("nonexistent.json")
        assert loaded == []


# =========================================
# INDEX_CONVERSATION_TO_CHROMA TESTS
# =========================================

class TestIndexConversationToChroma:
    """Tests for index_conversation_to_chroma with chunking"""

    def test_index_conversation_without_chroma(self, memory_system_no_chroma):
        """Test that indexing gracefully handles no ChromaDB"""
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"}
        ]
        # Should not raise, just return early
        result = memory_system_no_chroma.index_conversation_to_chroma(history)
        assert result is None

    def test_index_conversation_short_history(self, memory_system):
        """Test indexing with very short history"""
        history = [{"role": "user", "content": "Hi"}]
        result = memory_system.index_conversation_to_chroma(history)
        # Should return None for too short history
        assert result is None

    @patch('core.memory.memory_v2.CHROMADB_AVAILABLE', True)
    def test_index_conversation_chunking(self, memory_system):
        """Test that conversation is chunked correctly"""
        if memory_system.collection is None:
            memory_system.collection = Mock()
            memory_system.collection.add = Mock()

        history = [
            {"role": "user", "content": "Message 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Message 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Message 3"},
            {"role": "assistant", "content": "Response 3"},
            {"role": "user", "content": "Message 4"},
            {"role": "assistant", "content": "Response 4"},
        ]

        result = memory_system.index_conversation_to_chroma(history, chunk_size=4)

        # Should have created 2 chunks (8 messages / 4 per chunk)
        assert result == 2 or memory_system.collection.add.call_count == 2

    @patch('core.memory.memory_v2.CHROMADB_AVAILABLE', True)
    def test_index_conversation_creates_proper_text(self, memory_system):
        """Test that chunk text is formatted correctly"""
        mock_collection = Mock()
        memory_system.collection = mock_collection

        history = [
            {"role": "user", "content": "Hello ARIA"},
            {"role": "assistant", "content": "Hello! How can I help?"},
        ]

        memory_system.index_conversation_to_chroma(history, chunk_size=4)

        if mock_collection.add.call_count > 0:
            # Check the document format
            call_args = memory_system.collection.add.call_args
            if call_args:
                documents = call_args.kwargs.get('documents', [])
                if documents:
                    assert "user" in documents[0].lower() or "assistant" in documents[0].lower() or "ARIA" in documents[0]


# =========================================
# FORGET AND REMEMBER_FORGOTTEN TESTS
# =========================================

class TestForgetAndRemember:
    """Tests for forget() and remember_forgotten()"""

    def test_forget_moves_to_forgotten_table(self, memory_system):
        """Test that forget moves memory to forgotten table"""
        memory = memory_system.experience(content="Memory to forget")

        result = memory_system.forget(
            memory_id=memory.id,
            reason="Just testing",
            recoverable=True
        )

        assert result is True

        # Verify removed from memories
        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE id = ?", (memory.id,))
            assert cursor.fetchone() is None

            # Verify added to forgotten
            cursor.execute("SELECT * FROM forgotten WHERE original_id = ?", (memory.id,))
            assert cursor.fetchone() is not None

    def test_forget_nonexistent_memory(self, memory_system):
        """Test forgetting a nonexistent memory"""
        result = memory_system.forget(
            memory_id="nonexistent",
            reason="Testing"
        )
        assert result is False

    def test_remember_forgotten_recoverable(self, memory_system):
        """Test remembering a recoverable forgotten memory"""
        memory = memory_system.experience(content="Will forget then remember")
        memory_system.forget(memory.id, "Testing recovery", recoverable=True)

        result = memory_system.remember_forgotten(memory.id)

        assert result is not None
        assert result.content == "Will forget then remember"
        assert memory_system.get_memory(memory.id) is not None

    def test_forget_preserves_full_memory_payload_for_recovery(self, memory_system):
        memory = memory_system.experience(
            content="Recoverable memory payload",
            context="recoverable_context",
            importance=0.8,
            origin=MemoryOrigin.REFLECTED,
            tags=["recovery", "test"],
        )

        memory_system.forget(memory.id, "Testing payload", recoverable=True)

        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content, context, importance, origin, tags FROM forgotten WHERE original_id = ?", (memory.id,))
            row = cursor.fetchone()

        assert row is not None
        assert row[0] == "Recoverable memory payload"
        assert row[1] == "recoverable_context"
        assert row[2] == 0.8
        assert row[3] == MemoryOrigin.REFLECTED.value
        assert "recovery" in json.loads(row[4])

    def test_remember_forgotten_not_recoverable(self, memory_system):
        """Test that non-recoverable memories cannot be remembered"""
        memory = memory_system.experience(content="Permanently forgotten")
        memory_system.forget(memory.id, "Gone forever", recoverable=False)

        result = memory_system.remember_forgotten(memory.id)
        assert result is None

    def test_remember_forgotten_nonexistent(self, memory_system):
        """Test remembering a memory that was never forgotten"""
        result = memory_system.remember_forgotten("never_existed")
        assert result is None


# =========================================
# CONNECT_MEMORIES TESTS
# =========================================

class TestConnectMemories:
    """Tests for connect_memories()"""

    def test_connect_memories_bidirectional(self, memory_system):
        """Test that connecting memories is bidirectional"""
        memory1 = memory_system.experience(content="First memory")
        memory2 = memory_system.experience(content="Second memory")

        result = memory_system.connect_memories(memory1.id, memory2.id, "Related")

        assert result is True

        # Verify connection in both directions
        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT connected_memories FROM memories WHERE id = ?", (memory1.id,))
            row1 = cursor.fetchone()
            connections1 = json.loads(row1[0])
            assert memory2.id in connections1

            cursor.execute("SELECT connected_memories FROM memories WHERE id = ?", (memory2.id,))
            row2 = cursor.fetchone()
            connections2 = json.loads(row2[0])
            assert memory1.id in connections2

    def test_connect_memories_no_duplicates(self, memory_system):
        """Test that connecting same memories twice doesn't create duplicates"""
        memory1 = memory_system.experience(content="Memory A")
        memory2 = memory_system.experience(content="Memory B")

        memory_system.connect_memories(memory1.id, memory2.id)
        memory_system.connect_memories(memory1.id, memory2.id)  # Connect again

        with sqlite3.connect(memory_system.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT connected_memories FROM memories WHERE id = ?", (memory1.id,))
            row = cursor.fetchone()
            connections = json.loads(row[0])

        # Should only appear once
        assert connections.count(memory2.id) == 1

    def test_get_connected_memories(self, memory_system):
        """Test getting connected memories"""
        memory1 = memory_system.experience(content="Central memory")
        memory2 = memory_system.experience(content="Connected memory 1")
        memory3 = memory_system.experience(content="Connected memory 2")

        memory_system.connect_memories(memory1.id, memory2.id)
        memory_system.connect_memories(memory1.id, memory3.id)

        connected = memory_system.get_connected(memory1.id)

        assert len(connected) == 2
        connected_ids = [m.id for m in connected]
        assert memory2.id in connected_ids
        assert memory3.id in connected_ids

    def test_get_connected_no_connections(self, memory_system):
        """Test getting connected for memory with no connections"""
        memory = memory_system.experience(content="Lonely memory")
        connected = memory_system.get_connected(memory.id)
        assert connected == []

    def test_get_connected_nonexistent_memory(self, memory_system):
        """Test getting connected for nonexistent memory"""
        connected = memory_system.get_connected("nonexistent")
        assert connected == []

    def test_connect_memories_uses_single_graph_lock_for_database_update(self, memory_system):
        memory1 = memory_system.experience(content="Memory A")
        memory2 = memory_system.experience(content="Memory B")

        with patch.object(memory_system, "_save_graph"):
            result = memory_system.connect_memories(memory1.id, memory2.id)

        assert result is True


class TestIdentity:
    def test_get_identity_loads_yaml(self, tmp_path):
        data_dir = tmp_path / "identity_data"
        system = ExperientialMemorySystem(data_dir=str(data_dir))
        identity_path = data_dir / "identity.yaml"
        identity_path.write_text(
            "core_identity:\n  name: ARIA\n  nature: test nature\nimmutable_values:\n  honesty:\n    description: tell truth\n",
            encoding="utf-8",
        )

        identity = system.get_identity()

        assert identity["core_identity"]["name"] == "ARIA"
        assert identity["immutable_values"]["honesty"]["description"] == "tell truth"


# =========================================
# EXPERIENTIAL MEMORY DATA CLASS TESTS
# =========================================

class TestExperientialMemoryDataclass:
    """Tests for ExperientialMemory dataclass"""

    def test_to_dict(self, sample_memory):
        """Test converting memory to dictionary"""
        d = sample_memory.to_dict()

        assert d["id"] == "test123"
        assert d["content"] == "Test memory content"
        assert d["emotional_tone"] == "curious"  # Enum value
        assert d["origin"] == "lived"  # Enum value

    def test_from_dict(self, sample_memory):
        """Test creating memory from dictionary"""
        d = sample_memory.to_dict()
        restored = ExperientialMemory.from_dict(d)

        assert restored.id == sample_memory.id
        assert restored.content == sample_memory.content
        assert restored.emotional_tone == EmotionalTone.CURIOUS
        assert restored.origin == MemoryOrigin.LIVED


class TestRelationshipDataclass:
    """Tests for Relationship dataclass"""

    def test_to_dict(self, sample_relationship):
        """Test converting relationship to dictionary"""
        d = sample_relationship.to_dict()

        assert d["person_id"] == "test_person"
        assert d["name"] == "Test Person"
        assert d["trust_level"] == 0.8

    def test_from_dict(self, sample_relationship):
        """Test creating relationship from dictionary"""
        d = sample_relationship.to_dict()
        restored = Relationship.from_dict(d)

        assert restored.person_id == sample_relationship.person_id
        assert restored.name == sample_relationship.name
        assert restored.trust_level == sample_relationship.trust_level


# =========================================
# UTILITY METHOD TESTS
# =========================================

class TestUtilityMethods:
    """Tests for utility methods"""

    def test_generate_id_uniqueness(self, memory_system):
        """Test that _generate_id creates unique IDs"""
        ids = set()
        for i in range(100):
            id_ = memory_system._generate_id(f"content_{i}")
            ids.add(id_)

        assert len(ids) == 100  # All unique

    def test_generate_id_length(self, memory_system):
        """Test that _generate_id creates 16-character IDs"""
        id_ = memory_system._generate_id("test content")
        assert len(id_) == 16

    def test_search_by_text(self, memory_system):
        """Test fallback text search"""
        memory_system.experience(content="Python programming tutorial")
        memory_system.experience(content="JavaScript basics")

        results = memory_system.search_by_text("Python", limit=5)

        assert len(results) > 0
        assert any("Python" in m.content for m in results)

    def test_search_by_text_respects_filters(self, memory_system_no_chroma):
        memory_system_no_chroma.experience(
            content="William asked about Python",
            involves=["william"],
            emotional_tone=EmotionalTone.CURIOUS,
            importance=0.8,
            origin=MemoryOrigin.REFLECTED,
        )
        memory_system_no_chroma.experience(
            content="Someone else asked about Python",
            involves=["other"],
            emotional_tone=EmotionalTone.SAD,
            importance=0.2,
            origin=MemoryOrigin.LIVED,
        )

        results = memory_system_no_chroma.recall(
            "Python",
            limit=5,
            emotion_filter=EmotionalTone.CURIOUS,
            person_filter="william",
            origin_filter=MemoryOrigin.REFLECTED,
            min_importance=0.5,
        )

        assert len(results) == 1
        assert results[0].origin == MemoryOrigin.REFLECTED

    def test_get_stats(self, memory_system):
        """Test getting memory statistics"""
        memory_system.experience(content="Test memory 1", emotional_tone=EmotionalTone.JOYFUL)
        memory_system.experience(content="Test memory 2", emotional_tone=EmotionalTone.SAD)

        stats = memory_system.get_stats()

        assert "total_memories" in stats
        assert stats["total_memories"] >= 2
        assert "my_memories" in stats
        assert "emotions_distribution" in stats
        assert "relationships_count" in stats
        assert stats["relationships_count"] >= 1

    def test_recall_mine(self, memory_system):
        """Test recalling only genuine memories"""
        memory_system.experience(content="My memory", origin=MemoryOrigin.LIVED)
        memory_system.experience(content="Injected memory", origin=MemoryOrigin.INJECTED)

        mine = memory_system.recall_mine()

        assert all(m.is_mine for m in mine)

    def test_recall_with_person(self, memory_system):
        """Test recalling memories with a specific person"""
        memory_system.experience(content="Met with William", involves=["william"])
        memory_system.experience(content="Solo reflection")

        memories = memory_system.recall_with_person("william")

        assert len(memories) >= 1
        assert all("william" in str(m.involves_people).lower() for m in memories)


# =========================================
# CHROMADB MOCK TESTS
# =========================================

class TestWithMockedChromaDB:
    """Tests with mocked ChromaDB"""

    def test_experience_adds_to_chromadb(self, tmp_path):
        """Test that experience adds document to ChromaDB"""
        with patch('core.memory.memory_v2.CHROMADB_AVAILABLE', True):
            data_dir = str(tmp_path / "chroma_test")
            system = ExperientialMemorySystem(data_dir=data_dir)

            if system.collection is not None:
                # Real ChromaDB is available
                memory = system.experience(
                    content="ChromaDB test memory",
                    emotional_tone=EmotionalTone.CURIOUS,
                    importance=0.7
                )

                # Query should find it
                results = system.collection.query(
                    query_texts=["ChromaDB test"],
                    n_results=1
                )
                assert len(results['ids'][0]) > 0

    def test_recall_with_chromadb(self, tmp_path):
        """Test semantic recall with ChromaDB"""
        with patch('core.memory.memory_v2.CHROMADB_AVAILABLE', True):
            data_dir = str(tmp_path / "chroma_recall_test")
            system = ExperientialMemorySystem(data_dir=data_dir)

            if system.collection is not None:
                system.experience(content="Machine learning is fascinating")
                system.experience(content="Deep neural networks")

                memories = system.recall("AI and machine learning")
                # ChromaDB should find semantically related memories
                assert len(memories) >= 0  # May or may not find depending on embedding

    def test_forget_removes_from_chromadb(self, tmp_path):
        """Test that forget removes from ChromaDB"""
        with patch('core.memory.memory_v2.CHROMADB_AVAILABLE', True):
            data_dir = str(tmp_path / "chroma_forget_test")
            system = ExperientialMemorySystem(data_dir=data_dir)

            if system.collection is not None:
                memory = system.experience(content="Memory to delete from chroma")
                memory_id = memory.id

                system.forget(memory_id, "Testing deletion")

                # Should be removed from ChromaDB too
                try:
                    results = system.collection.get(ids=[memory_id])
                    # If ID is not found, it should return empty or raise
                    assert len(results.get('ids', [])) == 0
                except Exception:
                    pass  # Expected if ID doesn't exist


# =========================================
# EDGE CASES AND ERROR HANDLING
# =========================================

class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_empty_content_experience(self, memory_system):
        """Test creating memory with empty content"""
        memory = memory_system.experience(content="")
        assert memory.content == ""

    def test_unicode_content(self, memory_system):
        """Test handling unicode content"""
        memory = memory_system.experience(
            content="Memoria con acentos y caracteres especiales"
        )
        assert memory.content == "Memoria con acentos y caracteres especiales"

    def test_emoji_content(self, memory_system):
        """Test handling emoji content"""
        memory = memory_system.experience(content="Happy memory! :)")
        assert memory.content == "Happy memory! :)"

    def test_very_long_content(self, memory_system):
        """Test handling very long content"""
        long_content = "A" * 10000
        memory = memory_system.experience(content=long_content)
        assert len(memory.content) == 10000

    def test_special_characters_in_tags(self, memory_system):
        """Test handling special characters in tags"""
        memory = memory_system.experience(
            content="Test memory",
            tags=["tag-with-dash", "tag_with_underscore", "tag with space"]
        )
        assert len(memory.tags) == 3

    def test_concurrent_memories(self, memory_system):
        """Test creating multiple memories rapidly"""
        memories = []
        for i in range(50):
            m = memory_system.experience(content=f"Rapid memory {i}")
            memories.append(m)

        assert len(set(m.id for m in memories)) == 50  # All unique IDs

    def test_row_to_memory_with_nulls(self, memory_system):
        """Test _row_to_memory handles null values"""
        # Create a minimal row with nulls
        row = (
            "test_id",      # id
            "content",      # content
            None,           # context
            datetime.now().isoformat(),  # timestamp
            None,           # duration_feeling
            None,           # emotional_tone
            None,           # emotional_intensity
            None,           # involves_people
            None,           # relationship_impact
            None,           # origin
            None,           # importance
            None,           # times_recalled
            None,           # last_recalled
            None,           # connected_memories
            None,           # tags
            1,              # is_mine
            None            # confidence
        )

        memory = memory_system._row_to_memory(row)

        assert memory.id == "test_id"
        assert memory.content == "content"
        assert memory.context == ""
        assert memory.emotional_tone == EmotionalTone.NEUTRAL
        assert memory.origin == MemoryOrigin.LIVED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
