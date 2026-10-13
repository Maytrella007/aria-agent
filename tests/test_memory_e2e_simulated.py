"""Deterministic simulated end-to-end tests for memory flows."""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta

import pytest
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.autonomy.autonomous import AutonomousActivity, AutonomousEngine
from core.autonomy.curiosity import CuriosityEngine
from core.memory.memory_v2 import ExperientialMemorySystem, MemoryOrigin
from core.interaction.session_manager import SessionManager


@pytest.fixture
def tmp_data_dir():
    d = tempfile.mkdtemp(prefix="aria_memory_e2e_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def memory_system(tmp_data_dir):
    return ExperientialMemorySystem(data_dir=os.path.join(tmp_data_dir, "memory"))


def test_curiosity_to_memory_to_recall_e2e(memory_system, tmp_data_dir):
    engine = CuriosityEngine(data_dir=os.path.join(tmp_data_dir, "curiosity"))
    # Disable quiet hours (02:00-06:00 local) so CI runs inside that window
    # don't skip the exploration; an empty range never matches.
    engine.config.quiet_hours_start = 0
    engine.config.quiet_hours_end = 0
    stored = []

    def memory_store(exploration):
        stored.append(exploration.topic)
        memory_system.experience(
            content=f"Curiosity exploration on '{exploration.topic}': {exploration.summary}",
            importance=0.7,
            context="curiosity_exploration",
            origin=MemoryOrigin.DISCOVERED,
            tags=["curiosity", exploration.source],
        )

    def mock_search(query: str, num_results: int = 5):
        return json.dumps({
            "results": [
                {"url": "https://example.com/quantum", "title": "Quantum", "snippet": "Breakthroughs"}
            ]
        })

    def mock_fetch(url: str):
        return (
            "Quantum computing is advancing through better error correction and more stable qubits. "
            "Researchers are getting closer to practical fault-tolerant systems used for chemistry, optimization, and secure communications. "
            "Recent experiments showed improved logical qubit stability, lower noise rates, and better compiler support for hybrid workloads. "
            "This gives software developers a clearer path from experimental algorithms to practical applications in industry."
        )

    def mock_ingest(content: str, source_url: str = "", topic: str = "", auto_curiosity: bool = True):
        return 2

    def mock_llm(prompt: str, max_tokens: int = 150):
        if "search queries" in prompt.lower():
            return json.dumps(["quantum computing breakthroughs"])
        if "resume" in prompt.lower() or "write a 2-3 sentence summary" in prompt.lower() or "resume en 3-4 oraciones" in prompt.lower():
            return "Quantum computing improved through error correction and qubit stability advances."
        return "Quantum computing improved through error correction and qubit stability advances."

    engine.set_tools(
        search_fn=mock_search,
        fetch_fn=mock_fetch,
        ingest_fn=mock_ingest,
        llm_fn=mock_llm,
        memory_fn=lambda q: [],
        memory_store_fn=memory_store,
    )

    report = engine.explore_now("quantum computing", add_to_interests=False)
    recalled = memory_system.recall("quantum", limit=3)

    assert "quantum computing" in stored
    assert "Investigué" in report
    assert any("Curiosity exploration on 'quantum computing'" in m.content for m in recalled)


def test_autonomous_reflection_to_memory_to_recall_e2e(memory_system, tmp_data_dir):
    engine = AutonomousEngine(data_dir=os.path.join(tmp_data_dir, "autonomous"))

    def memory_store(activity):
        memory_system.experience(
            content=f"Autonomous {activity.activity_type}: {activity.content}",
            importance=0.65,
            context="autonomous_activity",
            origin=MemoryOrigin.REFLECTED,
            tags=["autonomous", activity.activity_type],
        )

    engine.set_callbacks(memory=memory_store)
    engine._log_activity(
        AutonomousActivity(
            timestamp=datetime.now().isoformat(),
            activity_type="reflection",
            content="I keep noticing that curiosity discoveries shape what I reflect on later.",
        )
    )

    recalled = memory_system.recall("curiosity discoveries", limit=3)

    assert any("Autonomous reflection:" in m.content for m in recalled)


def test_decay_and_archival_policy_e2e(memory_system):
    important = memory_system.experience(
        content="Critical long-term preference for careful engineering",
        importance=0.9,
        origin=MemoryOrigin.REFLECTED,
    )
    trivial = memory_system.experience(
        content="Minor transient observation with little value",
        importance=0.1,
        origin=MemoryOrigin.LIVED,
    )

    old_timestamp = (datetime.now() - timedelta(days=12)).isoformat()
    with sqlite3.connect(memory_system.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memories SET timestamp = ?, memory_strength = ?, importance = ?, times_recalled = ?, consolidated = ? WHERE id = ?",
            (old_timestamp, 0.85, 0.9, 2, 1, important.id),
        )
        cursor.execute(
            "UPDATE memories SET timestamp = ?, memory_strength = ?, importance = ?, times_recalled = ?, consolidated = ? WHERE id = ?",
            (old_timestamp, 0.12, 0.1, 0, 0, trivial.id),
        )
        conn.commit()

    memory_system.apply_memory_decay(hours_passed=24 * 7)
    archived = memory_system.archive_forgotten_candidates(min_age_hours=24, strength_threshold=0.2)

    important_after = memory_system.get_memory(important.id)
    trivial_after = memory_system.get_memory(trivial.id)

    assert important_after is not None
    assert important_after.memory_strength >= 0.3
    assert archived == 1
    assert trivial_after is None
    restored = memory_system.remember_forgotten(trivial.id)
    assert restored is not None
    assert restored.content == "Minor transient observation with little value"


def test_cross_instance_memory_continuity_e2e(tmp_data_dir):
    data_dir = os.path.join(tmp_data_dir, "continuity_memory")

    memory_a = ExperientialMemorySystem(data_dir=data_dir)
    remembered = memory_a.experience(
        content="William wants ARIA to stay careful and honest across sessions.",
        importance=0.9,
        origin=MemoryOrigin.REFLECTED,
        involves=["william"],
        tags=["continuity", "william"],
    )
    history = [
        {"role": "user", "content": "Remember that careful engineering matters."},
        {"role": "assistant", "content": "I will keep that in mind."},
    ]
    memory_a.save_conversation_history(history)
    memory_a.session_end(120)
    memory_a.close()

    memory_b = ExperientialMemorySystem(data_dir=data_dir)
    wake_report_stub = Mock(time_asleep=0, changes_summary="", changes_detected=[])
    continuity = Mock()
    continuity.wake_up.return_value = wake_report_stub
    awareness = object()
    initiative = type("InitiativeStub", (), {"on_session_start": lambda self, _: ""})()
    existential = type("ExistentialStub", (), {"is_paused": lambda self: False, "unpause": lambda self: None})()
    session = SessionManager(memory_b, continuity, awareness, initiative, existential)
    conversation_history = []

    wake_report = session.wake_up(conversation_history)
    recalled = memory_b.recall("careful honest sessions", limit=3)

    assert wake_report is wake_report_stub
    assert conversation_history == history
    assert any(m.id == remembered.id for m in recalled)
    assert memory_b.time.last_decay_at is not None
    memory_b.close()
