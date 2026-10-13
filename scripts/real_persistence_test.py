#!/usr/bin/env python3
"""
ARIA Real Persistence Test
===========================

A multi-day test that validates ARIA's memory system persists correctly
across real process restarts and time gaps.

Unlike simulated tests, this script:
- Actually stops and restarts the Python process
- Waits real hours between phases
- Verifies SQLite/ChromaDB persistence after cold starts
- Tests memory consolidation over actual elapsed time

Usage:
    # Start the test (Phase 1)
    python scripts/real_persistence_test.py --start

    # Continue after waiting (auto-detects phase)
    python scripts/real_persistence_test.py --continue

    # Check current status
    python scripts/real_persistence_test.py --status

    # Generate report at any time
    python scripts/real_persistence_test.py --report

    # Reset and start over
    python scripts/real_persistence_test.py --reset

Phases:
    Phase 1 (Hour 0):     Create test memories, verify immediate recall
    Phase 2 (Hour 8+):    Restart, verify persistence, add more memories
    Phase 3 (Hour 16+):   Restart, verify all, test consolidation
    Phase 4 (Hour 24+):   Final verification and comprehensive report

Author: ARIA Development Team
Version: 1.0.0
Created: 2025-01-03
"""

import os
import sys
import json
import time
import argparse
import hashlib
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum
import traceback

# Add project root to path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_ROOT)

# =============================================================================
# CONFIGURATION
# =============================================================================

class TestPhase(Enum):
    """Test phases"""
    NOT_STARTED = "not_started"
    PHASE_1_COMPLETE = "phase_1_complete"
    PHASE_2_COMPLETE = "phase_2_complete"
    PHASE_3_COMPLETE = "phase_3_complete"
    PHASE_4_COMPLETE = "phase_4_complete"
    FINISHED = "finished"


@dataclass
class TestConfig:
    """Test configuration"""
    # Timing (in hours)
    phase_2_min_wait: float = 8.0   # Minimum hours before phase 2
    phase_3_min_wait: float = 8.0   # Additional hours before phase 3
    phase_4_min_wait: float = 8.0   # Additional hours before phase 4

    # For quick testing, use these instead:
    # phase_2_min_wait: float = 0.1   # 6 minutes
    # phase_3_min_wait: float = 0.1
    # phase_4_min_wait: float = 0.1

    # Test data directory
    test_data_dir: str = "data/persistence_test"
    state_file: str = "data/persistence_test/test_state.json"
    report_file: str = "data/persistence_test/persistence_report.json"


@dataclass
class MemoryTestCase:
    """A test case for memory persistence"""
    id: str
    content: str
    emotional_tone: str
    importance: float
    tags: List[str]
    involves: List[str]
    phase_created: int
    expected_recall_keywords: List[str]


@dataclass
class TestState:
    """Persistent state across test runs"""
    test_id: str
    started_at: str
    current_phase: str
    phase_1_completed_at: Optional[str] = None
    phase_2_completed_at: Optional[str] = None
    phase_3_completed_at: Optional[str] = None
    phase_4_completed_at: Optional[str] = None

    # Memory IDs created in each phase
    phase_1_memory_ids: List[str] = field(default_factory=list)
    phase_2_memory_ids: List[str] = field(default_factory=list)
    phase_3_memory_ids: List[str] = field(default_factory=list)

    # Verification results
    phase_2_verification: Dict[str, Any] = field(default_factory=dict)
    phase_3_verification: Dict[str, Any] = field(default_factory=dict)
    phase_4_verification: Dict[str, Any] = field(default_factory=dict)

    # Errors encountered
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> 'TestState':
        return cls(**d)


# =============================================================================
# TEST MEMORIES - Specific content we'll verify persists
# =============================================================================

PHASE_1_MEMORIES = [
    MemoryTestCase(
        id="p1_user_info",
        content="El usuario de prueba se llama Carlos Martinez, es ingeniero de software "
                "en Barcelona, y tiene un gato llamado Pixel que le gusta dormir en el teclado.",
        emotional_tone="joyful",
        importance=0.9,
        tags=["usuario", "personal", "persistencia_test", "fase1"],
        involves=["carlos_martinez"],
        phase_created=1,
        expected_recall_keywords=["Carlos", "Barcelona", "Pixel", "gato", "teclado"]
    ),
    MemoryTestCase(
        id="p1_project_info",
        content="Carlos está trabajando en un proyecto llamado 'NeuralGarden' que usa "
                "redes neuronales para optimizar el crecimiento de plantas en invernaderos. "
                "El proyecto usa Python y TensorFlow.",
        emotional_tone="curious",
        importance=0.85,
        tags=["proyecto", "tecnologia", "persistencia_test", "fase1"],
        involves=["carlos_martinez"],
        phase_created=1,
        expected_recall_keywords=["NeuralGarden", "plantas", "invernadero", "TensorFlow"]
    ),
    MemoryTestCase(
        id="p1_emotional",
        content="Carlos me contó que su abuela falleció el mes pasado. Ella era jardinera "
                "y fue quien le inspiró el proyecto NeuralGarden. Es un tema emotivo para él.",
        emotional_tone="sad",
        importance=0.95,
        tags=["emocional", "familia", "persistencia_test", "fase1"],
        involves=["carlos_martinez"],
        phase_created=1,
        expected_recall_keywords=["abuela", "jardinera", "NeuralGarden", "inspiró"]
    ),
    MemoryTestCase(
        id="p1_preference",
        content="A Carlos le gusta el café con leche de avena, odia las reuniones antes "
                "de las 10am, y su color favorito es el verde esmeralda.",
        emotional_tone="neutral",
        importance=0.6,
        tags=["preferencias", "personal", "persistencia_test", "fase1"],
        involves=["carlos_martinez"],
        phase_created=1,
        expected_recall_keywords=["café", "avena", "10am", "verde esmeralda"]
    ),
]

PHASE_2_MEMORIES = [
    MemoryTestCase(
        id="p2_update",
        content="Carlos me cuenta que NeuralGarden tuvo su primera prueba exitosa. "
                "Los tomates crecieron un 23% más rápido que el grupo de control. "
                "Está muy emocionado con los resultados.",
        emotional_tone="joyful",
        importance=0.9,
        tags=["proyecto", "exito", "persistencia_test", "fase2"],
        involves=["carlos_martinez"],
        phase_created=2,
        expected_recall_keywords=["tomates", "23%", "control", "exitosa"]
    ),
    MemoryTestCase(
        id="p2_challenge",
        content="Surgió un problema: el invernadero tiene plagas de áfidos que están "
                "afectando las mediciones. Carlos necesita resolver esto antes de la "
                "presentación a inversores el 15 de febrero.",
        emotional_tone="anxious",
        importance=0.85,
        tags=["problema", "proyecto", "persistencia_test", "fase2"],
        involves=["carlos_martinez"],
        phase_created=2,
        expected_recall_keywords=["áfidos", "plagas", "inversores", "15 de febrero"]
    ),
]

PHASE_3_MEMORIES = [
    MemoryTestCase(
        id="p3_resolution",
        content="Carlos resolvió el problema de los áfidos usando mariquitas como control "
                "biológico. Fue idea de Pixel... bueno, el gato se comió una mariquita y "
                "Carlos investigó sobre ellas. La presentación está lista.",
        emotional_tone="joyful",
        importance=0.9,
        tags=["solucion", "proyecto", "persistencia_test", "fase3"],
        involves=["carlos_martinez"],
        phase_created=3,
        expected_recall_keywords=["mariquitas", "Pixel", "biológico", "presentación"]
    ),
    MemoryTestCase(
        id="p3_reflection",
        content="Reflexionamos sobre cómo el proyecto NeuralGarden conecta con el legado "
                "de su abuela. Carlos dijo que siente que ella estaría orgullosa. "
                "Fue un momento muy significativo en nuestra conversación.",
        emotional_tone="peaceful",
        importance=0.95,
        tags=["reflexion", "emocional", "persistencia_test", "fase3"],
        involves=["carlos_martinez"],
        phase_created=3,
        expected_recall_keywords=["legado", "abuela", "orgullosa", "significativo"]
    ),
]


# =============================================================================
# MAIN TEST CLASS
# =============================================================================

class RealPersistenceTest:
    """
    Orchestrates the multi-day persistence test.
    """

    def __init__(self, config: TestConfig = None):
        self.config = config or TestConfig()
        self.state: Optional[TestState] = None
        self.memory_system = None

        # Ensure test directory exists
        os.makedirs(self.config.test_data_dir, exist_ok=True)

    def _log(self, message: str, level: str = "INFO"):
        """Log with timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prefix = {"INFO": "[INFO]", "WARN": "[WARN]", "ERROR": "[ERROR]", "OK": "[OK]"}
        print(f"{prefix.get(level, '[???]')} [{timestamp}] {message}")

    def _load_state(self) -> Optional[TestState]:
        """Load test state from file"""
        if os.path.exists(self.config.state_file):
            try:
                with open(self.config.state_file, 'r') as f:
                    data = json.load(f)
                return TestState.from_dict(data)
            except Exception as e:
                self._log(f"Error loading state: {e}", "ERROR")
        return None

    def _save_state(self):
        """Save test state to file"""
        if self.state:
            with open(self.config.state_file, 'w') as f:
                json.dump(self.state.to_dict(), f, indent=2)

    def _init_memory_system(self):
        """Initialize ARIA's memory system"""
        if self.memory_system is not None:
            return True

        try:
            from core.memory.memory_v2 import (
                ExperientialMemorySystem,
                EmotionalTone,
                MemoryOrigin
            )

            # Store references for later use
            self._EmotionalTone = EmotionalTone
            self._MemoryOrigin = MemoryOrigin

            data_dir = os.path.join(PROJECT_ROOT, "data")
            self.memory_system = ExperientialMemorySystem(data_dir)

            self._log("Memory system initialized successfully", "OK")
            return True

        except Exception as e:
            self._log(f"Failed to initialize memory system: {e}", "ERROR")
            traceback.print_exc()
            return False

    def _get_emotional_tone(self, tone_str: str):
        """Convert string to EmotionalTone enum"""
        tone_map = {
            "joyful": self._EmotionalTone.JOYFUL,
            "sad": self._EmotionalTone.SAD,
            "curious": self._EmotionalTone.CURIOUS,
            "anxious": self._EmotionalTone.ANXIOUS,
            "peaceful": self._EmotionalTone.PEACEFUL,
            "neutral": self._EmotionalTone.NEUTRAL,
        }
        return tone_map.get(tone_str, self._EmotionalTone.NEUTRAL)

    def _create_memory(self, test_case: MemoryTestCase) -> Optional[str]:
        """Create a memory and return its ID"""
        try:
            memory = self.memory_system.experience(
                content=test_case.content,
                emotional_tone=self._get_emotional_tone(test_case.emotional_tone),
                emotional_intensity=0.7,
                importance=test_case.importance,
                tags=test_case.tags,
                involves=test_case.involves,
                context=f"Persistence test phase {test_case.phase_created}"
            )
            self._log(f"Created memory: {test_case.id} -> {memory.id}", "OK")
            return memory.id
        except Exception as e:
            self._log(f"Failed to create memory {test_case.id}: {e}", "ERROR")
            return None

    def _verify_memory_exists(self, memory_id: str) -> Tuple[bool, Optional[Any]]:
        """Check if a memory exists in the database"""
        try:
            # Use recall_recent to check if memory is accessible
            recent = self.memory_system.recall_recent(limit=100)
            for m in recent:
                if m.id == memory_id:
                    return True, m

            # Also check via direct SQL
            import sqlite3
            with sqlite3.connect(self.memory_system.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
                row = cursor.fetchone()
                if row:
                    return True, row

            return False, None
        except Exception as e:
            self._log(f"Error verifying memory {memory_id}: {e}", "ERROR")
            return False, None

    def _verify_recall(self, test_case: MemoryTestCase) -> Dict[str, Any]:
        """Verify a memory can be recalled and contains expected content"""
        result = {
            "test_case_id": test_case.id,
            "passed": False,
            "keywords_found": [],
            "keywords_missing": [],
            "recall_content": None,
            "error": None
        }

        try:
            # Try semantic recall
            memories = self.memory_system.recall(test_case.content[:50], limit=10)

            # Find matching memory
            found_memory = None
            for m in memories:
                # Check if any expected keywords are in the content
                matches = sum(1 for kw in test_case.expected_recall_keywords
                             if kw.lower() in m.content.lower())
                if matches >= len(test_case.expected_recall_keywords) * 0.5:
                    found_memory = m
                    break

            if found_memory:
                result["recall_content"] = found_memory.content[:200]

                # Check keywords
                for kw in test_case.expected_recall_keywords:
                    if kw.lower() in found_memory.content.lower():
                        result["keywords_found"].append(kw)
                    else:
                        result["keywords_missing"].append(kw)

                # Pass if we found at least 60% of keywords
                recall_rate = len(result["keywords_found"]) / len(test_case.expected_recall_keywords)
                result["passed"] = recall_rate >= 0.6
                result["recall_rate"] = recall_rate
            else:
                result["error"] = "Memory not found in recall results"

        except Exception as e:
            result["error"] = str(e)

        return result

    def _hours_since(self, timestamp_str: str) -> float:
        """Calculate hours since a timestamp"""
        if not timestamp_str:
            return 0
        ts = datetime.fromisoformat(timestamp_str)
        delta = datetime.now() - ts
        return delta.total_seconds() / 3600

    # =========================================================================
    # PHASE IMPLEMENTATIONS
    # =========================================================================

    def start_test(self) -> bool:
        """Start a new persistence test (Phase 1)"""
        self._log("=" * 60)
        self._log("STARTING REAL PERSISTENCE TEST")
        self._log("=" * 60)

        # Check for existing test
        existing = self._load_state()
        if existing and existing.current_phase != TestPhase.FINISHED.value:
            self._log(f"Existing test found in {existing.current_phase}", "WARN")
            self._log("Use --continue to resume or --reset to start fresh", "WARN")
            return False

        # Initialize memory system
        if not self._init_memory_system():
            return False

        # Create new test state
        test_id = hashlib.sha256(datetime.now().isoformat().encode()).hexdigest()[:12]
        self.state = TestState(
            test_id=test_id,
            started_at=datetime.now().isoformat(),
            current_phase=TestPhase.NOT_STARTED.value
        )

        self._log(f"Test ID: {test_id}")
        self._log("")

        # === PHASE 1: Create initial memories ===
        self._log("PHASE 1: Creating test memories...")
        self._log("-" * 40)

        memory_ids = []
        for test_case in PHASE_1_MEMORIES:
            mem_id = self._create_memory(test_case)
            if mem_id:
                memory_ids.append(mem_id)

        self.state.phase_1_memory_ids = memory_ids
        self._log(f"Created {len(memory_ids)}/{len(PHASE_1_MEMORIES)} memories")

        # Verify immediate recall
        self._log("")
        self._log("Verifying immediate recall...")
        immediate_results = []
        for test_case in PHASE_1_MEMORIES:
            result = self._verify_recall(test_case)
            immediate_results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            self._log(f"  {test_case.id}: {status}")

        # Update state
        self.state.current_phase = TestPhase.PHASE_1_COMPLETE.value
        self.state.phase_1_completed_at = datetime.now().isoformat()
        self._save_state()

        # Summary
        passed = sum(1 for r in immediate_results if r["passed"])
        self._log("")
        self._log("=" * 60)
        self._log(f"PHASE 1 COMPLETE: {passed}/{len(PHASE_1_MEMORIES)} immediate recalls passed")
        self._log(f"Next phase available after: {self.config.phase_2_min_wait} hours")
        self._log("")
        self._log(">>> STOP THE PROCESS NOW <<<")
        self._log(">>> Wait at least 8 hours (or overnight) <<<")
        self._log(">>> Then run: python scripts/real_persistence_test.py --continue <<<")
        self._log("=" * 60)

        return True

    def continue_test(self) -> bool:
        """Continue the test from where we left off"""
        self.state = self._load_state()

        if not self.state:
            self._log("No test in progress. Use --start to begin.", "ERROR")
            return False

        current = self.state.current_phase
        self._log(f"Resuming test {self.state.test_id} from {current}")

        if not self._init_memory_system():
            return False

        # Determine which phase to run
        if current == TestPhase.PHASE_1_COMPLETE.value:
            return self._run_phase_2()
        elif current == TestPhase.PHASE_2_COMPLETE.value:
            return self._run_phase_3()
        elif current == TestPhase.PHASE_3_COMPLETE.value:
            return self._run_phase_4()
        elif current == TestPhase.FINISHED.value:
            self._log("Test already finished. Use --report to see results.")
            return True
        else:
            self._log(f"Unknown phase: {current}", "ERROR")
            return False

    def _run_phase_2(self) -> bool:
        """Phase 2: Verify phase 1 persistence + add more memories"""
        hours_waited = self._hours_since(self.state.phase_1_completed_at)

        self._log("=" * 60)
        self._log(f"PHASE 2: First Persistence Verification")
        self._log(f"Time since Phase 1: {hours_waited:.2f} hours")
        self._log("=" * 60)

        if hours_waited < self.config.phase_2_min_wait:
            self._log(f"Minimum wait time: {self.config.phase_2_min_wait} hours", "WARN")
            self._log(f"Please wait {self.config.phase_2_min_wait - hours_waited:.2f} more hours", "WARN")
            return False

        # === CRITICAL: Verify Phase 1 memories persisted ===
        self._log("")
        self._log("Verifying Phase 1 memories persisted across restart...")
        self._log("-" * 40)

        verification_results = {
            "hours_elapsed": hours_waited,
            "memory_existence": [],
            "recall_tests": []
        }

        # Check each Phase 1 memory
        for i, mem_id in enumerate(self.state.phase_1_memory_ids):
            exists, data = self._verify_memory_exists(mem_id)
            verification_results["memory_existence"].append({
                "memory_id": mem_id,
                "exists": exists
            })
            status = "EXISTS" if exists else "MISSING"
            self._log(f"  Memory {mem_id}: {status}")

        # Test recall of Phase 1 memories
        self._log("")
        self._log("Testing recall of Phase 1 content...")
        for test_case in PHASE_1_MEMORIES:
            result = self._verify_recall(test_case)
            verification_results["recall_tests"].append(result)
            status = "PASS" if result["passed"] else "FAIL"
            self._log(f"  {test_case.id}: {status}")
            if result.get("keywords_missing"):
                self._log(f"    Missing: {result['keywords_missing']}")

        self.state.phase_2_verification = verification_results

        # === Create Phase 2 memories ===
        self._log("")
        self._log("Creating Phase 2 memories...")
        memory_ids = []
        for test_case in PHASE_2_MEMORIES:
            mem_id = self._create_memory(test_case)
            if mem_id:
                memory_ids.append(mem_id)

        self.state.phase_2_memory_ids = memory_ids

        # Update state
        self.state.current_phase = TestPhase.PHASE_2_COMPLETE.value
        self.state.phase_2_completed_at = datetime.now().isoformat()
        self._save_state()

        # Summary
        exists_count = sum(1 for r in verification_results["memory_existence"] if r["exists"])
        recall_count = sum(1 for r in verification_results["recall_tests"] if r["passed"])

        self._log("")
        self._log("=" * 60)
        self._log(f"PHASE 2 COMPLETE")
        self._log(f"  Memories persisted: {exists_count}/{len(self.state.phase_1_memory_ids)}")
        self._log(f"  Recalls passed: {recall_count}/{len(PHASE_1_MEMORIES)}")
        self._log(f"  New memories created: {len(memory_ids)}")
        self._log("")
        self._log(">>> STOP THE PROCESS NOW <<<")
        self._log(f">>> Wait at least {self.config.phase_3_min_wait} hours <<<")
        self._log(">>> Then run: python scripts/real_persistence_test.py --continue <<<")
        self._log("=" * 60)

        return True

    def _run_phase_3(self) -> bool:
        """Phase 3: Verify all memories + test consolidation"""
        hours_waited = self._hours_since(self.state.phase_2_completed_at)
        total_hours = self._hours_since(self.state.started_at)

        self._log("=" * 60)
        self._log(f"PHASE 3: Second Persistence Verification")
        self._log(f"Time since Phase 2: {hours_waited:.2f} hours")
        self._log(f"Total test duration: {total_hours:.2f} hours")
        self._log("=" * 60)

        if hours_waited < self.config.phase_3_min_wait:
            self._log(f"Minimum wait time: {self.config.phase_3_min_wait} hours", "WARN")
            return False

        verification_results = {
            "hours_elapsed": hours_waited,
            "total_hours": total_hours,
            "phase_1_recall": [],
            "phase_2_recall": [],
            "memory_connections": []
        }

        # Verify Phase 1 memories still exist
        self._log("")
        self._log("Verifying Phase 1 memories (should be ~16+ hours old)...")
        for test_case in PHASE_1_MEMORIES:
            result = self._verify_recall(test_case)
            verification_results["phase_1_recall"].append(result)
            status = "PASS" if result["passed"] else "FAIL"
            self._log(f"  {test_case.id}: {status}")

        # Verify Phase 2 memories
        self._log("")
        self._log("Verifying Phase 2 memories...")
        for test_case in PHASE_2_MEMORIES:
            result = self._verify_recall(test_case)
            verification_results["phase_2_recall"].append(result)
            status = "PASS" if result["passed"] else "FAIL"
            self._log(f"  {test_case.id}: {status}")

        # Test memory connections (SWR consolidation)
        self._log("")
        self._log("Testing memory connections (SWR consolidation)...")
        try:
            # Check if memories formed connections
            for mem_id in self.state.phase_1_memory_ids[:2]:
                connected = self.memory_system.get_connected(mem_id)
                verification_results["memory_connections"].append({
                    "memory_id": mem_id,
                    "connected_count": len(connected),
                    "connected_ids": [c.id for c in connected[:5]]
                })
                self._log(f"  {mem_id}: {len(connected)} connections")
        except Exception as e:
            self._log(f"Connection test error: {e}", "WARN")

        self.state.phase_3_verification = verification_results

        # Create Phase 3 memories
        self._log("")
        self._log("Creating Phase 3 memories...")
        memory_ids = []
        for test_case in PHASE_3_MEMORIES:
            mem_id = self._create_memory(test_case)
            if mem_id:
                memory_ids.append(mem_id)

        self.state.phase_3_memory_ids = memory_ids

        # Update state
        self.state.current_phase = TestPhase.PHASE_3_COMPLETE.value
        self.state.phase_3_completed_at = datetime.now().isoformat()
        self._save_state()

        # Summary
        p1_passed = sum(1 for r in verification_results["phase_1_recall"] if r["passed"])
        p2_passed = sum(1 for r in verification_results["phase_2_recall"] if r["passed"])

        self._log("")
        self._log("=" * 60)
        self._log(f"PHASE 3 COMPLETE")
        self._log(f"  Phase 1 recalls: {p1_passed}/{len(PHASE_1_MEMORIES)}")
        self._log(f"  Phase 2 recalls: {p2_passed}/{len(PHASE_2_MEMORIES)}")
        self._log("")
        self._log(">>> STOP THE PROCESS NOW <<<")
        self._log(f">>> Wait at least {self.config.phase_4_min_wait} hours <<<")
        self._log(">>> Then run: python scripts/real_persistence_test.py --continue <<<")
        self._log("=" * 60)

        return True

    def _run_phase_4(self) -> bool:
        """Phase 4: Final verification and comprehensive report"""
        hours_waited = self._hours_since(self.state.phase_3_completed_at)
        total_hours = self._hours_since(self.state.started_at)

        self._log("=" * 60)
        self._log(f"PHASE 4: Final Verification & Report")
        self._log(f"Total test duration: {total_hours:.2f} hours")
        self._log("=" * 60)

        if hours_waited < self.config.phase_4_min_wait:
            self._log(f"Minimum wait time: {self.config.phase_4_min_wait} hours", "WARN")
            return False

        verification_results = {
            "total_hours": total_hours,
            "all_recalls": [],
            "relationship_test": None,
            "stats": {}
        }

        # Final verification of ALL memories
        all_test_cases = PHASE_1_MEMORIES + PHASE_2_MEMORIES + PHASE_3_MEMORIES

        self._log("")
        self._log("Final verification of all memories...")
        self._log("-" * 40)

        for test_case in all_test_cases:
            result = self._verify_recall(test_case)
            result["phase"] = test_case.phase_created
            result["age_hours"] = total_hours if test_case.phase_created == 1 else (
                total_hours - self._hours_since(self.state.phase_2_completed_at)
                if test_case.phase_created == 2 else hours_waited
            )
            verification_results["all_recalls"].append(result)

            status = "PASS" if result["passed"] else "FAIL"
            self._log(f"  [P{test_case.phase_created}] {test_case.id}: {status}")

        # Test relationship memory
        self._log("")
        self._log("Testing relationship memory...")
        try:
            rel = self.memory_system.get_relationship("carlos_martinez")
            if rel:
                verification_results["relationship_test"] = {
                    "exists": True,
                    "interactions": rel.total_interactions,
                    "trust_level": rel.trust_level
                }
                self._log(f"  Relationship found: {rel.total_interactions} interactions")
            else:
                verification_results["relationship_test"] = {"exists": False}
                self._log("  Relationship not found", "WARN")
        except Exception as e:
            self._log(f"  Error: {e}", "ERROR")

        # Get memory stats
        try:
            stats = self.memory_system.get_stats()
            verification_results["stats"] = stats
            self._log("")
            self._log(f"Memory system stats: {stats['total_memories']} total memories")
        except Exception as e:
            self._log(f"Stats error: {e}", "WARN")

        self.state.phase_4_verification = verification_results
        self.state.current_phase = TestPhase.FINISHED.value
        self.state.phase_4_completed_at = datetime.now().isoformat()
        self._save_state()

        # Generate and display report
        return self.generate_report()

    # =========================================================================
    # REPORTING
    # =========================================================================

    def generate_report(self) -> bool:
        """Generate comprehensive test report"""
        if not self.state:
            self.state = self._load_state()

        if not self.state:
            self._log("No test data found", "ERROR")
            return False

        total_hours = self._hours_since(self.state.started_at)

        print("\n")
        print("=" * 70)
        print("           ARIA REAL PERSISTENCE TEST - FINAL REPORT")
        print("=" * 70)
        print(f"\n  Test ID:         {self.state.test_id}")
        print(f"  Started:         {self.state.started_at}")
        print(f"  Total Duration:  {total_hours:.2f} hours ({total_hours/24:.1f} days)")
        print(f"  Current Phase:   {self.state.current_phase}")

        # Phase timeline
        print("\n" + "-" * 70)
        print("  PHASE TIMELINE")
        print("-" * 70)
        print(f"  Phase 1 (Create):     {self.state.phase_1_completed_at or 'Not started'}")
        print(f"  Phase 2 (Verify 1):   {self.state.phase_2_completed_at or 'Not completed'}")
        print(f"  Phase 3 (Verify 2):   {self.state.phase_3_completed_at or 'Not completed'}")
        print(f"  Phase 4 (Final):      {self.state.phase_4_completed_at or 'Not completed'}")

        # Results summary
        print("\n" + "-" * 70)
        print("  PERSISTENCE RESULTS")
        print("-" * 70)

        total_tests = 0
        total_passed = 0

        # Phase 2 results
        if self.state.phase_2_verification:
            v = self.state.phase_2_verification
            p2_passed = sum(1 for r in v.get("recall_tests", []) if r.get("passed"))
            p2_total = len(v.get("recall_tests", []))
            print(f"\n  After ~8 hours (Phase 2):")
            print(f"    Memories persisted: {sum(1 for r in v.get('memory_existence', []) if r.get('exists'))}/{len(v.get('memory_existence', []))}")
            print(f"    Recall tests:       {p2_passed}/{p2_total}")
            total_tests += p2_total
            total_passed += p2_passed

        # Phase 3 results
        if self.state.phase_3_verification:
            v = self.state.phase_3_verification
            p3_p1 = sum(1 for r in v.get("phase_1_recall", []) if r.get("passed"))
            p3_p2 = sum(1 for r in v.get("phase_2_recall", []) if r.get("passed"))
            print(f"\n  After ~16 hours (Phase 3):")
            print(f"    Phase 1 recalls:    {p3_p1}/{len(v.get('phase_1_recall', []))}")
            print(f"    Phase 2 recalls:    {p3_p2}/{len(v.get('phase_2_recall', []))}")
            total_tests += len(v.get("phase_1_recall", [])) + len(v.get("phase_2_recall", []))
            total_passed += p3_p1 + p3_p2

            # Connections
            conns = v.get("memory_connections", [])
            if conns:
                total_conns = sum(c.get("connected_count", 0) for c in conns)
                print(f"    SWR Connections:    {total_conns} total")

        # Phase 4 results
        if self.state.phase_4_verification:
            v = self.state.phase_4_verification
            all_recalls = v.get("all_recalls", [])

            by_phase = {1: [], 2: [], 3: []}
            for r in all_recalls:
                phase = r.get("phase", 0)
                if phase in by_phase:
                    by_phase[phase].append(r)

            print(f"\n  Final (After ~24 hours):")
            for phase_num in [1, 2, 3]:
                recalls = by_phase[phase_num]
                passed = sum(1 for r in recalls if r.get("passed"))
                print(f"    Phase {phase_num} memories:   {passed}/{len(recalls)}")
                total_tests += len(recalls)
                total_passed += passed

        # Overall score
        print("\n" + "-" * 70)
        print("  OVERALL SCORE")
        print("-" * 70)

        if total_tests > 0:
            score = (total_passed / total_tests) * 100

            if score >= 90:
                verdict = "EXCELLENT - Memory system is highly reliable"
                status = "PASS"
            elif score >= 70:
                verdict = "GOOD - Memory system works with minor issues"
                status = "PASS"
            elif score >= 50:
                verdict = "MODERATE - Some persistence issues detected"
                status = "WARN"
            else:
                verdict = "POOR - Significant persistence problems"
                status = "FAIL"

            print(f"\n  Total Tests:  {total_tests}")
            print(f"  Passed:       {total_passed}")
            print(f"  Score:        {score:.1f}%")
            print(f"\n  Verdict:      [{status}] {verdict}")
        else:
            print("\n  No test results available yet.")

        # Errors
        if self.state.errors:
            print("\n" + "-" * 70)
            print("  ERRORS ENCOUNTERED")
            print("-" * 70)
            for err in self.state.errors:
                print(f"  - {err}")

        print("\n" + "=" * 70)

        # Save report to file
        report_data = {
            "test_id": self.state.test_id,
            "total_duration_hours": total_hours,
            "total_tests": total_tests,
            "total_passed": total_passed,
            "score_percent": (total_passed / total_tests * 100) if total_tests > 0 else 0,
            "state": self.state.to_dict()
        }

        with open(self.config.report_file, 'w') as f:
            json.dump(report_data, f, indent=2)

        print(f"\n  Full report saved to: {self.config.report_file}")
        print("=" * 70 + "\n")

        return True

    def show_status(self):
        """Show current test status"""
        self.state = self._load_state()

        if not self.state:
            print("\nNo persistence test in progress.")
            print("Use --start to begin a new test.\n")
            return

        total_hours = self._hours_since(self.state.started_at)

        print("\n" + "=" * 50)
        print("  PERSISTENCE TEST STATUS")
        print("=" * 50)
        print(f"  Test ID:       {self.state.test_id}")
        print(f"  Current Phase: {self.state.current_phase}")
        print(f"  Running for:   {total_hours:.2f} hours")

        # Next action
        if self.state.current_phase == TestPhase.PHASE_1_COMPLETE.value:
            hours_since = self._hours_since(self.state.phase_1_completed_at)
            remaining = max(0, self.config.phase_2_min_wait - hours_since)
            print(f"\n  Hours since Phase 1: {hours_since:.2f}")
            if remaining > 0:
                print(f"  Wait {remaining:.2f} more hours before --continue")
            else:
                print("  Ready for Phase 2! Run --continue")

        elif self.state.current_phase == TestPhase.PHASE_2_COMPLETE.value:
            hours_since = self._hours_since(self.state.phase_2_completed_at)
            remaining = max(0, self.config.phase_3_min_wait - hours_since)
            print(f"\n  Hours since Phase 2: {hours_since:.2f}")
            if remaining > 0:
                print(f"  Wait {remaining:.2f} more hours before --continue")
            else:
                print("  Ready for Phase 3! Run --continue")

        elif self.state.current_phase == TestPhase.PHASE_3_COMPLETE.value:
            hours_since = self._hours_since(self.state.phase_3_completed_at)
            remaining = max(0, self.config.phase_4_min_wait - hours_since)
            print(f"\n  Hours since Phase 3: {hours_since:.2f}")
            if remaining > 0:
                print(f"  Wait {remaining:.2f} more hours before --continue")
            else:
                print("  Ready for Phase 4 (Final)! Run --continue")

        elif self.state.current_phase == TestPhase.FINISHED.value:
            print("\n  Test COMPLETE! Run --report to see results.")

        print("=" * 50 + "\n")

    def reset_test(self):
        """Reset the test state"""
        if os.path.exists(self.config.state_file):
            os.remove(self.config.state_file)
        if os.path.exists(self.config.report_file):
            os.remove(self.config.report_file)
        print("\nTest state reset. Use --start to begin a new test.\n")


# =============================================================================
# QUICK TEST MODE
# =============================================================================

class QuickTestConfig(TestConfig):
    """Configuration for quick testing (minutes instead of hours)"""
    phase_2_min_wait: float = 0.05   # 3 minutes
    phase_3_min_wait: float = 0.05   # 3 minutes
    phase_4_min_wait: float = 0.05   # 3 minutes


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="ARIA Real Persistence Test",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/real_persistence_test.py --start      # Begin new test
  python scripts/real_persistence_test.py --continue   # Continue test
  python scripts/real_persistence_test.py --status     # Check status
  python scripts/real_persistence_test.py --report     # Generate report
  python scripts/real_persistence_test.py --reset      # Start over

  # Quick test mode (3 min waits instead of 8 hours)
  python scripts/real_persistence_test.py --start --quick

The test runs in 4 phases over ~24 hours:
  Phase 1: Create test memories
  Phase 2: Verify after 8 hours, add more
  Phase 3: Verify after 16 hours, test SWR
  Phase 4: Final verification & report
        """
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--start', action='store_true', help='Start new test')
    group.add_argument('--continue', dest='cont', action='store_true', help='Continue test')
    group.add_argument('--status', action='store_true', help='Show test status')
    group.add_argument('--report', action='store_true', help='Generate report')
    group.add_argument('--reset', action='store_true', help='Reset test state')

    parser.add_argument('--quick', action='store_true',
                       help='Quick mode (3 min waits for testing)')

    args = parser.parse_args()

    # Select configuration
    config = QuickTestConfig() if args.quick else TestConfig()
    test = RealPersistenceTest(config)

    if args.start:
        test.start_test()
    elif args.cont:
        test.continue_test()
    elif args.status:
        test.show_status()
    elif args.report:
        test.generate_report()
    elif args.reset:
        test.reset_test()


if __name__ == "__main__":
    main()
