"""
Fact Store for ARIA Memory System

Stores structured facts (subject-predicate-object triples) extracted from
conversations for improved recall of specific details.

Phase 3 of Memory Recall Improvement Plan
"""

import sqlite3
import os
import uuid
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple
import threading


@dataclass
class Fact:
    """A structured fact (subject-predicate-object triple)"""
    id: str
    memory_id: Optional[str]  # Reference to source memory
    subject: str              # "user", "partner", "Tokyo"
    predicate: str            # "received_offer_from", "lives_in", "is"
    object: str               # "TechCorp", "Portland", "dream_city"
    confidence: float         # 0.0 - 1.0
    timestamp: str
    source_text: str          # Original text this was extracted from


class FactStore:
    """
    SQLite-based store for structured facts.

    Enables retrieval of specific details by subject, predicate, or object.
    Thread-safe implementation.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection"""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        """Initialize the facts table"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        conn = self._get_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS facts (
                id TEXT PRIMARY KEY,
                memory_id TEXT,
                subject TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object TEXT NOT NULL,
                confidence REAL DEFAULT 0.8,
                timestamp TEXT NOT NULL,
                source_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Create indexes for efficient searching
        conn.execute('CREATE INDEX IF NOT EXISTS idx_fact_subject ON facts(subject)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_fact_predicate ON facts(predicate)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_fact_object ON facts(object)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_fact_memory_id ON facts(memory_id)')

        conn.commit()

    def add_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        memory_id: Optional[str] = None,
        confidence: float = 0.8,
        source_text: str = ""
    ) -> Fact:
        """Add a new fact to the store"""
        fact = Fact(
            id=str(uuid.uuid4()),
            memory_id=memory_id,
            subject=subject.lower().strip(),
            predicate=predicate.lower().strip(),
            object=obj.strip(),
            confidence=confidence,
            timestamp=datetime.now().isoformat(),
            source_text=source_text[:500]  # Limit source text length
        )

        conn = self._get_connection()
        conn.execute('''
            INSERT OR REPLACE INTO facts
            (id, memory_id, subject, predicate, object, confidence, timestamp, source_text)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (fact.id, fact.memory_id, fact.subject, fact.predicate,
              fact.object, fact.confidence, fact.timestamp, fact.source_text))
        conn.commit()

        return fact

    def add_facts_from_entities(
        self,
        entities,  # ExtractedEntities from entity_extractor
        memory_id: Optional[str] = None,
        source_text: str = ""
    ) -> List[Fact]:
        """
        Add multiple facts from extracted entities.

        Args:
            entities: ExtractedEntities object
            memory_id: Optional reference to source memory
            source_text: Original text for reference

        Returns:
            List of created Fact objects
        """
        facts = []

        # Add location facts
        for location in entities.locations:
            fact = self.add_fact(
                subject="user",
                predicate="mentioned_location",
                obj=location,
                memory_id=memory_id,
                confidence=0.9,
                source_text=source_text
            )
            facts.append(fact)

        # Add people facts
        for person in entities.people:
            fact = self.add_fact(
                subject="user",
                predicate="mentioned_person",
                obj=person,
                memory_id=memory_id,
                confidence=0.85,
                source_text=source_text
            )
            facts.append(fact)

        # Add key facts
        for key_fact in entities.key_facts:
            fact = self.add_fact(
                subject="user",
                predicate="stated_fact",
                obj=key_fact,
                memory_id=memory_id,
                confidence=0.75,
                source_text=source_text
            )
            facts.append(fact)

        return facts

    def search(
        self,
        subject: Optional[str] = None,
        predicate: Optional[str] = None,
        obj: Optional[str] = None,
        limit: int = 10
    ) -> List[Fact]:
        """Search for facts by subject, predicate, and/or object"""
        conditions = []
        params = []

        if subject:
            conditions.append("subject LIKE ?")
            params.append(f"%{subject.lower()}%")
        if predicate:
            conditions.append("predicate LIKE ?")
            params.append(f"%{predicate.lower()}%")
        if obj:
            conditions.append("object LIKE ?")
            params.append(f"%{obj}%")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        conn = self._get_connection()
        cursor = conn.execute(f'''
            SELECT id, memory_id, subject, predicate, object,
                   confidence, timestamp, source_text
            FROM facts
            WHERE {where_clause}
            ORDER BY timestamp DESC
            LIMIT ?
        ''', params + [limit])

        return [self._row_to_fact(row) for row in cursor.fetchall()]

    def search_by_text(self, query: str, limit: int = 10) -> List[Fact]:
        """Search facts by matching query against subject, predicate, or object"""
        query_lower = query.lower()

        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT id, memory_id, subject, predicate, object,
                   confidence, timestamp, source_text
            FROM facts
            WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ?
            ORDER BY confidence DESC, timestamp DESC
            LIMIT ?
        ''', (f"%{query_lower}%", f"%{query_lower}%", f"%{query}%", limit))

        return [self._row_to_fact(row) for row in cursor.fetchall()]

    def get_facts_for_memory(self, memory_id: str) -> List[Fact]:
        """Get all facts associated with a specific memory"""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT id, memory_id, subject, predicate, object,
                   confidence, timestamp, source_text
            FROM facts
            WHERE memory_id = ?
            ORDER BY timestamp DESC
        ''', (memory_id,))

        return [self._row_to_fact(row) for row in cursor.fetchall()]

    def get_all_locations(self, limit: int = 50) -> List[str]:
        """Get all unique locations mentioned"""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT DISTINCT object
            FROM facts
            WHERE predicate = 'mentioned_location'
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))

        return [row[0] for row in cursor.fetchall()]

    def get_all_people(self, limit: int = 50) -> List[str]:
        """Get all unique people mentioned"""
        conn = self._get_connection()
        cursor = conn.execute('''
            SELECT DISTINCT object
            FROM facts
            WHERE predicate = 'mentioned_person'
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))

        return [row[0] for row in cursor.fetchall()]

    def format_facts_for_context(self, facts: List[Fact], max_facts: int = 10) -> str:
        """Format facts as context string for LLM"""
        if not facts:
            return ""

        lines = ["=== KNOWN FACTS ==="]
        for fact in facts[:max_facts]:
            lines.append(f"- {fact.subject} {fact.predicate} {fact.object}")

        return "\n".join(lines)

    def _row_to_fact(self, row) -> Fact:
        """Convert database row to Fact object"""
        return Fact(
            id=row['id'],
            memory_id=row['memory_id'],
            subject=row['subject'],
            predicate=row['predicate'],
            object=row['object'],
            confidence=row['confidence'],
            timestamp=row['timestamp'],
            source_text=row['source_text'] or ""
        )

    def get_stats(self) -> dict:
        """Get statistics about the fact store"""
        conn = self._get_connection()

        total = conn.execute('SELECT COUNT(*) FROM facts').fetchone()[0]
        locations = conn.execute(
            "SELECT COUNT(DISTINCT object) FROM facts WHERE predicate = 'mentioned_location'"
        ).fetchone()[0]
        people = conn.execute(
            "SELECT COUNT(DISTINCT object) FROM facts WHERE predicate = 'mentioned_person'"
        ).fetchone()[0]

        return {
            'total_facts': total,
            'unique_locations': locations,
            'unique_people': people
        }

    def close(self):
        """Close database connection"""
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# Quick test
if __name__ == "__main__":
    import tempfile

    # Create temporary database
    db_path = tempfile.mktemp(suffix='.db')
    store = FactStore(db_path)

    # Add some facts
    store.add_fact("user", "received_offer_from", "Tokyo", confidence=0.9)
    store.add_fact("partner", "lives_in", "Portland", confidence=0.85)
    store.add_fact("partner", "has_family_in", "Portland", confidence=0.8)

    # Search
    print("Search 'Tokyo':", store.search_by_text("Tokyo"))
    print("Search 'Portland':", store.search_by_text("Portland"))
    print("All locations:", store.get_all_locations())
    print("Stats:", store.get_stats())

    # Cleanup
    store.close()
    os.remove(db_path)
