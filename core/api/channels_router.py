"""
ARIA Channels REST API
======================

Backs the channels/messaging page of the ARIA GUI.

Endpoints:
  GET  /api/channels              — list all channels with status + metrics
  GET  /api/channels/dashboard    — aggregated dashboard (today's totals)
  GET  /api/channels/{name}       — detail for one channel
  POST /api/channels/{name}/start — start a channel
  POST /api/channels/{name}/stop  — stop a channel
  POST /api/channels/{name}/config— update runtime config
  POST /api/channels/{name}/token — reveal token (masked, POST for security)
  POST /api/channels/{name}/rotate-token — rotate token (manual instruction)

The router is wired into the main FastAPI app from core.api.server via
`init_channels_router(app, channel_manager)`.

Design notes
------------
* Token reveal is POST, not GET — secrets must never leak into browser
  history, server access logs, or referer headers.
* Unknown channel names return 404 via ``api_error()``.
* If a channel has no bot instance (env vars missing), status = "unconfigured".
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from core.api.errors import api_error


# Module-level state set by init_channels_router()
_channel_manager = None


def init_channels_router(app, channel_manager) -> None:
    """Wire the channels router into a FastAPI app."""
    global _channel_manager
    _channel_manager = channel_manager
    app.include_router(router)


router = APIRouter(prefix="/api/channels", tags=["channels"])


# =============================================================================
# Schemas
# =============================================================================

class ConfigBody(BaseModel):
    """Arbitrary key-value config update for a channel."""
    config: Dict[str, Any]


# =============================================================================
# Helpers
# =============================================================================

def _require_manager():
    """Ensure the ChannelManager has been injected."""
    if _channel_manager is None:
        raise api_error(
            "service_unavailable",
            "Channel manager not initialized",
            status_code=503,
        )
    return _channel_manager


def _require_known_channel(name: str):
    """Validate that *name* is a known channel, raise 404 otherwise."""
    mgr = _require_manager()
    if name not in mgr.CHANNELS:
        raise api_error(
            "not_found",
            f"Unknown channel: '{name}'. Valid channels: {list(mgr.CHANNELS.keys())}",
            status_code=404,
        )
    return mgr


# =============================================================================
# Endpoints
# =============================================================================

@router.get("")
def list_channels():
    """List every known channel with status and metrics."""
    mgr = _require_manager()
    return {"channels": mgr.list_channels()}


@router.get("/dashboard")
def dashboard():
    """Aggregated dashboard: messages today, active chats, health."""
    mgr = _require_manager()
    return mgr.get_dashboard()


@router.get("/{name}")
def get_channel(name: str):
    """Detail view for a single channel."""
    mgr = _require_known_channel(name)
    return mgr.get_channel(name)


@router.post("/{name}/start")
def start_channel(name: str):
    """Start a channel (bot must already be instantiated by ARIA)."""
    mgr = _require_known_channel(name)
    result = mgr.start_channel(name)
    if not result.get("ok"):
        error_code = result.get("error", "start_failed")
        status_map = {
            "unconfigured": 400,
            "not_instantiated": 400,
            "start_failed": 500,
        }
        raise api_error(
            error_code,
            result.get("detail"),
            status_code=status_map.get(error_code, 500),
        )
    return result


@router.post("/{name}/stop")
def stop_channel(name: str):
    """Stop a running channel."""
    mgr = _require_known_channel(name)
    result = mgr.stop_channel(name)
    if not result.get("ok"):
        raise api_error(
            result.get("error", "stop_failed"),
            result.get("detail"),
            status_code=500,
        )
    return result


@router.post("/{name}/config")
def update_config(name: str, body: ConfigBody):
    """Update runtime configuration for a channel."""
    mgr = _require_known_channel(name)
    result = mgr.update_config(name, body.config)
    if not result.get("ok"):
        raise api_error(
            result.get("error", "config_failed"),
            result.get("detail"),
            status_code=400,
        )
    return result


@router.post("/{name}/token")
def reveal_token(name: str):
    """
    Reveal the token(s) for a channel (masked — last 4 chars visible).

    This is POST intentionally: secrets must never travel via GET where they
    would end up in browser history, server access logs, and referer headers.
    """
    mgr = _require_known_channel(name)
    return mgr.reveal_token(name)


@router.post("/{name}/rotate-token")
def rotate_token(name: str):
    """
    Request token rotation for a channel.

    Returns instructions for manual rotation — ARIA cannot generate new
    tokens on behalf of third-party providers.
    """
    mgr = _require_known_channel(name)
    result = mgr.rotate_token(name)
    # This always returns ok=False with instructions; surface it as 501
    raise api_error(
        "not_implemented",
        result.get("detail"),
        status_code=501,
    )
