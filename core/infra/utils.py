"""
ARIA - Core Utilities
======================
Consolidated utility functions used across the ARIA system.

This module provides:
- Atomic file operations for data integrity
- Thread-safe ID generation
- Common helpers for YAML/JSON operations
"""

import os
import json
import tempfile
import hashlib
import threading
from datetime import datetime
from typing import Any, Optional
import yaml


# Thread-safe lock for ID generation
_id_lock = threading.Lock()
_id_counter = 0


def atomic_write_yaml(filepath: str, data: Any, default_flow_style: bool = False) -> None:
    """
    Write YAML data atomically to prevent corruption on interruption.

    Uses a write-to-temp-then-rename strategy which is atomic on POSIX systems.
    Falls back to direct write if atomic rename fails (e.g., cross-device).

    Args:
        filepath: Path to the target file
        data: Data to serialize to YAML
        default_flow_style: YAML formatting style (False = block style)

    Raises:
        IOError: If both atomic and fallback writes fail
    """
    dir_path = os.path.dirname(filepath)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    try:
        # Write to temp file in same directory (required for atomic rename)
        fd, temp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_path or '.')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                yaml.dump(data, f, default_flow_style=default_flow_style, allow_unicode=True)
            # Atomic rename (atomic on POSIX, nearly atomic on Windows)
            os.replace(temp_path, filepath)
        except Exception:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise
    except Exception:
        # Fallback to direct write if atomic fails (e.g., cross-device, permissions)
        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=default_flow_style, allow_unicode=True)


def atomic_write_json(filepath: str, data: Any, indent: int = 2) -> None:
    """
    Write JSON data atomically to prevent corruption on interruption.

    Args:
        filepath: Path to the target file
        data: Data to serialize to JSON
        indent: JSON indentation level
    """
    dir_path = os.path.dirname(filepath)
    if dir_path:
        os.makedirs(dir_path, exist_ok=True)

    try:
        fd, temp_path = tempfile.mkstemp(suffix='.tmp', dir=dir_path or '.')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=indent, ensure_ascii=False)
            os.replace(temp_path, filepath)
        except Exception:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            raise
    except Exception:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)


def generate_id(
    prefix: str = "",
    length: int = 12,
    content: Optional[str] = None,
    include_counter: bool = False
) -> str:
    """
    Generate a unique ID using SHA256 hashing.

    Thread-safe ID generation with optional content-based hashing.

    Args:
        prefix: Optional prefix for the ID (e.g., "vis_", "project_")
        length: Length of hex digest (default 12, max 64)
        content: Optional content to include in hash for content-based IDs
        include_counter: Include a thread-safe counter for extra uniqueness

    Returns:
        Unique hex ID string

    Examples:
        generate_id()                           # "a1b2c3d4e5f6"
        generate_id(prefix="mem_", length=16)   # "mem_a1b2c3d4e5f6g7h8"
        generate_id(content="hello world")      # Content-based ID
    """
    global _id_counter

    # Validate prefix is a string
    if not isinstance(prefix, str):
        prefix = str(prefix) if prefix is not None else ""

    # Build unique string
    parts = []

    if prefix:
        parts.append(prefix)

    parts.append(datetime.now().isoformat())

    if content:
        parts.append(content[:100])  # Limit content length

    if include_counter:
        with _id_lock:
            _id_counter += 1
            parts.append(str(_id_counter))

    unique_string = "_".join(parts)
    hash_hex = hashlib.sha256(unique_string.encode()).hexdigest()

    # Ensure length is within bounds
    length = min(max(length, 8), 64)

    result = hash_hex[:length]

    # Add prefix if specified (not included in hash)
    if prefix and not unique_string.startswith(prefix):
        return f"{prefix}{result}"

    return result


def safe_yaml_load(filepath: str, default: Any = None) -> Any:
    """
    Safely load YAML file with error handling.

    Args:
        filepath: Path to YAML file
        default: Default value if file doesn't exist or is invalid

    Returns:
        Parsed YAML data or default value
    """
    if not os.path.exists(filepath):
        return default

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data if data is not None else default
    except (IOError, yaml.YAMLError):
        return default


def safe_json_load(filepath: str, default: Any = None) -> Any:
    """
    Safely load JSON file with error handling.

    Args:
        filepath: Path to JSON file
        default: Default value if file doesn't exist or is invalid

    Returns:
        Parsed JSON data or default value
    """
    if not os.path.exists(filepath):
        return default

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return default


class ThreadSafeCounter:
    """Thread-safe counter for generating sequential IDs."""

    def __init__(self, start: int = 0):
        self._value = start
        self._lock = threading.Lock()

    def increment(self) -> int:
        """Increment and return the new value."""
        with self._lock:
            self._value += 1
            return self._value

    @property
    def value(self) -> int:
        """Get current value."""
        with self._lock:
            return self._value


class ResourceLock:
    """
    Named lock manager for protecting shared resources.

    Usage:
        locks = ResourceLock()
        with locks.acquire("database"):
            # Protected database operations
    """

    def __init__(self):
        self._locks: dict = {}
        self._master_lock = threading.Lock()

    def acquire(self, name: str) -> threading.RLock:
        """
        Get or create a lock for the named resource.

        Args:
            name: Name of the resource to lock

        Returns:
            RLock for the resource (can be used as context manager)
        """
        with self._master_lock:
            if name not in self._locks:
                self._locks[name] = threading.RLock()
            return self._locks[name]

    def get_lock(self, name: str) -> threading.RLock:
        """Alias for acquire()."""
        return self.acquire(name)
