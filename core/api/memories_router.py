"""
ARIA Memories REST API
======================

Backs the memories page of the GUI.

Three endpoints:
  1. GET /api/memories/dashboard  -- aggregated stats
  2. GET /api/memories            -- paginated list with filters
  3. GET /api/memories/{id}       -- single memory detail

The router is wired into the main FastAPI app from core.api.server via
``init_memories_router(app, memory_system)``.
"""

from typing import Optional

from fastapi import APIRouter, Query

from core.api.errors import api_error


# Module-level state set by init_memories_router()
_memory = None


def init_memories_router(app, memory_system) -> None:
    """Wire the memories router into a FastAPI app."""
    global _memory
    _memory = memory_system
    app.include_router(router)


router = APIRouter(prefix="/api/memories", tags=["memories"])


# =============================================================================
# Helpers
# =============================================================================

def _require_memory():
    if _memory is None:
        raise api_error("service_unavailable", "Memory system not initialized", 503)
    return _memory


def _memory_to_item(mem) -> dict:
    """Convert an ExperientialMemory object to an API-friendly dict."""
    d = mem.to_dict()
    return {
        "id": d.get("id"),
        "content": d.get("content"),
        "context": d.get("context", ""),
        "emotional_tone": d.get("emotional_tone"),
        "emotional_intensity": d.get("emotional_intensity", 0.5),
        "origin": d.get("origin"),
        "involves_people": d.get("involves_people", []),
        "tags": d.get("tags", []),
        "strength": d.get("memory_strength", 1.0),
        "recall_count": d.get("times_recalled", 0),
        "created_at": d.get("timestamp"),
        "consolidated_count": d.get("consolidation_count", 0),
        "importance": d.get("importance", 0.5),
        "is_mine": d.get("is_mine", True),
        "last_recalled": d.get("last_recalled"),
        "connected_memories": d.get("connected_memories", []),
        "relationship_impact": d.get("relationship_impact", {}),
        "duration_feeling": d.get("duration_feeling", "normal"),
        "confidence": d.get("confidence", 0.9),
        "consolidated": d.get("consolidated", False),
        "encoding_context": d.get("encoding_context", ""),
    }


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/dashboard")
def memories_dashboard():
    """Aggregated stats for the memories dashboard."""
    mem = _require_memory()

    try:
        data = mem.dashboard_stats()
    except Exception as e:
        raise api_error("internal_error", f"Failed to load dashboard stats: {e}", 500)

    return data


@router.get("")
def list_memories(
    origin: Optional[str] = Query(None, description="Filter by origin: lived, reflected, discovered, injected, inherited"),
    tone: Optional[str] = Query(None, description="Filter by emotional tone"),
    person: Optional[str] = Query(None, description="Filter by person involved"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    sort: str = Query("recent", description="Sort: recent, strongest, recalled, oldest"),
    q: Optional[str] = Query(None, description="Full-text search query"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated list of memories with filters."""
    mem = _require_memory()

    try:
        result = mem.list_paginated(
            origin=origin,
            tone=tone,
            person=person,
            tag=tag,
            sort=sort,
            q=q,
            limit=limit,
            offset=offset,
        )
    except Exception as e:
        raise api_error("internal_error", f"Failed to list memories: {e}", 500)

    return {
        "items": [_memory_to_item(m) for m in result["items"]],
        "total": result["total"],
        "limit": limit,
        "offset": offset,
    }


@router.get("/{memory_id}")
def get_memory_detail(memory_id: str):
    """Get a single memory by ID."""
    mem = _require_memory()

    try:
        memory = mem.get_memory(memory_id)
    except Exception as e:
        raise api_error("internal_error", f"Failed to retrieve memory: {e}", 500)

    if memory is None:
        raise api_error("not_found", f"Memory {memory_id} not found", 404)

    return _memory_to_item(memory)
