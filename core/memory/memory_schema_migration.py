"""
ARIA - Memory Schema Migration for Neuroscience-Inspired Consolidation
=======================================================================

This module provides:
1. SQLite schema migration (ALTER TABLE + new indexes)
2. ChromaDB metadata sync strategy
3. Helper method _sync_memory_to_chroma()
4. Complete migration function with error handling
5. Optimized indexes for consolidation queries
6. Query helpers for consolidation operations

New fields from Neuroscience Plan:
- consolidated: bool - Whether memory has been consolidated
- consolidation_count: int - Times replayed/consolidated
- last_consolidation: str - ISO timestamp of last consolidation
- memory_strength: float - Decays over time, increases with replay (0.0-1.0)
- encoding_context: str - System state when memory was created

Author: ARIA Development Team
Created: December 2024
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass

# Configure logging
logger = logging.getLogger(__name__)


# =============================================================================
# SCHEMA DEFINITIONS
# =============================================================================

# New columns to add to the memories table
NEW_COLUMNS = [
    # (column_name, type, default_value, description)
    ("consolidated", "INTEGER", "0",
     "Whether memory has been consolidated (0=False, 1=True)"),
    ("consolidation_count", "INTEGER", "0",
     "Number of times this memory has been replayed/consolidated"),
    ("last_consolidation", "TEXT", "NULL",
     "ISO timestamp of the last consolidation"),
    ("memory_strength", "REAL", "1.0",
     "Memory strength that decays over time (0.0-1.0)"),
    ("encoding_context", "TEXT", "''",
     "System state/context when memory was created"),
]

# New indexes for efficient consolidation queries
NEW_INDEXES = [
    # (index_name, columns, description)
    (
        "idx_memories_consolidated",
        "consolidated",
        "Index for filtering consolidated vs unconsolidated memories"
    ),
    (
        "idx_memories_strength",
        "memory_strength DESC",
        "Index for querying by memory strength"
    ),
    (
        "idx_memories_consolidation_time",
        "last_consolidation",
        "Index for finding memories by consolidation time"
    ),
    (
        "idx_memories_unconsolidated_recent",
        "consolidated, timestamp DESC",
        "Composite index for getting recent unconsolidated memories"
    ),
    (
        "idx_memories_decay_candidates",
        "consolidated, memory_strength, importance",
        "Composite index for decay operation candidates"
    ),
    (
        "idx_memories_consolidation_priority",
        "consolidated, emotional_intensity DESC, importance DESC",
        "Composite index for prioritizing memories for consolidation"
    ),
]

# ChromaDB metadata fields to add
NEW_CHROMA_METADATA_FIELDS = [
    "consolidated",           # int (0 or 1)
    "consolidation_count",    # int
    "memory_strength",        # float
    # Note: last_consolidation and encoding_context not in ChromaDB
    # as they're not useful for semantic filtering
]


# =============================================================================
# MIGRATION CLASS
# =============================================================================

class MemorySchemaMigration:
    """
    Handles schema migration for ARIA's memory system.

    Adds new columns and indexes required by the neuroscience-inspired
    consolidation system.

    Usage:
        migration = MemorySchemaMigration(db_path, chroma_collection)
        report = migration.run_full_migration()
    """

    def __init__(self, db_path: str, chroma_collection=None):
        """
        Initialize the migration handler.

        Args:
            db_path: Path to the SQLite database
            chroma_collection: ChromaDB collection object (optional)
        """
        self.db_path = db_path
        self.chroma_collection = chroma_collection
        self.migration_log: List[Dict[str, Any]] = []

    def _log(self, message: str, level: str = "info"):
        """Log a migration message."""
        timestamp = datetime.now().isoformat()
        entry = {"timestamp": timestamp, "level": level, "message": message}
        self.migration_log.append(entry)

        if level == "error":
            logger.error(message)
        elif level == "warning":
            logger.warning(message)
        else:
            logger.info(message)

    # =========================================================================
    # SQLITE MIGRATION
    # =========================================================================

    def check_column_exists(self, conn: sqlite3.Connection, column_name: str) -> bool:
        """Check if a column exists in the memories table."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(memories)")
        columns = [row[1] for row in cursor.fetchall()]
        return column_name in columns

    def check_index_exists(self, conn: sqlite3.Connection, index_name: str) -> bool:
        """Check if an index exists."""
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,)
        )
        return cursor.fetchone() is not None

    def migrate_sqlite_schema(self) -> Dict[str, Any]:
        """
        Add new columns to the SQLite memories table.

        Returns:
            Dict with migration statistics
        """
        stats = {
            "columns_added": [],
            "columns_skipped": [],
            "errors": []
        }

        self._log("Starting SQLite schema migration...")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                for col_name, col_type, default_val, description in NEW_COLUMNS:
                    if self.check_column_exists(conn, col_name):
                        stats["columns_skipped"].append(col_name)
                        self._log(f"Column '{col_name}' already exists, skipping")
                        continue

                    try:
                        # Build ALTER TABLE statement
                        if default_val == "NULL":
                            sql = f"ALTER TABLE memories ADD COLUMN {col_name} {col_type}"
                        else:
                            sql = f"ALTER TABLE memories ADD COLUMN {col_name} {col_type} DEFAULT {default_val}"

                        cursor.execute(sql)
                        stats["columns_added"].append(col_name)
                        self._log(f"Added column '{col_name}' ({description})")

                    except sqlite3.OperationalError as e:
                        error_msg = f"Failed to add column '{col_name}': {e}"
                        stats["errors"].append(error_msg)
                        self._log(error_msg, "error")

                conn.commit()

        except sqlite3.Error as e:
            error_msg = f"Database error during schema migration: {e}"
            stats["errors"].append(error_msg)
            self._log(error_msg, "error")

        self._log(
            f"Schema migration complete. Added: {len(stats['columns_added'])}, "
            f"Skipped: {len(stats['columns_skipped'])}, Errors: {len(stats['errors'])}"
        )

        return stats

    def create_consolidation_indexes(self) -> Dict[str, Any]:
        """
        Create optimized indexes for consolidation queries.

        Returns:
            Dict with index creation statistics
        """
        stats = {
            "indexes_created": [],
            "indexes_skipped": [],
            "errors": []
        }

        self._log("Creating consolidation indexes...")

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                for idx_name, columns, description in NEW_INDEXES:
                    if self.check_index_exists(conn, idx_name):
                        stats["indexes_skipped"].append(idx_name)
                        self._log(f"Index '{idx_name}' already exists, skipping")
                        continue

                    try:
                        sql = f"CREATE INDEX IF NOT EXISTS {idx_name} ON memories({columns})"
                        cursor.execute(sql)
                        stats["indexes_created"].append(idx_name)
                        self._log(f"Created index '{idx_name}' ({description})")

                    except sqlite3.OperationalError as e:
                        error_msg = f"Failed to create index '{idx_name}': {e}"
                        stats["errors"].append(error_msg)
                        self._log(error_msg, "error")

                conn.commit()

        except sqlite3.Error as e:
            error_msg = f"Database error during index creation: {e}"
            stats["errors"].append(error_msg)
            self._log(error_msg, "error")

        self._log(
            f"Index creation complete. Created: {len(stats['indexes_created'])}, "
            f"Skipped: {len(stats['indexes_skipped'])}, Errors: {len(stats['errors'])}"
        )

        return stats

    # =========================================================================
    # CHROMADB SYNC
    # =========================================================================

    def _build_chroma_metadata(self, row: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build complete ChromaDB metadata from a SQLite row dict.

        Args:
            row: SQLite row as dictionary

        Returns:
            Dict of metadata for ChromaDB
        """
        # Parse JSON fields safely
        def safe_json_loads(val, default):
            if val is None:
                return default
            if isinstance(val, (list, dict)):
                return val
            try:
                return json.loads(val)
            except (json.JSONDecodeError, TypeError):
                return default

        involves_people = safe_json_loads(row.get("involves_people"), [])
        tags = safe_json_loads(row.get("tags"), [])
        connected = safe_json_loads(row.get("connected_memories"), [])

        metadata = {
            # Original fields
            "emotional_tone": row.get("emotional_tone", "neutral") or "neutral",
            "emotional_intensity": float(row.get("emotional_intensity", 0.5) or 0.5),
            "importance": float(row.get("importance", 0.5) or 0.5),
            "confidence": float(row.get("confidence", 0.9) or 0.9),
            "origin": row.get("origin", "lived") or "lived",
            "is_mine": int(row.get("is_mine", 1) or 1),
            "involves_people": ",".join(involves_people) if involves_people else "",
            "has_people": 1 if involves_people else 0,
            "tags": ",".join(tags) if tags else "",
            "has_tags": 1 if tags else 0,
            "has_connections": 1 if connected else 0,
            "timestamp": row.get("timestamp", ""),

            # New consolidation fields
            "consolidated": int(row.get("consolidated", 0) or 0),
            "consolidation_count": int(row.get("consolidation_count", 0) or 0),
            "memory_strength": float(row.get("memory_strength", 1.0) or 1.0),
        }

        return metadata

    def _sync_memory_to_chroma(
        self,
        memory_id: str,
        content: str,
        context: str,
        metadata: Dict[str, Any]
    ) -> bool:
        """
        Sync a single memory to ChromaDB with complete metadata.

        This is a helper method that ensures SQLite and ChromaDB stay in sync.
        Should be called whenever a memory is updated in SQLite.

        Args:
            memory_id: The memory's unique ID
            content: The memory content
            context: The memory context
            metadata: Dict of metadata fields

        Returns:
            True if sync successful, False otherwise
        """
        if not self.chroma_collection:
            return False

        try:
            # Create enriched document for better embeddings
            enriched_document = content
            if context:
                enriched_document = f"{content}\n\nContext: {context}"

            # Upsert to ChromaDB (handles both insert and update)
            self.chroma_collection.upsert(
                documents=[enriched_document],
                metadatas=[metadata],
                ids=[memory_id]
            )

            return True

        except Exception as e:
            self._log(f"Failed to sync memory {memory_id} to ChromaDB: {e}", "error")
            return False

    def sync_all_memories_to_chroma(self, batch_size: int = 50) -> Dict[str, Any]:
        """
        Sync all SQLite memories to ChromaDB with new metadata fields.

        This is the batch update strategy for keeping SQLite and ChromaDB in sync.

        Args:
            batch_size: Number of memories to process per batch

        Returns:
            Dict with sync statistics
        """
        if not self.chroma_collection:
            return {"error": "ChromaDB collection not available", "synced": 0}

        stats = {
            "total": 0,
            "synced": 0,
            "failed": 0,
            "batches": 0
        }

        self._log("Starting ChromaDB sync for all memories...")

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Get total count
                cursor.execute("SELECT COUNT(*) FROM memories")
                stats["total"] = cursor.fetchone()[0]

                # Process in batches
                offset = 0
                while True:
                    cursor.execute(
                        f"SELECT * FROM memories LIMIT {batch_size} OFFSET {offset}"
                    )
                    rows = cursor.fetchall()

                    if not rows:
                        break

                    # Prepare batch data
                    ids = []
                    documents = []
                    metadatas = []

                    for row in rows:
                        try:
                            row_dict = dict(row)
                            memory_id = row_dict["id"]
                            content = row_dict["content"]
                            context = row_dict.get("context") or ""

                            # Build enriched document
                            doc = content
                            if context:
                                doc = f"{content}\n\nContext: {context}"

                            # Build metadata
                            metadata = self._build_chroma_metadata(row_dict)

                            ids.append(memory_id)
                            documents.append(doc)
                            metadatas.append(metadata)

                        except Exception as e:
                            stats["failed"] += 1
                            self._log(f"Failed to prepare memory: {e}", "warning")

                    # Batch upsert
                    if ids:
                        try:
                            self.chroma_collection.upsert(
                                ids=ids,
                                documents=documents,
                                metadatas=metadatas
                            )
                            stats["synced"] += len(ids)
                        except Exception as e:
                            stats["failed"] += len(ids)
                            self._log(f"Batch upsert failed: {e}", "error")

                    stats["batches"] += 1
                    offset += batch_size

                    if stats["batches"] % 10 == 0:
                        self._log(
                            f"Progress: {stats['synced']}/{stats['total']} memories synced"
                        )

        except sqlite3.Error as e:
            self._log(f"Database error during sync: {e}", "error")

        self._log(
            f"ChromaDB sync complete. Synced: {stats['synced']}, Failed: {stats['failed']}"
        )
        return stats

    def batch_update_decay(self, decay_rate: float = 0.95) -> Dict[str, Any]:
        """
        Batch update strategy for applying memory decay.

        This efficiently applies decay to unconsolidated memories and
        syncs changes to ChromaDB.

        Args:
            decay_rate: Multiplier for memory_strength (e.g., 0.95 = 5% decay)

        Returns:
            Dict with update statistics
        """
        stats = {
            "updated": 0,
            "synced_to_chroma": 0,
            "errors": []
        }

        self._log(f"Applying memory decay with rate {decay_rate}...")

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                # Apply decay to unconsolidated memories with strength > 0.1
                cursor.execute("""
                    UPDATE memories
                    SET memory_strength = memory_strength * ?
                    WHERE consolidated = 0
                    AND memory_strength > 0.1
                """, (decay_rate,))

                stats["updated"] = cursor.rowcount
                conn.commit()

                # If ChromaDB is available, sync the updated memories
                if self.chroma_collection:
                    cursor.execute("""
                        SELECT * FROM memories
                        WHERE consolidated = 0
                        AND memory_strength > 0.1
                    """)

                    for row in cursor.fetchall():
                        try:
                            row_dict = dict(row)
                            metadata = self._build_chroma_metadata(row_dict)
                            content = row_dict["content"]
                            context = row_dict.get("context") or ""

                            if self._sync_memory_to_chroma(
                                row_dict["id"], content, context, metadata
                            ):
                                stats["synced_to_chroma"] += 1
                        except Exception as e:
                            stats["errors"].append(f"Sync error: {e}")

        except sqlite3.Error as e:
            error_msg = f"Database error during decay: {e}"
            stats["errors"].append(error_msg)
            self._log(error_msg, "error")

        self._log(
            f"Decay complete. Updated: {stats['updated']}, "
            f"Synced to ChromaDB: {stats['synced_to_chroma']}"
        )
        return stats

    # =========================================================================
    # COMPLETE MIGRATION
    # =========================================================================

    def run_full_migration(self) -> Dict[str, Any]:
        """
        Execute the complete migration:
        1. Add new SQLite columns
        2. Create optimized indexes
        3. Sync all memories to ChromaDB with new metadata

        Returns:
            Complete migration report
        """
        report = {
            "started_at": datetime.now().isoformat(),
            "sqlite_schema": None,
            "indexes": None,
            "chromadb_sync": None,
            "completed_at": None,
            "success": False,
            "log": []
        }

        self._log("=" * 50)
        self._log("Starting full memory schema migration")
        self._log("=" * 50)

        try:
            # Step 1: SQLite schema migration
            self._log("\n[Step 1/3] Migrating SQLite schema...")
            report["sqlite_schema"] = self.migrate_sqlite_schema()

            # Step 2: Create indexes
            self._log("\n[Step 2/3] Creating consolidation indexes...")
            report["indexes"] = self.create_consolidation_indexes()

            # Step 3: Sync to ChromaDB
            if self.chroma_collection:
                self._log("\n[Step 3/3] Syncing memories to ChromaDB...")
                report["chromadb_sync"] = self.sync_all_memories_to_chroma()
            else:
                self._log("\n[Step 3/3] Skipping ChromaDB sync (collection not provided)")
                report["chromadb_sync"] = {"skipped": True, "reason": "No collection provided"}

            report["success"] = True

        except Exception as e:
            self._log(f"Migration failed with error: {e}", "error")
            report["success"] = False

        report["completed_at"] = datetime.now().isoformat()
        report["log"] = self.migration_log

        self._log("=" * 50)
        status = "completed successfully" if report["success"] else "FAILED"
        self._log(f"Migration {status}")
        self._log("=" * 50)

        return report


# =============================================================================
# CONSOLIDATION QUERY HELPERS
# =============================================================================

class ConsolidationQueries:
    """
    Optimized query methods for the consolidation system.
    Uses the new indexes for efficient data retrieval.

    Usage:
        queries = ConsolidationQueries(db_path)
        candidates = queries.get_unconsolidated_memories(hours=24)
    """

    def __init__(self, db_path: str):
        self.db_path = db_path

    def get_unconsolidated_memories(
        self,
        hours: int = 24,
        limit: int = 50
    ) -> List[tuple]:
        """
        Get unconsolidated memories from the last N hours.

        Uses idx_memories_unconsolidated_recent index.

        Args:
            hours: Number of hours to look back
            limit: Maximum number of memories to return

        Returns:
            List of memory tuples (compatible with _row_to_memory)
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM memories
                WHERE (consolidated = 0 OR consolidated IS NULL)
                AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (cutoff, limit))

            return cursor.fetchall()

    def get_memories_by_strength(
        self,
        min_strength: float = 0.0,
        max_strength: float = 1.0,
        limit: int = 100
    ) -> List[tuple]:
        """
        Get memories within a strength range.

        Uses idx_memories_strength index.

        Args:
            min_strength: Minimum memory_strength
            max_strength: Maximum memory_strength
            limit: Maximum number of memories to return

        Returns:
            List of memory tuples (compatible with _row_to_memory)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM memories
                WHERE COALESCE(memory_strength, 1.0) >= ?
                AND COALESCE(memory_strength, 1.0) <= ?
                ORDER BY memory_strength DESC
                LIMIT ?
            """, (min_strength, max_strength, limit))

            return cursor.fetchall()

    def get_consolidation_candidates(
        self,
        importance_threshold: float = 0.4,
        emotional_threshold: float = 0.4,
        limit: int = 20
    ) -> List[tuple]:
        """
        Get memories that should be prioritized for consolidation.

        Uses idx_memories_consolidation_priority index.

        Criteria:
        - Not yet consolidated
        - High importance OR high emotional intensity
        - Ordered by emotional intensity and importance

        Args:
            importance_threshold: Minimum importance score
            emotional_threshold: Minimum emotional intensity
            limit: Maximum number of memories to return

        Returns:
            List of memory tuples (compatible with _row_to_memory)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM memories
                WHERE (consolidated = 0 OR consolidated IS NULL)
                AND (importance >= ? OR emotional_intensity >= ?)
                ORDER BY emotional_intensity DESC, importance DESC
                LIMIT ?
            """, (importance_threshold, emotional_threshold, limit))

            return cursor.fetchall()

    def get_weak_memories(
        self,
        strength_threshold: float = 0.3,
        limit: int = 50
    ) -> List[tuple]:
        """
        Get weak, unconsolidated memories that may be forgotten.

        Uses idx_memories_decay_candidates index.

        Args:
            strength_threshold: Maximum memory_strength
            limit: Maximum number of memories to return

        Returns:
            List of memory tuples (compatible with _row_to_memory)
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM memories
                WHERE (consolidated = 0 OR consolidated IS NULL)
                AND COALESCE(memory_strength, 1.0) < ?
                ORDER BY memory_strength ASC, importance ASC
                LIMIT ?
            """, (strength_threshold, limit))

            return cursor.fetchall()

    def get_consolidation_stats(self) -> Dict[str, Any]:
        """
        Get statistics about memory consolidation status.

        Returns:
            Dict with consolidation statistics
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            stats = {}

            # Total memories
            cursor.execute("SELECT COUNT(*) FROM memories")
            stats["total_memories"] = cursor.fetchone()[0]

            # Consolidated vs unconsolidated
            cursor.execute("SELECT COUNT(*) FROM memories WHERE consolidated = 1")
            stats["consolidated"] = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE consolidated = 0 OR consolidated IS NULL"
            )
            stats["unconsolidated"] = cursor.fetchone()[0]

            # Average memory strength
            cursor.execute("SELECT AVG(COALESCE(memory_strength, 1.0)) FROM memories")
            avg_strength = cursor.fetchone()[0]
            stats["avg_memory_strength"] = round(avg_strength, 3) if avg_strength else 1.0

            # Weak memories (strength < 0.3)
            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_strength < 0.3"
            )
            stats["weak_memories"] = cursor.fetchone()[0]

            # Strong memories (strength >= 0.8)
            cursor.execute(
                "SELECT COUNT(*) FROM memories WHERE memory_strength >= 0.8"
            )
            stats["strong_memories"] = cursor.fetchone()[0]

            # Average consolidation count
            cursor.execute(
                "SELECT AVG(consolidation_count) FROM memories WHERE consolidated = 1"
            )
            avg_count = cursor.fetchone()[0]
            stats["avg_consolidation_count"] = round(avg_count, 2) if avg_count else 0.0

            return stats


# =============================================================================
# MEMORY UPDATE HELPERS
# =============================================================================

class MemoryConsolidationUpdates:
    """
    Helper methods for updating memory consolidation fields.
    Ensures SQLite and ChromaDB stay in sync.

    Usage:
        updates = MemoryConsolidationUpdates(db_path, chroma_collection)
        updates.mark_consolidated(memory_id)
    """

    def __init__(self, db_path: str, chroma_collection=None):
        self.db_path = db_path
        self.chroma_collection = chroma_collection

    def _get_memory_and_sync(self, memory_id: str, conn: sqlite3.Connection) -> bool:
        """Helper to get memory and sync to ChromaDB."""
        if not self.chroma_collection:
            return True

        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
        row = cursor.fetchone()

        if not row:
            return False

        row_dict = dict(row)
        migration = MemorySchemaMigration(self.db_path, self.chroma_collection)
        metadata = migration._build_chroma_metadata(row_dict)
        return migration._sync_memory_to_chroma(
            memory_id,
            row_dict["content"],
            row_dict.get("context") or "",
            metadata
        )

    def mark_consolidated(
        self,
        memory_id: str,
        increment_count: bool = True
    ) -> bool:
        """
        Mark a memory as consolidated.

        Args:
            memory_id: The memory's unique ID
            increment_count: Whether to increment consolidation_count

        Returns:
            True if successful
        """
        now = datetime.now().isoformat()

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if increment_count:
                    cursor.execute("""
                        UPDATE memories
                        SET consolidated = 1,
                            consolidation_count = COALESCE(consolidation_count, 0) + 1,
                            last_consolidation = ?
                        WHERE id = ?
                    """, (now, memory_id))
                else:
                    cursor.execute("""
                        UPDATE memories
                        SET consolidated = 1,
                            last_consolidation = ?
                        WHERE id = ?
                    """, (now, memory_id))

                if cursor.rowcount == 0:
                    return False

                conn.commit()

                # Sync to ChromaDB
                self._get_memory_and_sync(memory_id, conn)

                return True

        except sqlite3.Error as e:
            logger.error(f"Failed to mark memory {memory_id} as consolidated: {e}")
            return False

    def update_memory_strength(
        self,
        memory_id: str,
        new_strength: float = None,
        boost: float = None
    ) -> bool:
        """
        Update a memory's strength.

        Args:
            memory_id: The memory's unique ID
            new_strength: Set absolute strength value (0.0-1.0)
            boost: Multiply current strength by this factor

        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if new_strength is not None:
                    # Clamp to valid range
                    new_strength = max(0.0, min(1.0, new_strength))
                    cursor.execute("""
                        UPDATE memories
                        SET memory_strength = ?
                        WHERE id = ?
                    """, (new_strength, memory_id))

                elif boost is not None:
                    # FIX BUG #1: Use addition (+) not multiplication (*)
                    # Multiplication was destroying strength (0.5 * 0.15 = 0.075)
                    # Addition correctly boosts (0.5 + 0.15 = 0.65)
                    cursor.execute("""
                        UPDATE memories
                        SET memory_strength = MIN(1.0, COALESCE(memory_strength, 1.0) + ?)
                        WHERE id = ?
                    """, (boost, memory_id))

                else:
                    return False

                if cursor.rowcount == 0:
                    return False

                conn.commit()

                # Sync to ChromaDB
                self._get_memory_and_sync(memory_id, conn)

                return True

        except sqlite3.Error as e:
            logger.error(f"Failed to update memory strength for {memory_id}: {e}")
            return False

    def update_importance(
        self,
        memory_id: str,
        new_importance: float
    ) -> bool:
        """
        Update a memory's importance score.

        Args:
            memory_id: The memory's unique ID
            new_importance: New importance value (0.0-1.0)

        Returns:
            True if successful
        """
        # Clamp to valid range
        new_importance = max(0.0, min(1.0, new_importance))

        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE memories
                    SET importance = ?
                    WHERE id = ?
                """, (new_importance, memory_id))

                if cursor.rowcount == 0:
                    return False

                conn.commit()

                # Sync to ChromaDB
                self._get_memory_and_sync(memory_id, conn)

                return True

        except sqlite3.Error as e:
            logger.error(f"Failed to update importance for {memory_id}: {e}")
            return False

    def increment_consolidation_count(self, memory_id: str) -> int:
        """
        Increment a memory's consolidation count.

        Args:
            memory_id: The memory's unique ID

        Returns:
            New count, or -1 on failure
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE memories
                    SET consolidation_count = COALESCE(consolidation_count, 0) + 1,
                        last_consolidation = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), memory_id))

                if cursor.rowcount == 0:
                    return -1

                # Get new count
                cursor.execute(
                    "SELECT consolidation_count FROM memories WHERE id = ?",
                    (memory_id,)
                )
                row = cursor.fetchone()
                new_count = row[0] if row else -1

                conn.commit()
                return new_count

        except sqlite3.Error as e:
            logger.error(f"Failed to increment consolidation count for {memory_id}: {e}")
            return -1

    def set_encoding_context(self, memory_id: str, context: str) -> bool:
        """
        Set the encoding context for a memory.

        Args:
            memory_id: The memory's unique ID
            context: Description of system state when memory was created

        Returns:
            True if successful
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    UPDATE memories
                    SET encoding_context = ?
                    WHERE id = ?
                """, (context, memory_id))

                if cursor.rowcount == 0:
                    return False

                conn.commit()
                return True

        except sqlite3.Error as e:
            logger.error(f"Failed to set encoding context for {memory_id}: {e}")
            return False


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def run_migration(db_path: str, chroma_collection=None) -> Dict[str, Any]:
    """
    Convenience function to run the complete migration.

    Args:
        db_path: Path to the SQLite database
        chroma_collection: Optional ChromaDB collection

    Returns:
        Migration report
    """
    migration = MemorySchemaMigration(db_path, chroma_collection)
    return migration.run_full_migration()


def verify_migration(db_path: str) -> Dict[str, Any]:
    """
    Verify that the migration was applied correctly.

    Args:
        db_path: Path to the SQLite database

    Returns:
        Verification report
    """
    report = {
        "columns_present": [],
        "columns_missing": [],
        "indexes_present": [],
        "indexes_missing": [],
        "verified": False
    }

    expected_columns = [col[0] for col in NEW_COLUMNS]
    expected_indexes = [idx[0] for idx in NEW_INDEXES]

    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()

            # Check columns
            cursor.execute("PRAGMA table_info(memories)")
            existing_columns = [row[1] for row in cursor.fetchall()]

            for col in expected_columns:
                if col in existing_columns:
                    report["columns_present"].append(col)
                else:
                    report["columns_missing"].append(col)

            # Check indexes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            existing_indexes = [row[0] for row in cursor.fetchall()]

            for idx in expected_indexes:
                if idx in existing_indexes:
                    report["indexes_present"].append(idx)
                else:
                    report["indexes_missing"].append(idx)

            report["verified"] = (
                len(report["columns_missing"]) == 0 and
                len(report["indexes_missing"]) == 0
            )

    except sqlite3.Error as e:
        report["error"] = str(e)

    return report


# =============================================================================
# MAIN (for testing)
# =============================================================================

if __name__ == "__main__":
    import sys

    print("Memory Schema Migration Tool")
    print("=" * 50)

    if len(sys.argv) < 2:
        print("Usage: python memory_schema_migration.py <path_to_db>")
        print("\nExample:")
        print("  python memory_schema_migration.py data/memories_v2/experiences.db")
        print("\nNew columns that will be added:")
        for col in NEW_COLUMNS:
            print(f"  - {col[0]} ({col[1]}, default: {col[2]})")
        print("\nNew indexes that will be created:")
        for idx in NEW_INDEXES:
            print(f"  - {idx[0]}")
        sys.exit(0)

    db_path = sys.argv[1]

    if not os.path.exists(db_path):
        print(f"Error: Database not found at {db_path}")
        sys.exit(1)

    print(f"\nMigrating database: {db_path}")
    print("-" * 50)

    # Run migration
    report = run_migration(db_path)

    # Print results
    print("\n" + "=" * 50)
    print("MIGRATION REPORT")
    print("=" * 50)

    print(f"\nStarted: {report['started_at']}")
    print(f"Completed: {report['completed_at']}")
    print(f"Success: {report['success']}")

    if report['sqlite_schema']:
        print(f"\nSQLite Schema:")
        print(f"  Columns added: {report['sqlite_schema']['columns_added']}")
        print(f"  Columns skipped: {report['sqlite_schema']['columns_skipped']}")

    if report['indexes']:
        print(f"\nIndexes:")
        print(f"  Created: {report['indexes']['indexes_created']}")
        print(f"  Skipped: {report['indexes']['indexes_skipped']}")

    # Verify
    print("\n" + "-" * 50)
    print("Verifying migration...")
    verification = verify_migration(db_path)

    if verification['verified']:
        print("VERIFICATION PASSED - All columns and indexes present")
    else:
        print("VERIFICATION ISSUES:")
        if verification.get('columns_missing'):
            print(f"  Missing columns: {verification['columns_missing']}")
        if verification.get('indexes_missing'):
            print(f"  Missing indexes: {verification['indexes_missing']}")
