"""
ARIA Mirror REST API
====================

Backs the Mirror page (`docs/gui-mockups/v3.1/04-mirror.html`).

Exposes the notebook-and-book self-modification pipeline as a REST API:
pending changes, reject/approve/promote workflow, freeze/unfreeze,
emergency rollback, and file-level modification history.

The router is wired into the main FastAPI app from core.api.server via
``init_mirror_router(app, self_modifier)``.

Design notes
------------
* GET endpoints are read-only and safe.
* POST endpoints that mutate state include ``initiated_by`` from the
  request body (the frontend passes it from the auth session).
* ``promote`` uses an ``asyncio.Lock`` to prevent double-click races.
* All errors use ``api_error()`` from ``core.api.errors``.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core.api.errors import api_error
from core.cognition.mirror import classify_file_tier, TIER_LABELS


# =========================================================================
# Module-level state set by init_mirror_router()
# =========================================================================

_self_modifier = None
_promote_lock = asyncio.Lock()


def init_mirror_router(app, self_modifier) -> None:
    """Wire the mirror router into a FastAPI app."""
    global _self_modifier
    _self_modifier = self_modifier
    app.include_router(router)


router = APIRouter(prefix="/api/mirror", tags=["mirror"])


# =========================================================================
# Schemas
# =========================================================================

class RejectBody(BaseModel):
    reason: str = "User rejected mirror promotion"
    initiated_by: str = "user"


class RequestChangesBody(BaseModel):
    feedback: str


class PromoteBody(BaseModel):
    ids: List[str]
    reason: str = "User approved mirror promotion"
    initiated_by: str = "user"


class FreezeBody(BaseModel):
    reason: str = "Manual freeze"
    initiated_by: str = "user"


class UnfreezeBody(BaseModel):
    initiated_by: str = "user"


class RollbackBody(BaseModel):
    initiated_by: str = "user"


class ReopenBody(BaseModel):
    initiated_by: str = "user"


# =========================================================================
# Helpers
# =========================================================================

def _require_modifier():
    if _self_modifier is None:
        raise api_error("not_initialized", "Self-modifier not initialized", 503)
    return _self_modifier


def _enrich_with_tier(change: dict) -> dict:
    """Add tier and tier_label to a change dict."""
    rel_path = change.get("target_file", "")
    tier = classify_file_tier(rel_path) if rel_path else 1
    change["tier"] = tier
    change["tier_label"] = TIER_LABELS.get(tier, "unknown")
    return change


def _mod_to_dict(mod) -> dict:
    """Convert a Modification dataclass to a JSON-safe dict."""
    if hasattr(mod, "to_dict"):
        return mod.to_dict()
    return {
        "id": getattr(mod, "id", ""),
        "timestamp": getattr(mod, "timestamp", ""),
        "target_file": getattr(mod, "target_file", ""),
        "modification_type": getattr(mod, "modification_type", ""),
        "reason": getattr(mod, "reason", ""),
        "initiated_by": getattr(mod, "initiated_by", ""),
        "success": getattr(mod, "success", False),
        "error_message": getattr(mod, "error_message", None),
        "status": getattr(mod, "status", ""),
        "validation_result": getattr(mod, "validation_result", None),
    }


# =========================================================================
# GET /api/mirror/status
# =========================================================================

@router.get("/status")
def mirror_status():
    """Mirror status: git state + queue counters."""
    modifier = _require_modifier()

    mirror_info = {}
    if modifier.mirror:
        try:
            mirror_info = modifier.mirror.status()
        except Exception:
            mirror_info = {"error": "Could not read mirror status"}

    counters = modifier.get_counters()

    return {
        "mirror": mirror_info,
        "counters": counters,
    }


# =========================================================================
# GET /api/mirror/pending
# =========================================================================

@router.get("/pending")
def list_pending():
    """List changes awaiting human review, enriched with tier info."""
    modifier = _require_modifier()
    items = modifier.list_pending_changes()
    enriched = [_enrich_with_tier(dict(c)) for c in items]
    return {"items": enriched, "total": len(enriched)}


# =========================================================================
# GET /api/mirror/changes?status=rejected|promoted|all
# =========================================================================

@router.get("/changes")
def list_changes(status: str = Query("all", pattern="^(rejected|promoted|all)$")):
    """List changes filtered by status."""
    modifier = _require_modifier()

    if status == "rejected":
        items = modifier.list_rejected_changes()
    elif status == "promoted":
        items = modifier.list_promoted_changes()
    else:
        items = (
            modifier.list_pending_changes()
            + modifier.list_rejected_changes()
            + modifier.list_promoted_changes()
        )

    enriched = [_enrich_with_tier(dict(c)) for c in items]
    return {"items": enriched, "total": len(enriched)}


# =========================================================================
# GET /api/mirror/changes/{id}
# =========================================================================

@router.get("/changes/{mod_id}")
def get_change_detail(mod_id: str):
    """Full detail for a single change including tier and diff content."""
    modifier = _require_modifier()

    detail = modifier.get_change_detail(mod_id)
    if detail is None:
        raise api_error("not_found", f"Change {mod_id} not found", 404)

    return detail


# =========================================================================
# GET /api/mirror/file-history/{path:path}
# =========================================================================

@router.get("/file-history/{target_file:path}")
def file_history(target_file: str, limit: int = Query(10, ge=1, le=100)):
    """Return last N modifications touching a specific file."""
    modifier = _require_modifier()

    items = modifier.get_file_history(target_file, limit=limit)
    enriched = [_enrich_with_tier(dict(c)) for c in items]
    return {"items": enriched, "total": len(enriched)}


# =========================================================================
# GET /api/mirror/preview-reject/{id}
# =========================================================================

@router.get("/preview-reject/{mod_id}")
def preview_reject(mod_id: str):
    """Preview consequences of rejecting a pending change."""
    modifier = _require_modifier()
    return modifier.preview_reject(mod_id)


# =========================================================================
# GET /api/mirror/preview-promote?ids=id1,id2,...
# =========================================================================

@router.get("/preview-promote")
def preview_promote(ids: str = Query(..., description="Comma-separated modification IDs")):
    """Check cherry-pick feasibility for a set of changes before promoting."""
    modifier = _require_modifier()

    mod_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if not mod_ids:
        raise api_error("validation_failed", "No IDs provided", 400)

    # Check each change exists and is promotable
    previews = []
    all_promotable = True
    for mid in mod_ids:
        change = modifier.get_pending_change(mid)
        if change is None:
            previews.append({
                "id": mid,
                "found": False,
                "promotable": False,
                "error": f"Change {mid} not found in pending queue",
            })
            all_promotable = False
            continue

        rel_path = change.get("target_file", "")
        tier = classify_file_tier(rel_path) if rel_path else 1
        previews.append({
            "id": mid,
            "found": True,
            "promotable": True,
            "target_file": rel_path,
            "tier": tier,
            "tier_label": TIER_LABELS.get(tier, "unknown"),
            "commit_sha": change.get("commit_sha", ""),
        })

    # Check frozen state
    frozen = modifier.is_frozen()
    if frozen:
        all_promotable = False

    return {
        "items": previews,
        "total": len(previews),
        "all_promotable": all_promotable,
        "frozen": frozen,
    }


# =========================================================================
# POST /api/mirror/reject/{id}
# =========================================================================

@router.post("/reject/{mod_id}")
def reject_change(mod_id: str, body: RejectBody):
    """Reject a pending change. Does not delete the git commit."""
    modifier = _require_modifier()

    result = modifier.reject_change(
        mod_id,
        reason=body.reason,
        initiated_by=body.initiated_by,
    )
    d = _mod_to_dict(result)
    if not result.success:
        raise api_error(
            "reject_failed",
            result.error_message or "Reject failed",
            400,
        )
    _publish_mirror_event("queue_changed", {"action": "rejected", "mod_id": mod_id})
    return _enrich_with_tier(d)


# =========================================================================
# POST /api/mirror/request-changes/{id}
# =========================================================================

@router.post("/request-changes/{mod_id}")
def request_changes(mod_id: str, body: RequestChangesBody):
    """Store feedback on a pending change for future regeneration.

    This does NOT trigger regeneration -- it only persists the feedback
    in the pending YAML and marks the change as ``feedback_sent``.
    """
    modifier = _require_modifier()

    pending = modifier._load_pending()
    target_change = None
    for item in pending.get("changes", []):
        if item.get("id") == mod_id:
            target_change = item
            break

    if target_change is None:
        raise api_error("not_found", f"Change {mod_id} not found", 404)

    target_change["feedback_sent"] = True
    target_change["feedback"] = body.feedback
    target_change["feedback_at"] = datetime.now().isoformat()
    modifier._save_pending(pending)

    _publish_mirror_event("queue_changed", {"action": "request_changes", "mod_id": mod_id})
    return _enrich_with_tier(dict(target_change))


# =========================================================================
# POST /api/mirror/reopen/{id}
# =========================================================================

@router.post("/reopen/{mod_id}")
def reopen_change(mod_id: str, body: ReopenBody):
    """Reopen a previously rejected change."""
    modifier = _require_modifier()

    result = modifier.reopen_change(mod_id, initiated_by=body.initiated_by)
    d = _mod_to_dict(result)
    if not result.success:
        raise api_error(
            "reopen_failed",
            result.error_message or "Reopen failed",
            400,
        )
    _publish_mirror_event("queue_changed", {"action": "reopened", "mod_id": mod_id})
    return _enrich_with_tier(d)


# =========================================================================
# POST /api/mirror/promote
# =========================================================================

@router.post("/promote")
async def promote_changes(body: PromoteBody):
    """Promote (cherry-pick) selected changes from develop to main+live.

    Uses an asyncio lock to prevent double-click race conditions.
    """
    modifier = _require_modifier()

    if not body.ids:
        raise api_error("validation_failed", "No IDs provided", 400)

    async with _promote_lock:
        results = modifier.promote_selected(
            body.ids,
            reason=body.reason,
            initiated_by=body.initiated_by,
        )

    items = [_enrich_with_tier(_mod_to_dict(r)) for r in results]
    all_ok = all(r.success for r in results)

    if not all_ok:
        # Return 207 Multi-Status: some may have succeeded
        return {
            "items": items,
            "total": len(items),
            "all_ok": False,
            "post_promote_state": None,
        }

    # On full success, include the post-promote state for the frontend
    post_state = modifier.get_post_promote_state()
    _publish_mirror_event("promoted", {"ids": body.ids, "count": len(body.ids)})
    return {
        "items": items,
        "total": len(items),
        "all_ok": True,
        "post_promote_state": post_state,
    }


# =========================================================================
# POST /api/mirror/freeze
# =========================================================================

@router.post("/freeze")
def freeze_mirror(body: FreezeBody):
    """Activate the kill switch. All promotions are blocked until unfreeze."""
    modifier = _require_modifier()

    ok = modifier.freeze(reason=body.reason, initiated_by=body.initiated_by)
    _publish_mirror_event("frozen", {"reason": body.reason})
    return {
        "ok": ok,
        "frozen": modifier.is_frozen(),
        "reason": body.reason,
        "initiated_by": body.initiated_by,
    }


# =========================================================================
# POST /api/mirror/unfreeze
# =========================================================================

@router.post("/unfreeze")
def unfreeze_mirror(body: UnfreezeBody):
    """Deactivate the kill switch. Promotions resume."""
    modifier = _require_modifier()

    ok = modifier.unfreeze(initiated_by=body.initiated_by)
    _publish_mirror_event("unfrozen", {})
    return {
        "ok": ok,
        "frozen": modifier.is_frozen(),
    }


# =========================================================================
# POST /api/mirror/emergency-rollback
# =========================================================================

@router.post("/emergency-rollback")
def emergency_rollback(body: RollbackBody):
    """Revert main to before the last promotion and freeze the mirror."""
    modifier = _require_modifier()

    result = modifier.emergency_rollback(initiated_by=body.initiated_by)
    if not result.get("success"):
        raise api_error(
            "rollback_failed",
            result.get("error", "Emergency rollback failed"),
            400,
        )
    _publish_mirror_event("rollback", {"restored": result.get("restored", [])})
    return result


# =============================================================================
# SSE — real-time mirror events
# =============================================================================

# Mirror event queue: mutative endpoints push events here, SSE reads them.
# Simple in-process pubsub. For single-user this is sufficient.

import queue as _queue
import json as _json

_mirror_subscribers: list[_queue.Queue] = []
_mirror_sub_lock = asyncio.Lock()


def _publish_mirror_event(event_type: str, data: dict | None = None):
    """Push an event to all SSE subscribers. Called from mutative endpoints."""
    payload = _json.dumps({"type": event_type, **(data or {})}, default=str)
    dead = []
    for i, q in enumerate(_mirror_subscribers):
        try:
            q.put_nowait(payload)
        except _queue.Full:
            dead.append(i)
    # Cleanup dead subscribers
    for i in reversed(dead):
        try:
            _mirror_subscribers.pop(i)
        except IndexError:
            pass


@router.get("/events")
async def mirror_events(request: Request):
    """SSE stream of mirror events.

    Events emitted:
      - queue_changed      — a change was rejected, reopened, or request-changes'd
      - promoted           — changes were promoted to live
      - frozen             — mirror was frozen
      - unfrozen           — mirror was unfrozen
      - rollback           — emergency rollback executed
      - heartbeat          — keepalive every 30s

    The frontend subscribes on page load and updates the queue
    reactively without polling.
    """
    subscriber: _queue.Queue = _queue.Queue(maxsize=100)
    _mirror_subscribers.append(subscriber)

    async def generate():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    # Check for events with a short timeout
                    payload = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: subscriber.get(timeout=30.0)
                    )
                    yield f"data: {payload}\n\n"
                except _queue.Empty:
                    # Send heartbeat keepalive
                    yield ": heartbeat\n\n"
        finally:
            try:
                _mirror_subscribers.remove(subscriber)
            except ValueError:
                pass

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
