"""Regression tests for forge logging without SelfModifier."""

import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cognition.modification_log import ModificationLogger
from core.tools.forge_skill_tool import ForgeSkillTool
from core.tools.forge_tool import ForgeToolTool


class TestForgeLogging:
    def test_shared_modification_logger_records_summary_and_full_entry(self, tmp_path):
        log_path = tmp_path / "data" / "modification_log.yaml"
        logger = ModificationLogger(str(log_path))

        logger.record_dict(
            {
                "id": "abc123",
                "timestamp": "2026-01-01T00:00:00",
                "target_file": "core/tools/forged/demo.py",
                "modification_type": "forge",
                "original_content_hash": "",
                "new_content_hash": "",
                "reason": "test",
                "initiated_by": "aria",
                "success": True,
                "error_message": None,
            },
            original_content=None,
            new_content="print('demo')\n",
        )

        with open(log_path, "r", encoding="utf-8") as f:
            summary = yaml.safe_load(f)
        with open(str(log_path).replace(".yaml", "_full.yaml"), "r", encoding="utf-8") as f:
            full = yaml.safe_load(f)

        assert summary["total_modifications"] == 1
        assert summary["modifications"][0]["id"] == "abc123"
        assert full["entries"][0]["new_content"] == "print('demo')\n"

    def test_forge_tool_logs_without_self_modifier(self, tmp_path):
        log_path = tmp_path / "data" / "modification_log.yaml"
        tool = ForgeToolTool(context={})

        tool._log_creation("demo_tool", "print('demo')\n", "needed for testing", log_path=str(log_path))

        with open(log_path, "r", encoding="utf-8") as f:
            summary = yaml.safe_load(f)

        entry = summary["modifications"][0]
        assert entry["modification_type"] == "forge"
        assert entry["target_file"] == "core/tools/forged/demo_tool.py"
        assert entry["reason"] == "[forge_tool] needed for testing"

    def test_forge_skill_logs_without_self_modifier(self, tmp_path):
        log_path = tmp_path / "data" / "modification_log.yaml"
        skill_file = tmp_path / "demo_skill.yaml"
        skill_file.write_text("name: demo_skill\n", encoding="utf-8")
        tool = ForgeSkillTool(context={})

        tool._log_creation("demo_skill", str(skill_file), "needed for testing", log_path=str(log_path))

        with open(log_path, "r", encoding="utf-8") as f:
            summary = yaml.safe_load(f)
        with open(str(log_path).replace(".yaml", "_full.yaml"), "r", encoding="utf-8") as f:
            full = yaml.safe_load(f)

        entry = summary["modifications"][0]
        assert entry["modification_type"] == "forge_skill"
        assert entry["target_file"] == "core/skills/demo_skill.yaml"
        assert full["entries"][0]["new_content"] == "name: demo_skill\n"
