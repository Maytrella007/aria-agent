"""Runtime-facing tests for MemoryIngestor emotion detection."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory.memory_ingestor import MemoryIngestor
from core.memory.memory_v2 import EmotionalTone


def test_detect_emotion_maps_gratitude_to_supported_enum():
    ingestor = MemoryIngestor(memory=None, tools=None, EmotionalTone=EmotionalTone)
    assert ingestor.detect_emotion("Gracias por tu ayuda") == EmotionalTone.CONNECTED


def test_detect_emotion_maps_frustration_to_supported_enum():
    ingestor = MemoryIngestor(memory=None, tools=None, EmotionalTone=EmotionalTone)
    assert ingestor.detect_emotion("Esto es muy frustrante y annoying") == EmotionalTone.ANGRY


def test_detect_emotion_maps_hope_to_supported_enum():
    ingestor = MemoryIngestor(memory=None, tools=None, EmotionalTone=EmotionalTone)
    assert ingestor.detect_emotion("I feel hopeful and optimistic") == EmotionalTone.INSPIRED
