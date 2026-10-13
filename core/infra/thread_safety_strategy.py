"""
ARIA - Thread Safety Strategy for Neuroscience-Inspired Memory Components
==========================================================================

This module defines the complete thread safety strategy for integrating
neuroscience-inspired memory components into ARIA's memory system.

Components protected:
1. MemoryConsolidator - Sleep-like memory consolidation
2. DefaultModeNetwork - Background processing during idle
3. SharpWaveRippleSimulator - Memory replay for strengthening
4. MindWanderingEngine - Spontaneous thought generation
5. MetacognitiveMonitor - Self-monitoring of memory confidence
6. UnifiedMemoryArchitecture - Coordination of all components

Lock Hierarchy (acquire in ascending order to prevent deadlocks):
- Level 0: UNIFIED_COORDINATOR (top-level coordination)
- Level 1-2: Database locks (CHROMA_DB, SQLITE_DB)
- Level 3-6: Data structure locks (BM25, GRAPH, RELATIONSHIPS, TIME)
- Level 7-11: Component state locks
- Level 12-14: Component data locks (fine-grained)

Author: ARIA Development Team
Created: December 2024
"""

import threading
import copy
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from contextlib import contextmanager


# =============================================================================
# SECTION 1: GLOBAL LOCK HIERARCHY (DEADLOCK PREVENTION)
# =============================================================================

class LockLevel(Enum):
    """
    Lock hierarchy levels - ALWAYS acquire locks in ascending order.

    This ordering prevents deadlocks by ensuring all threads acquire locks
    in the same global order. The rule is simple:
    - A thread holding a lock at level N can only acquire locks at level N+1 or higher
    - Never acquire a lower-level lock while holding a higher-level lock

    Levels are ordered by:
    1. Scope (global/coordinator locks first)
    2. Data criticality (more critical = lower level)
    3. Contention frequency (higher contention = lower level)
    """
    # Level 0: Global coordinator lock (always acquire first if needed)
    UNIFIED_COORDINATOR = 0

    # Level 1-2: Core database locks (high contention, critical data)
    CHROMA_DB = 1           # ChromaDB operations (external resource)
    SQLITE_DB = 2           # SQLite database operations

    # Level 3-6: In-memory data structure locks (from memory_v2.py)
    BM25_INDEX = 3          # BM25 search index
    MEMORY_GRAPH = 4        # Memory connections graph
    RELATIONSHIPS = 5       # Relationships dictionary
    TIME_PERCEPTION = 6     # Time perception state

    # Level 7-11: New component STATE locks (ordered by dependency)
    DMN_STATE = 7           # DefaultModeNetwork state
    CONSOLIDATOR_STATE = 8  # MemoryConsolidator state
    SWR_STATE = 9           # SharpWaveRipple state
    WANDERING_STATE = 10    # MindWandering state
    METACOG_STATE = 11      # MetacognitiveMonitor state

    # Level 12-14: Component-specific DATA locks (fine-grained)
    DMN_ACTIVATIONS = 12    # DMN module_activations dict
    CONFIDENCE_HISTORY = 13 # Metacognitive confidence_history
    CURRENT_CONCERNS = 14   # MindWandering current_concerns


# Mapping from existing memory_v2.py lock names to hierarchy levels
EXISTING_LOCK_MAPPING = {
    '_chroma_lock': LockLevel.CHROMA_DB,
    '_bm25_lock': LockLevel.BM25_INDEX,
    '_graph_lock': LockLevel.MEMORY_GRAPH,
    '_relationships_lock': LockLevel.RELATIONSHIPS,
    '_time_lock': LockLevel.TIME_PERCEPTION,
}


# =============================================================================
# SECTION 2: LOCK REGISTRY AND MANAGEMENT
# =============================================================================

class LockRegistry:
    """
    Central registry for all locks in the memory system.

    Benefits:
    - Single source of truth for all locks
    - Enforces lock hierarchy through ordered acquisition
    - Provides debugging/monitoring capabilities
    - Enables deadlock detection in debug mode

    Thread Safety:
    - The registry itself uses a master lock for its internal state
    - Individual resource locks are RLocks for reentrant access

    Usage:
        registry = LockRegistry()

        with registry.acquire(LockLevel.CHROMA_DB):
            # Do something with ChromaDB
            pass
    """

    _instance: Optional['LockRegistry'] = None
    _instance_lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern - one registry for the entire system."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._master_lock = threading.Lock()
        self._locks: Dict[LockLevel, threading.RLock] = {}
        self._lock_owners: Dict[LockLevel, Optional[int]] = {}
        self._held_locks: Dict[int, List[LockLevel]] = {}  # thread_id -> held levels
        self._debug_mode = False
        self._lock_stats: Dict[LockLevel, Dict[str, int]] = {}

        # Initialize all locks
        for level in LockLevel:
            self._locks[level] = threading.RLock()
            self._lock_owners[level] = None
            self._lock_stats[level] = {'acquisitions': 0, 'contentions': 0}

        self._initialized = True

    def get_lock(self, level: LockLevel) -> threading.RLock:
        """Get the lock for a specific level."""
        return self._locks[level]

    def enable_debug(self):
        """Enable debug mode with deadlock detection."""
        self._debug_mode = True

    def disable_debug(self):
        """Disable debug mode."""
        self._debug_mode = False

    @contextmanager
    def acquire(self, level: LockLevel, timeout: float = None):
        """
        Acquire a lock with hierarchy enforcement.

        Args:
            level: The lock level to acquire
            timeout: Optional timeout in seconds (None = wait forever)

        Raises:
            RuntimeError: If lock hierarchy is violated (debug mode only)
            TimeoutError: If lock cannot be acquired within timeout

        Yields:
            The acquired lock
        """
        thread_id = threading.get_ident()

        if self._debug_mode:
            self._check_hierarchy(thread_id, level)

        lock = self._locks[level]

        # Try to acquire with timeout
        if timeout is not None:
            acquired = lock.acquire(timeout=timeout)
            if not acquired:
                raise TimeoutError(
                    f"Failed to acquire lock {level.name} within {timeout}s"
                )
        else:
            lock.acquire()

        try:
            # Track acquisition
            self._lock_stats[level]['acquisitions'] += 1

            if self._debug_mode:
                with self._master_lock:
                    if thread_id not in self._held_locks:
                        self._held_locks[thread_id] = []
                    self._held_locks[thread_id].append(level)
                    self._lock_owners[level] = thread_id

            yield lock

        finally:
            if self._debug_mode:
                with self._master_lock:
                    if thread_id in self._held_locks:
                        if level in self._held_locks[thread_id]:
                            self._held_locks[thread_id].remove(level)
                        if not self._held_locks[thread_id]:
                            del self._held_locks[thread_id]
                    self._lock_owners[level] = None
            lock.release()

    @contextmanager
    def acquire_multiple(self, *levels: LockLevel, timeout: float = None):
        """
        Acquire multiple locks in hierarchy order.

        Args:
            *levels: Lock levels to acquire (will be sorted by hierarchy)
            timeout: Optional timeout in seconds

        Yields:
            Dict mapping level to lock
        """
        # Sort by hierarchy level to ensure correct order
        sorted_levels = sorted(levels, key=lambda x: x.value)
        acquired_locks = {}

        try:
            for level in sorted_levels:
                lock = self._locks[level]
                if timeout is not None:
                    if not lock.acquire(timeout=timeout):
                        raise TimeoutError(f"Failed to acquire {level.name}")
                else:
                    lock.acquire()
                acquired_locks[level] = lock

            yield acquired_locks

        finally:
            # Release in reverse order
            for level in reversed(sorted_levels):
                if level in acquired_locks:
                    acquired_locks[level].release()

    def _check_hierarchy(self, thread_id: int, requested_level: LockLevel):
        """Check that lock hierarchy is not violated."""
        with self._master_lock:
            if thread_id in self._held_locks:
                held = self._held_locks[thread_id]
                for held_level in held:
                    if held_level.value > requested_level.value:
                        raise RuntimeError(
                            f"Lock hierarchy violation: Cannot acquire {requested_level.name} "
                            f"(level {requested_level.value}) while holding {held_level.name} "
                            f"(level {held_level.value}). Acquire locks in ascending order."
                        )

    def get_held_locks(self, thread_id: int = None) -> List[LockLevel]:
        """Get locks held by a thread (current thread if not specified)."""
        if thread_id is None:
            thread_id = threading.get_ident()
        with self._master_lock:
            return self._held_locks.get(thread_id, []).copy()

    def get_statistics(self) -> Dict[str, Any]:
        """Get lock usage statistics."""
        return {
            level.name: stats.copy()
            for level, stats in self._lock_stats.items()
        }

    def reset_statistics(self):
        """Reset lock statistics."""
        for level in LockLevel:
            self._lock_stats[level] = {'acquisitions': 0, 'contentions': 0}


# =============================================================================
# SECTION 3: COMPONENT LOCK SPECIFICATIONS
# =============================================================================

@dataclass
class ComponentLockSpec:
    """Specification for a component's locking requirements."""
    component_name: str
    primary_lock: LockLevel
    secondary_locks: List[LockLevel] = field(default_factory=list)
    requires_existing_locks: List[str] = field(default_factory=list)
    lock_type: str = "RLock"
    notes: str = ""


# Lock specifications for each neuroscience component
COMPONENT_LOCK_SPECS = {
    "MemoryConsolidator": ComponentLockSpec(
        component_name="MemoryConsolidator",
        primary_lock=LockLevel.CONSOLIDATOR_STATE,
        requires_existing_locks=["_chroma_lock", "_graph_lock", "_bm25_lock"],
        notes="Lock order: CONSOLIDATOR_STATE -> CHROMA_DB -> MEMORY_GRAPH -> BM25_INDEX"
    ),
    "DefaultModeNetwork": ComponentLockSpec(
        component_name="DefaultModeNetwork",
        primary_lock=LockLevel.DMN_STATE,
        secondary_locks=[LockLevel.DMN_ACTIVATIONS],
        requires_existing_locks=["_chroma_lock"],
        notes="Uses copy-on-write for module_activations"
    ),
    "SharpWaveRippleSimulator": ComponentLockSpec(
        component_name="SharpWaveRippleSimulator",
        primary_lock=LockLevel.SWR_STATE,
        requires_existing_locks=["_chroma_lock", "_graph_lock"],
        notes="Short-lived locks during replay"
    ),
    "MindWanderingEngine": ComponentLockSpec(
        component_name="MindWanderingEngine",
        primary_lock=LockLevel.WANDERING_STATE,
        secondary_locks=[LockLevel.CURRENT_CONCERNS],
        requires_existing_locks=["_chroma_lock", "_relationships_lock"],
        notes="Separate lock for concerns list (high frequency)"
    ),
    "MetacognitiveMonitor": ComponentLockSpec(
        component_name="MetacognitiveMonitor",
        primary_lock=LockLevel.METACOG_STATE,
        secondary_locks=[LockLevel.CONFIDENCE_HISTORY],
        requires_existing_locks=["_chroma_lock"],
        notes="Bounded history with copy-on-write"
    ),
    "UnifiedMemoryArchitecture": ComponentLockSpec(
        component_name="UnifiedMemoryArchitecture",
        primary_lock=LockLevel.UNIFIED_COORDINATOR,
        requires_existing_locks=[
            "_chroma_lock", "_graph_lock", "_bm25_lock",
            "_relationships_lock", "_time_lock"
        ],
        notes="Top-level coordinator - only for mode changes"
    ),
}


# =============================================================================
# SECTION 4: THREAD-SAFE BASE CLASS
# =============================================================================

class ThreadSafeComponent:
    """
    Base class for thread-safe neuroscience components.

    Provides:
    - Standard lock acquisition patterns
    - Copy-on-write helpers
    - State transition safety
    - Integration with LockRegistry

    Usage:
        class MyComponent(ThreadSafeComponent):
            def __init__(self):
                super().__init__("MyComponentName")
                self._my_state = {}

            def do_something(self):
                with self._with_state_lock():
                    # Safe state modification
                    self._my_state['key'] = 'value'
    """

    def __init__(self, component_name: str):
        self._component_name = component_name
        self._registry = LockRegistry()
        self._spec = COMPONENT_LOCK_SPECS.get(component_name)

        if self._spec is None:
            # Allow unknown components with a generic lock
            self._primary_lock_level = LockLevel.METACOG_STATE  # Default
            self._primary_lock = self._registry.get_lock(self._primary_lock_level)
        else:
            self._primary_lock_level = self._spec.primary_lock
            self._primary_lock = self._registry.get_lock(self._spec.primary_lock)

    @contextmanager
    def _with_state_lock(self, timeout: float = None):
        """Acquire the primary state lock for this component."""
        with self._registry.acquire(self._primary_lock_level, timeout=timeout):
            yield

    @contextmanager
    def _with_secondary_lock(self, level: LockLevel, timeout: float = None):
        """Acquire a secondary lock (must be higher level than primary)."""
        if level.value < self._primary_lock_level.value:
            raise RuntimeError(
                f"Cannot acquire secondary lock {level.name} "
                f"(level {level.value}) which is lower than primary "
                f"{self._primary_lock_level.name} (level {self._primary_lock_level.value})"
            )
        with self._registry.acquire(level, timeout=timeout):
            yield

    def _copy_on_write(self, data: Any) -> Any:
        """
        Create a deep copy for copy-on-write pattern.

        Use this when:
        - Reading data that may be modified by another thread
        - Preparing updates that will be atomically swapped
        """
        return copy.deepcopy(data)

    def _get_component_spec(self) -> Optional[ComponentLockSpec]:
        """Get the lock specification for this component."""
        return self._spec


# =============================================================================
# SECTION 5: ATOMIC OPERATION PATTERNS
# =============================================================================

class AtomicPatterns:
    """
    Reusable atomic operation patterns for memory operations.

    These patterns ensure thread-safety for common operations.
    All methods are static and can be used without instantiation.
    """

    @staticmethod
    def copy_on_write_update(
        lock: threading.RLock,
        get_current: Callable[[], Any],
        update_fn: Callable[[Any], Any],
        set_new: Callable[[Any], None]
    ) -> Any:
        """
        Copy-on-write update pattern.

        Steps:
        1. Copy current state under lock
        2. Apply update outside lock (allows concurrent reads)
        3. Atomic swap under lock

        Args:
            lock: The lock protecting the data
            get_current: Function to get current value
            update_fn: Function to transform the copy
            set_new: Function to set the new value

        Returns:
            The new value after update

        Usage:
            AtomicPatterns.copy_on_write_update(
                lock=self._lock,
                get_current=lambda: self._data,
                update_fn=lambda data: {**data, "key": "new_value"},
                set_new=lambda data: setattr(self, '_data', data)
            )
        """
        # Step 1: Copy under lock
        with lock:
            data_copy = copy.deepcopy(get_current())

        # Step 2: Apply update (outside lock - allows reads)
        new_data = update_fn(data_copy)

        # Step 3: Atomic swap
        with lock:
            set_new(new_data)
            return new_data

    @staticmethod
    def read_modify_write(
        lock: threading.RLock,
        read_fn: Callable[[], Any],
        modify_fn: Callable[[Any], Any],
        write_fn: Callable[[Any], None]
    ):
        """
        Read-modify-write pattern with full lock protection.

        Use when the entire operation must be atomic (no concurrent reads allowed).

        Args:
            lock: The lock protecting the data
            read_fn: Function to read current value
            modify_fn: Function to modify the value
            write_fn: Function to write back

        Usage:
            AtomicPatterns.read_modify_write(
                lock=self._lock,
                read_fn=lambda: self._counter,
                modify_fn=lambda x: x + 1,
                write_fn=lambda x: setattr(self, '_counter', x)
            )
        """
        with lock:
            current = read_fn()
            new_value = modify_fn(current)
            write_fn(new_value)
            return new_value

    @staticmethod
    def bounded_append(
        lock: threading.RLock,
        container: list,
        item: Any,
        max_size: int,
        keep_ratio: float = 0.5
    ) -> int:
        """
        Append to a bounded list with atomic cleanup.

        When the list exceeds max_size, keeps only the most recent
        (max_size * keep_ratio) items.

        Args:
            lock: The lock protecting the container
            container: The list to append to
            item: Item to append
            max_size: Maximum size before cleanup
            keep_ratio: Ratio of items to keep on cleanup (0.0-1.0)

        Returns:
            Current length of container after operation

        Usage:
            AtomicPatterns.bounded_append(
                lock=self._history_lock,
                container=self._history,
                item=new_entry,
                max_size=1000,
                keep_ratio=0.5  # Keep 500 items when cleanup triggers
            )
        """
        with lock:
            container.append(item)
            current_len = len(container)

            if current_len > max_size:
                keep_count = int(max_size * keep_ratio)
                del container[:-keep_count]
                current_len = len(container)

            return current_len

    @staticmethod
    def safe_dict_update(
        lock: threading.RLock,
        target_dict: dict,
        updates: dict,
        merge: bool = True
    ) -> dict:
        """
        Thread-safe dictionary update.

        Args:
            lock: The lock protecting the dictionary
            target_dict: The dictionary to update
            updates: Key-value pairs to add/update
            merge: If True, merge with existing. If False, replace entirely.

        Returns:
            The updated dictionary (copy)

        Usage:
            AtomicPatterns.safe_dict_update(
                lock=self._state_lock,
                target_dict=self._state,
                updates={'new_key': 'new_value'},
                merge=True
            )
        """
        with lock:
            if merge:
                target_dict.update(updates)
            else:
                target_dict.clear()
                target_dict.update(updates)
            return target_dict.copy()

    @staticmethod
    def compare_and_swap(
        lock: threading.RLock,
        get_current: Callable[[], Any],
        expected: Any,
        new_value: Any,
        set_value: Callable[[Any], None]
    ) -> bool:
        """
        Compare-and-swap operation.

        Only updates if current value equals expected value.

        Args:
            lock: The lock protecting the value
            get_current: Function to get current value
            expected: Expected current value
            new_value: New value to set if current == expected
            set_value: Function to set the value

        Returns:
            True if swap occurred, False otherwise

        Usage:
            success = AtomicPatterns.compare_and_swap(
                lock=self._lock,
                get_current=lambda: self._state,
                expected="idle",
                new_value="active",
                set_value=lambda v: setattr(self, '_state', v)
            )
        """
        with lock:
            current = get_current()
            if current == expected:
                set_value(new_value)
                return True
            return False


# =============================================================================
# SECTION 6: INTEGRATION HELPERS
# =============================================================================

def get_lock_for_existing(lock_name: str) -> Optional[LockLevel]:
    """
    Get the LockLevel for an existing lock from memory_v2.py.

    Args:
        lock_name: Name of the lock (e.g., '_chroma_lock')

    Returns:
        LockLevel if found, None otherwise
    """
    return EXISTING_LOCK_MAPPING.get(lock_name)


def validate_lock_order(locks: List[LockLevel]) -> bool:
    """
    Validate that a sequence of locks is in correct hierarchy order.

    Args:
        locks: List of LockLevels in the order they will be acquired

    Returns:
        True if order is valid, False otherwise
    """
    for i in range(1, len(locks)):
        if locks[i].value < locks[i-1].value:
            return False
    return True


def get_required_locks_for_component(component_name: str) -> List[LockLevel]:
    """
    Get all locks required for a component in correct acquisition order.

    Args:
        component_name: Name of the component

    Returns:
        List of LockLevels in correct order
    """
    spec = COMPONENT_LOCK_SPECS.get(component_name)
    if spec is None:
        return []

    locks = [spec.primary_lock]
    locks.extend(spec.secondary_locks)

    # Add existing locks
    for lock_name in spec.requires_existing_locks:
        level = EXISTING_LOCK_MAPPING.get(lock_name)
        if level:
            locks.append(level)

    # Sort by hierarchy
    return sorted(set(locks), key=lambda x: x.value)


# =============================================================================
# SECTION 7: DEBUG AND TESTING UTILITIES
# =============================================================================

class DeadlockDetector:
    """
    Utility for detecting potential deadlocks during development.

    Usage:
        detector = DeadlockDetector()
        detector.start_monitoring()

        # ... run your code ...

        violations = detector.get_violations()
        detector.stop_monitoring()
    """

    def __init__(self):
        self._violations: List[str] = []
        self._monitoring = False
        self._registry = LockRegistry()

    def start_monitoring(self):
        """Start monitoring for hierarchy violations."""
        self._monitoring = True
        self._registry.enable_debug()
        self._violations = []

    def stop_monitoring(self):
        """Stop monitoring."""
        self._monitoring = False
        self._registry.disable_debug()

    def get_violations(self) -> List[str]:
        """Get list of detected violations."""
        return self._violations.copy()

    def clear_violations(self):
        """Clear recorded violations."""
        self._violations = []


# =============================================================================
# TESTING / MAIN
# =============================================================================

if __name__ == "__main__":
    print("Thread Safety Strategy for ARIA Neuroscience Components")
    print("=" * 60)

    print("\nLock Hierarchy (acquire in this order):")
    for level in sorted(LockLevel, key=lambda x: x.value):
        print(f"  Level {level.value:2d}: {level.name}")

    print("\nComponent Lock Specifications:")
    for name, spec in COMPONENT_LOCK_SPECS.items():
        print(f"\n  {name}:")
        print(f"    Primary Lock: {spec.primary_lock.name}")
        if spec.secondary_locks:
            print(f"    Secondary Locks: {[l.name for l in spec.secondary_locks]}")
        if spec.requires_existing_locks:
            print(f"    Uses Existing: {spec.requires_existing_locks}")

    print("\nExisting Lock Mapping:")
    for lock_name, level in EXISTING_LOCK_MAPPING.items():
        print(f"  {lock_name} -> {level.name} (Level {level.value})")

    print("\n" + "=" * 60)
    print("Module ready for import. Usage:")
    print("  from core.thread_safety_strategy import (")
    print("      LockLevel, LockRegistry, ThreadSafeComponent, AtomicPatterns")
    print("  )")
