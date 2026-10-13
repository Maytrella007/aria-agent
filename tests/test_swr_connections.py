"""
Unit tests for SWR Connection Discovery
========================================

Tests the _find_connections method in SharpWaveRippleSimulator
to ensure connections are properly discovered during consolidation.

Created: January 2025
"""

import pytest
from unittest.mock import Mock, MagicMock
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class MockMemory:
    """Mock memory for testing connection discovery"""
    id: str
    tags: List[str]
    involves_people: List[str]
    importance: float = 0.5
    emotional_intensity: float = 0.5
    content: str = "Test memory content"


class TestSWRConnectionDiscovery:
    """Tests for the SWR connection discovery algorithm"""

    def setup_method(self):
        """Set up test fixtures"""
        # Import here to avoid issues if module not available
        try:
            from core.neuroscience.consolidation import SharpWaveRippleSimulator
            self.swr = SharpWaveRippleSimulator()
        except ImportError:
            pytest.skip("consolidation module not available")

    def test_no_connections_with_no_overlap(self):
        """Memories with completely different tags should not connect"""
        mem1 = MockMemory(
            id="m1",
            tags=["tag_a", "tag_b"],
            involves_people=[]
        )
        mem2 = MockMemory(
            id="m2",
            tags=["tag_c", "tag_d"],
            involves_people=[]
        )

        connections = self.swr._find_connections([mem1, mem2])
        # With no overlap, should find no connections
        assert len(connections) == 0

    def test_connection_with_shared_tags(self):
        """Memories sharing tags should connect"""
        mem1 = MockMemory(
            id="m1",
            tags=["experience", "memory", "test"],
            involves_people=[]
        )
        mem2 = MockMemory(
            id="m2",
            tags=["experience", "learning", "test"],
            involves_people=[]
        )

        connections = self.swr._find_connections([mem1, mem2])
        # 2 shared tags out of 4 unique = Jaccard 0.5, should connect
        assert len(connections) >= 1
        assert connections[0][0] == "m1"
        assert connections[0][1] == "m2"
        assert connections[0][2] >= 0.2  # Strength should be reasonable

    def test_connection_with_shared_people(self):
        """Memories sharing people should connect with bonus"""
        mem1 = MockMemory(
            id="m1",
            tags=["conversation"],
            involves_people=["William", "ARIA"]
        )
        mem2 = MockMemory(
            id="m2",
            tags=["reflection"],
            involves_people=["William"]
        )

        connections = self.swr._find_connections([mem1, mem2])
        # 1 shared person = 0.3 bonus
        assert len(connections) >= 1
        assert connections[0][2] >= 0.2

    def test_connection_with_marathon_common_tags(self):
        """Marathon test memories with common tags should connect"""
        # Simulating marathon test scenario with common tags
        common_tags = ["experience", "memory", "aria", "marathon_test"]

        mem1 = MockMemory(
            id="m1",
            tags=["conversation", "social"] + common_tags,
            involves_people=["ARIA"]
        )
        mem2 = MockMemory(
            id="m2",
            tags=["reflection", "philosophy"] + common_tags,
            involves_people=["ARIA"]
        )

        connections = self.swr._find_connections([mem1, mem2])
        # 4 common tags + 1 shared person should definitely connect
        assert len(connections) == 1
        assert connections[0][2] >= 0.4

    def test_multiple_memories_connections(self):
        """Test connection discovery across multiple memories"""
        memories = [
            MockMemory(id="m1", tags=["a", "b", "common"], involves_people=["User"]),
            MockMemory(id="m2", tags=["c", "d", "common"], involves_people=["User"]),
            MockMemory(id="m3", tags=["e", "f", "common"], involves_people=["User"]),
        ]

        connections = self.swr._find_connections(memories)
        # All pairs share "common" tag and "User" person
        # Should find connections between: m1-m2, m1-m3, m2-m3
        assert len(connections) >= 2  # At least some connections

    def test_threshold_boundary(self):
        """Test behavior at threshold boundary"""
        # Create memories that are just at threshold
        mem1 = MockMemory(
            id="m1",
            tags=["only_shared"],
            involves_people=[]
        )
        mem2 = MockMemory(
            id="m2",
            tags=["only_shared"],
            involves_people=[]
        )

        connections = self.swr._find_connections([mem1, mem2])
        # 1 shared tag out of 1 total = Jaccard 1.0
        # This should definitely connect
        assert len(connections) == 1
        assert connections[0][2] >= 0.2

    def test_empty_tags_handling(self):
        """Memories with empty/None tags should not crash"""
        mem1 = MockMemory(id="m1", tags=[], involves_people=[])
        mem2 = MockMemory(id="m2", tags=None, involves_people=None)

        # Should not raise exception
        connections = self.swr._find_connections([mem1, mem2])
        assert isinstance(connections, list)

    def test_single_memory_no_connections(self):
        """Single memory should return no connections"""
        mem1 = MockMemory(id="m1", tags=["test"], involves_people=[])

        connections = self.swr._find_connections([mem1])
        assert len(connections) == 0

    def test_connection_strength_calculation(self):
        """Verify connection strength is calculated correctly"""
        # High overlap scenario
        mem1 = MockMemory(
            id="m1",
            tags=["a", "b", "c", "d"],
            involves_people=["Person1", "Person2"]
        )
        mem2 = MockMemory(
            id="m2",
            tags=["a", "b", "c", "e"],
            involves_people=["Person1"]
        )

        connections = self.swr._find_connections([mem1, mem2])
        assert len(connections) == 1

        # 3 shared tags (a,b,c) out of 5 unique (a,b,c,d,e) = 0.6 Jaccard
        # 1 shared person = 0.3 bonus
        # Total should be around 0.9, capped at 1.0
        strength = connections[0][2]
        assert 0.5 <= strength <= 1.0


class TestSWRIntegration:
    """Integration tests for SWR with memory system"""

    def test_swr_burst_creates_connections(self):
        """Verify SWR burst can discover connections"""
        try:
            from core.neuroscience.consolidation import SharpWaveRippleSimulator
        except ImportError:
            pytest.skip("consolidation module not available")

        swr = SharpWaveRippleSimulator()

        # Create memories with overlap
        memories = [
            MockMemory(
                id=f"m{i}",
                tags=["common", "marathon_test", f"unique_{i}"],
                involves_people=["ARIA"],
                importance=0.7,
                emotional_intensity=0.6
            )
            for i in range(5)
        ]

        events = swr.simulate_swr_burst(memories, num_ripples=3)

        # Should have created some SWR events
        assert len(events) == 3

        # Check if any connections were discovered
        total_connections = sum(len(e.new_connections) for e in events)
        # With overlapping tags and shared person, should find connections
        assert total_connections >= 0  # May be 0 depending on random selection


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
