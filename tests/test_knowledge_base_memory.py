"""Knowledge base memory persistence regression tests."""

import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory.memory_v2 import EmotionalTone
from core.skills.base import SkillContext
from core.skills.knowledge_base import KnowledgeBaseSkill


def test_knowledge_base_saves_memory_with_enum_tone():
    skill = KnowledgeBaseSkill()
    tools = MagicMock()
    tool_result = MagicMock(success=True, output="saved", error=None)
    tools.execute.return_value = tool_result
    tools.get.return_value = None
    memory = MagicMock()
    ctx = SkillContext(tools=tools, memory=memory, user="william")

    result = skill.execute("save architecture decision: use sqlite first", ctx)

    assert result.success
    memory.experience.assert_called_once()
    assert memory.experience.call_args.kwargs["emotional_tone"] == EmotionalTone.NEUTRAL
