"""Focused tests for autonomous memory persistence hooks."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.autonomy.autonomous import AutonomousActivity, AutonomousEngine


def test_autonomous_engine_persists_only_reflection_and_introspection(tmp_path):
    engine = AutonomousEngine(data_dir=str(tmp_path))
    stored = []

    engine.set_callbacks(memory=lambda activity: stored.append(activity.activity_type))

    engine._log_activity(AutonomousActivity(timestamp="2026-01-01T00:00:00", activity_type="thought", content="short"))
    engine._log_activity(AutonomousActivity(timestamp="2026-01-01T00:01:00", activity_type="reflection", content="A substantive reflection worth keeping"))
    engine._log_activity(AutonomousActivity(timestamp="2026-01-01T00:02:00", activity_type="introspection", content="A substantive introspection worth keeping"))

    assert stored == ["reflection", "introspection"]
