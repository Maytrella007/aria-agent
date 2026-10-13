"""
ARIA - Database Tool
=====================

Execute SQL queries against SQLite (built-in) and PostgreSQL (optional) databases.
Provides safe read/write separation: `query` for SELECT, `execute` for mutations.
"""

import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.database")

DEFAULT_ROW_LIMIT = 100


class DatabaseTool(ToolBase):
    """Query and manipulate SQLite or PostgreSQL databases."""

    name = "database"
    description = (
        "Execute SQL against SQLite or PostgreSQL databases. "
        "Actions: query (SELECT only), execute (INSERT/UPDATE/DELETE), "
        "tables (list tables), schema (show table schema)."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description="Action to perform",
            required=True,
            enum=["query", "execute", "tables", "schema"],
        ),
        ToolParam(
            name="sql",
            type="string",
            description="SQL statement to run (required for query/execute actions)",
            required=False,
        ),
        ToolParam(
            name="db_path",
            type="string",
            description="Path to SQLite database file (uses data_dir default if omitted)",
            required=False,
        ),
        ToolParam(
            name="db_type",
            type="string",
            description="Database type: sqlite or postgres (default: sqlite)",
            required=False,
            default="sqlite",
            enum=["sqlite", "postgres"],
        ),
        ToolParam(
            name="table_name",
            type="string",
            description="Table name (required for schema action)",
            required=False,
        ),
        ToolParam(
            name="limit",
            type="integer",
            description="Max rows to return (default: 100)",
            required=False,
            default=DEFAULT_ROW_LIMIT,
        ),
        ToolParam(
            name="connection_string",
            type="string",
            description="PostgreSQL connection string (for postgres db_type)",
            required=False,
        ),
    ]

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]
        db_type = kwargs.get("db_type", "sqlite")

        if db_type == "postgres":
            return self._handle_postgres(action, kwargs)
        return self._handle_sqlite(action, kwargs)

    # -------------------------------------------------------------------------
    # SQLite
    # -------------------------------------------------------------------------

    def _resolve_db_path(self, kwargs: dict) -> str:
        """Resolve SQLite database file path."""
        db_path = kwargs.get("db_path")
        if db_path:
            return db_path
        data_dir = self.context.get("data_dir", ".")
        return os.path.join(data_dir, "aria.db")

    def _handle_sqlite(self, action: str, kwargs: dict) -> ToolResult:
        db_path = self._resolve_db_path(kwargs)
        limit = kwargs.get("limit", DEFAULT_ROW_LIMIT)

        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if action == "tables":
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row["name"] for row in cursor.fetchall()]
                conn.close()
                return ToolResult(
                    success=True,
                    output=f"Tables: {', '.join(tables) or '(none)'}",
                    data={"tables": tables},
                )

            if action == "schema":
                table_name = kwargs.get("table_name")
                if not table_name:
                    conn.close()
                    return ToolResult(success=False, error="table_name is required for schema action")
                cursor.execute(f"PRAGMA table_info({table_name})")
                columns = [dict(row) for row in cursor.fetchall()]
                conn.close()
                if not columns:
                    return ToolResult(success=False, error=f"Table '{table_name}' not found")
                lines = [f"  {c['name']} {c['type']}{' NOT NULL' if c['notnull'] else ''}{' PK' if c['pk'] else ''}"
                         for c in columns]
                return ToolResult(
                    success=True,
                    output=f"Schema for {table_name}:\n" + "\n".join(lines),
                    data={"columns": columns},
                )

            sql = kwargs.get("sql")
            if not sql:
                conn.close()
                return ToolResult(success=False, error="sql parameter is required for query/execute actions")

            if action == "query":
                stripped = sql.strip().upper()
                if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
                    conn.close()
                    return ToolResult(
                        success=False,
                        error="query action only supports SELECT statements. Use execute for mutations.",
                    )
                cursor.execute(sql)
                rows = [dict(r) for r in cursor.fetchmany(limit)]
                conn.close()
                return ToolResult(
                    success=True,
                    output=json.dumps(rows, indent=2, default=str),
                    data={"rows": rows, "count": len(rows)},
                )

            if action == "execute":
                stripped = sql.strip().upper()
                if stripped.startswith("SELECT"):
                    conn.close()
                    return ToolResult(
                        success=False,
                        error="Use the query action for SELECT statements.",
                    )
                cursor.execute(sql)
                conn.commit()
                affected = cursor.rowcount
                conn.close()
                return ToolResult(
                    success=True,
                    output=f"OK — {affected} row(s) affected.",
                    data={"rowcount": affected},
                )

            conn.close()
            return ToolResult(success=False, error=f"Unknown action: {action}")

        except Exception as e:
            logger.error(f"SQLite error: {e}")
            return ToolResult(success=False, error=str(e))

    # -------------------------------------------------------------------------
    # PostgreSQL
    # -------------------------------------------------------------------------

    def _handle_postgres(self, action: str, kwargs: dict) -> ToolResult:
        try:
            import psycopg2
            import psycopg2.extras
        except ImportError:
            return ToolResult(
                success=False,
                error="psycopg2 is not installed. Install it with: pip install psycopg2-binary",
            )

        conn_str = kwargs.get("connection_string")
        if not conn_str:
            return ToolResult(success=False, error="connection_string is required for postgres db_type")

        limit = kwargs.get("limit", DEFAULT_ROW_LIMIT)

        try:
            conn = psycopg2.connect(conn_str)
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

            if action == "tables":
                cursor.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
                tables = [row["tablename"] for row in cursor.fetchall()]
                conn.close()
                return ToolResult(
                    success=True,
                    output=f"Tables: {', '.join(tables) or '(none)'}",
                    data={"tables": tables},
                )

            if action == "schema":
                table_name = kwargs.get("table_name")
                if not table_name:
                    conn.close()
                    return ToolResult(success=False, error="table_name is required for schema action")
                cursor.execute(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns WHERE table_name = %s ORDER BY ordinal_position",
                    (table_name,),
                )
                columns = [dict(row) for row in cursor.fetchall()]
                conn.close()
                if not columns:
                    return ToolResult(success=False, error=f"Table '{table_name}' not found")
                lines = [f"  {c['column_name']} {c['data_type']}{'' if c['is_nullable'] == 'YES' else ' NOT NULL'}"
                         for c in columns]
                return ToolResult(
                    success=True,
                    output=f"Schema for {table_name}:\n" + "\n".join(lines),
                    data={"columns": columns},
                )

            sql = kwargs.get("sql")
            if not sql:
                conn.close()
                return ToolResult(success=False, error="sql parameter is required for query/execute actions")

            if action == "query":
                stripped = sql.strip().upper()
                if not stripped.startswith("SELECT") and not stripped.startswith("WITH"):
                    conn.close()
                    return ToolResult(
                        success=False,
                        error="query action only supports SELECT statements. Use execute for mutations.",
                    )
                cursor.execute(sql)
                rows = [dict(r) for r in cursor.fetchmany(limit)]
                conn.close()
                return ToolResult(
                    success=True,
                    output=json.dumps(rows, indent=2, default=str),
                    data={"rows": rows, "count": len(rows)},
                )

            if action == "execute":
                stripped = sql.strip().upper()
                if stripped.startswith("SELECT"):
                    conn.close()
                    return ToolResult(
                        success=False,
                        error="Use the query action for SELECT statements.",
                    )
                cursor.execute(sql)
                conn.commit()
                affected = cursor.rowcount
                conn.close()
                return ToolResult(
                    success=True,
                    output=f"OK — {affected} row(s) affected.",
                    data={"rowcount": affected},
                )

            conn.close()
            return ToolResult(success=False, error=f"Unknown action: {action}")

        except Exception as e:
            logger.error(f"PostgreSQL error: {e}")
            return ToolResult(success=False, error=str(e))
