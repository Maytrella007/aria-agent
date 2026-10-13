"""Runtime maintenance tests for SessionManager wake-up flow."""

import os
import sys
from unittest.mock import Mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.interaction.session_manager import SessionManager


def test_wake_up_runs_memory_maintenance_and_recovers_history():
    memory = Mock()
    memory.load_conversation_history.return_value = [
        {"role": "user", "content": "hola"},
        {"role": "assistant", "content": "hola!"},
    ]
    continuity = Mock()
    continuity.wake_up.return_value = Mock(time_asleep=0, changes_summary="", changes_detected=[])
    awareness = Mock()
    initiative = Mock()
    initiative.on_session_start.return_value = ""
    existential = Mock()
    existential.is_paused.return_value = False

    session = SessionManager(memory, continuity, awareness, initiative, existential)
    conversation_history = []

    report = session.wake_up(conversation_history)

    assert report is continuity.wake_up.return_value
    memory.session_start.assert_called_once()
    memory.run_memory_maintenance.assert_called_once()
    assert conversation_history == memory.load_conversation_history.return_value


def test_auto_save_runs_periodic_memory_maintenance():
    memory = Mock()
    continuity = Mock()
    awareness = Mock()
    initiative = Mock()
    initiative.on_session_start.return_value = ""
    existential = Mock()
    existential.is_paused.return_value = False

    session = SessionManager(memory, continuity, awareness, initiative, existential)
    session.do_auto_save([{"role": "user", "content": "hello"}])

    memory.run_memory_maintenance.assert_called_once_with(min_decay_interval_hours=12)
    memory.auto_save.assert_called_once()
    memory.save_conversation_history.assert_called_once()
