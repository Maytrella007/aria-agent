"""
ARIA API Server - SSE streaming endpoint for GUI clients.

Provides:
  POST /api/chat       — Send a message, get a run_id back
  GET  /api/stream/{run_id} — SSE stream of events for a run (or "all")
  GET  /api/history/{run_id} — Replay missed events (reconnection)
  GET  /api/status     — Health check / system info
  GET  /api/status/full — Full sidebar pulse data
  GET  /api/conversations — List past conversations
  GET  /api/conversations/{session_id} — Full transcript of a session

Usage:
  python -m core.api.server              # default port 8000
  python -m core.api.server --port 3000  # custom port
"""

import asyncio
import json
import logging
import time
import uuid

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from fastapi import FastAPI, Query, Request
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "FastAPI is required for the ARIA API server. "
        "Install with: pip install fastapi uvicorn"
    )

from core.api.errors import api_error
from core.api.conversation_store import (
    save_conversation,
    list_conversations,
    get_conversation,
)


class ChatRequest(BaseModel):
    message: str
    user: str = "web_user"


class ChatResponse(BaseModel):
    run_id: str


app = FastAPI(title="ARIA API", version="0.1.0")

# CORS: restricted to SvelteKit dev server + production domain.
# In production, ARIA_CORS_ORIGIN should be set to the real domain.
import os as _os
_cors_origins = _os.environ.get(
    "ARIA_CORS_ORIGINS",
    "http://localhost:5173,http://localhost:4173"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# BFF shared secret — SvelteKit sends this header on every proxy request.
# FastAPI rejects any request without it (unless ARIA_INTERNAL_SECRET is
# not set, in which case auth is disabled for local dev).
_internal_secret = _os.environ.get("ARIA_INTERNAL_SECRET", "")


@app.middleware("http")
async def verify_internal_auth(request: Request, call_next):
    """BFF auth boundary: reject requests not coming from SvelteKit."""
    # Skip auth check if no secret configured (local dev mode)
    if not _internal_secret:
        return await call_next(request)

    # Allow health check without auth
    if request.url.path == "/api/status":
        return await call_next(request)

    header_value = request.headers.get("X-Internal-Auth", "")
    if header_value != _internal_secret:
        return JSONResponse(
            status_code=403,
            content={"error": "forbidden", "detail": "Invalid internal auth", "status_code": 403},
        )
    return await call_next(request)


# These are set by init_app() before the server starts
_aria_instance = None
_event_bus = None


def init_app(aria_instance):
    """Initialize the API with an ARIA instance."""
    global _aria_instance, _event_bus
    _aria_instance = aria_instance
    _event_bus = aria_instance.event_bus

    # Wire the credentials router (zone 1: LLM keys, zone 2: coding agents,
    # zone 3: services). It needs an AuthManager to read/write credentials.
    auth_manager = getattr(aria_instance, "auth_manager", None)
    if auth_manager is not None:
        try:
            from .credentials_router import init_credentials_router
            init_credentials_router(app, auth_manager)
            logger.info("Credentials router mounted at /api/credentials")
        except Exception as e:
            logger.warning(f"Failed to mount credentials router: {e}")
    else:
        logger.warning("No auth_manager on ARIA instance — credentials API disabled")

    # Wire the memories router — needs the ExperientialMemorySystem instance.
    memory_system = getattr(aria_instance, "memory", None)
    if memory_system is not None:
        try:
            from .memories_router import init_memories_router
            init_memories_router(app, memory_system)
            logger.info("Memories router mounted at /api/memories")
        except Exception as e:
            logger.warning(f"Failed to mount memories router: {e}")
    else:
        logger.warning("No memory system on ARIA instance — memories API disabled")

    # Wire the mirror router — needs the SelfModifier instance from the
    # evolution engine.  Path: aria_instance.evolution.modifier
    self_modifier = None
    evolution = getattr(aria_instance, "evolution", None)
    if evolution is not None:
        self_modifier = getattr(evolution, "modifier", None)
    if self_modifier is not None:
        try:
            from .mirror_router import init_mirror_router
            init_mirror_router(app, self_modifier)
            logger.info("Mirror router mounted at /api/mirror")
        except Exception as e:
            logger.warning(f"Failed to mount mirror router: {e}")
    else:
        logger.warning("No self_modifier on ARIA instance — mirror API disabled")

    # Wire the channels router (Telegram, Discord, Slack management).
    try:
        from core.channels.channel_manager import ChannelManager
        from .channels_router import init_channels_router
        channel_manager = ChannelManager(aria_instance)
        init_channels_router(app, channel_manager)
        logger.info("Channels router mounted at /api/channels")
    except Exception as e:
        logger.warning(f"Failed to mount channels router: {e}")


@app.get("/api/status")
async def status():
    if _aria_instance is None:
        return {"status": "not_initialized"}
    # Extract model info from the LLM provider
    model_name = "unknown"
    provider_name = "unknown"
    max_tokens = 4096
    try:
        llm = _aria_instance.agent_loop.llm
        if hasattr(llm, 'config'):
            model_name = llm.config.model or "unknown"
            provider_name = llm.config.provider.value if hasattr(llm.config.provider, 'value') else str(llm.config.provider)
            max_tokens = llm.config.max_tokens or 4096
        elif hasattr(llm, 'name'):
            provider_name = llm.name
    except Exception:
        pass

    return {
        "status": "ok",
        "llm_available": _aria_instance.agent_loop.llm_available,
        "tools_count": len(_aria_instance.tools) if hasattr(_aria_instance, 'tools') else 0,
        "model": model_name,
        "provider": provider_name,
        "max_tokens": max_tokens,
    }


@app.get("/api/stream/{run_id}")
async def stream_events(run_id: str, request: Request, since_seq: int = 0):
    """SSE endpoint — GUI connects here for real-time events."""
    if _event_bus is None:
        return {"error": "Event bus not initialized"}

    aq, unsub = _event_bus.subscribe_async(maxsize=200)

    # First, replay any missed events (for reconnection)
    if since_seq > 0 and run_id != "all":
        missed = _event_bus.history(run_id, since_seq)
        for ev in missed:
            try:
                aq.put_nowait(ev)
            except asyncio.QueueFull:
                break

    async def generate():
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(aq.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                    continue

                if run_id == "all" or event.run_id == run_id:
                    data = json.dumps(event.to_dict(), default=str)
                    yield f"data: {data}\n\n"

                    # If lifecycle end, close the stream for this run_id
                    if run_id != "all" and event.stream == "lifecycle" and event.event == "end":
                        break
        finally:
            unsub()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest):
    """Send a message. Tokens arrive via SSE at /api/stream/{run_id}."""
    if _aria_instance is None:
        return ChatResponse(run_id="error:not_initialized")

    run_id = str(uuid.uuid4())[:8]

    # Get conversation history (or create empty)
    if not hasattr(_aria_instance, '_api_conversation_history'):
        _aria_instance._api_conversation_history = []

    history = _aria_instance._api_conversation_history

    # Run processing in background thread to not block the event loop
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(_process_in_thread(
        _aria_instance, body.message, history, body.user, run_id
    ))

    return ChatResponse(run_id=run_id)


async def _process_in_thread(aria, message, history, user, run_id):
    """Run agent_loop.process in a thread pool to avoid blocking async."""
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            lambda: aria.agent_loop.process(
                message, history,
                intent_detector=aria.intent if hasattr(aria, 'intent') else None,
                user=user,
                run_id=run_id,
            )
        )
        # Persist the conversation after processing completes.
        try:
            save_conversation(run_id, list(history))
        except Exception as save_err:
            logger.warning(f"Failed to persist conversation {run_id}: {save_err}")
    except Exception as e:
        logger.error(f"Error processing chat message: {e}")
        if _event_bus:
            _event_bus.emit("error", "error", {
                "message": str(e), "type": type(e).__name__,
            }, run_id=run_id)


@app.get("/api/history/{run_id}")
async def get_history(run_id: str, since_seq: int = 0):
    """Replay events for reconnection."""
    if _event_bus is None:
        return []
    events = _event_bus.history(run_id, since_seq)
    return [ev.to_dict() for ev in events]


# =========================================================================
# Sidebar pulse — GET /api/status/full
# =========================================================================

def _humanize_elapsed(ts) -> str:
    """Turn a timestamp (float epoch or ISO string) into '3m ago' style."""
    if ts is None:
        return "never"
    try:
        if isinstance(ts, str):
            epoch = datetime.fromisoformat(ts).timestamp()
        else:
            epoch = float(ts)
        delta = time.time() - epoch
        if delta < 60:
            return f"{int(delta)}s ago"
        if delta < 3600:
            return f"{int(delta // 60)}m ago"
        if delta < 86400:
            return f"{int(delta // 3600)}h ago"
        return f"{int(delta // 86400)}d ago"
    except Exception:
        return "unknown"


@app.get("/api/status/full")
async def status_full():
    """Full sidebar pulse data — everything the GUI sidebar needs in one call."""
    if _aria_instance is None:
        raise api_error("not_initialized", "ARIA instance not initialized", 503)

    aria = _aria_instance

    # --- LLM availability ---
    llm_available = getattr(aria.agent_loop, "llm_available", False)

    # --- Memory count ---
    memory_count = None
    memory = getattr(aria, "memory", None)
    if memory is not None:
        try:
            stats = memory.get_stats()
            memory_count = stats.get("total_memories", 0)
        except Exception:
            memory_count = None

    # --- Cognitive cycle status ---
    cycle_status = "idle"
    last_cycle_run = None
    cognitive_cycle = getattr(aria, "cognitive_cycle", None)
    if cognitive_cycle is not None:
        # CognitiveCycleOrchestrator does not expose a running flag or
        # last-run timestamp directly.  We read what's available.
        last_cycle_run = getattr(cognitive_cycle, "last_run", None)
        if getattr(cognitive_cycle, "_running", False):
            cycle_status = "running"

    # --- Mirror status ---
    mirror_sync = None
    mirror_pending = 0
    mirror = getattr(aria, "mirror", None)
    if mirror is not None:
        try:
            ms = mirror.status()
            mirror_sync = "in sync" if ms.get("exists") else "not initialized"
            # improve_branches counts pending improvement branches
            mirror_pending = ms.get("improve_branches", 0)
        except Exception:
            mirror_sync = "error"

    # --- Active channels ---
    channels_active = 0
    for ch_name in ("telegram", "discord", "slack"):
        ch = getattr(aria, ch_name, None)
        if ch is not None and getattr(ch, "is_running", False):
            channels_active += 1

    # --- Version ---
    try:
        from core import VERSION
    except ImportError:
        VERSION = "unknown"

    return {
        "status": "ok",
        "llm_available": llm_available,
        "memory_count": memory_count,
        "cycle_status": cycle_status,
        "last_cycle_run": _humanize_elapsed(last_cycle_run),
        "mirror_sync": mirror_sync,
        "mirror_pending": mirror_pending,
        "channels_active": channels_active,
        "version": VERSION,
    }


# =========================================================================
# Conversations — GET /api/conversations, GET /api/conversations/{session_id}
# =========================================================================

@app.get("/api/conversations")
async def conversations_list(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    """List past conversations, most recent first."""
    return list_conversations(limit=limit, offset=offset)


@app.get("/api/conversations/{session_id}")
async def conversations_detail(session_id: str):
    """Full transcript of a past chat session."""
    data = get_conversation(session_id)
    if data is None:
        raise api_error("not_found", f"Conversation '{session_id}' not found", 404)
    return data


def main():
    import argparse
    parser = argparse.ArgumentParser(description="ARIA API Server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    # Initialize ARIA
    import os as _os
    import sys
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))))

    from aria import ARIA
    aria = ARIA()
    init_app(aria)

    import uvicorn
    logger.info(f"Starting ARIA API on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
