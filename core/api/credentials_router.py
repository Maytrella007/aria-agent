"""
ARIA Credentials REST API
=========================

Backs the credentials page (`docs/gui-mockups/v3.1/05-credentials.html`).

Three zones:
  1. LLM keys      → /api/credentials/providers
  2. Coding agents → /api/credentials/agents
  3. Services      → /api/credentials/services
                   → /api/credentials/oauth/{provider}/...

The router is wired into the main FastAPI app from core.api.server via
`init_credentials_router(app, auth_manager)`.

Design notes
------------
* GET endpoints are read-only and safe.
* POST/DELETE that touch credentials require an AuthManager instance.
* `install` and `uninstall` for coding agents only return the COMMAND
  the user (or the GUI) should execute. We do not exec uninstall on the
  server side — the user must opt in explicitly via the shell.
* Provider state is one of: 'active' | 'configured' | 'empty' | 'local'.
"""

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.skills.coding_agent import CodingAgentSkill


# Module-level state set by init_credentials_router()
_auth_manager = None


def init_credentials_router(app, auth_manager) -> None:
    """Wire the credentials router into a FastAPI app."""
    global _auth_manager
    _auth_manager = auth_manager
    app.include_router(router)


router = APIRouter(prefix="/api/credentials", tags=["credentials"])


# =============================================================================
# Schemas
# =============================================================================

class KeyBody(BaseModel):
    key: str


class ProviderState(BaseModel):
    name: str
    model: Optional[str] = None
    state: str  # active | configured | empty | local
    key_preview: Optional[str] = None
    auth_methods: list  # ['api_key'] or ['api_key', 'oauth']


class AgentState(BaseModel):
    name: str
    description: str
    binary: str
    installed: bool
    authenticated: bool
    is_default: bool
    env_keys: list
    install_cmd: Optional[str] = None
    install_alt: Optional[str] = None
    auth_cmd: Optional[str] = None


# Catalog of LLM providers exposed by the GUI. Each entry is the canonical
# (hardcoded) display info; runtime state is layered on top via AuthManager.
LLM_CATALOG = [
    {"name": "anthropic",  "model": "claude-sonnet-4-20250514", "auth_methods": ["api_key"]},
    {"name": "openai",     "model": "gpt-4o",                   "auth_methods": ["api_key", "oauth"]},
    {"name": "google",     "model": "gemini-1.5-pro",           "auth_methods": ["api_key"]},
    {"name": "deepseek",   "model": "deepseek-chat",            "auth_methods": ["api_key"]},
    {"name": "openrouter", "model": "anthropic/claude-3.5-sonnet", "auth_methods": ["api_key"]},
    {"name": "ollama",     "model": "llama3",                   "auth_methods": []},
]

SERVICES_CATALOG = [
    {
        "name": "google_workspace",
        "label": "Google Workspace",
        "auth_type": "oauth",
        "scopes": ["gmail", "drive", "calendar"],
        "oauth_provider": "google",
        "planned": False,
    },
    {
        "name": "resend",
        "label": "Resend",
        "auth_type": "api_key",
        "env_key": "RESEND_API_KEY",
        "planned": True,
    },
]


# =============================================================================
# Helpers
# =============================================================================

def _require_auth():
    if _auth_manager is None:
        raise HTTPException(status_code=503, detail="Auth manager not initialized")
    return _auth_manager


# =============================================================================
# Zone 1 — LLM providers
# =============================================================================

@router.get("/providers")
def list_providers():
    """List every known LLM provider with its current state."""
    auth = _require_auth()
    out = []
    for entry in LLM_CATALOG:
        name = entry["name"]
        state = auth.get_provider_state(name)
        preview = None
        if state in ("active", "configured"):
            preview = auth.get_key_preview(name)
        elif state == "local":
            preview = "localhost:11434"
        out.append({
            "name": name,
            "model": entry["model"],
            "state": state,
            "key_preview": preview,
            "auth_methods": entry["auth_methods"],
        })
    return {"providers": out, "active": auth.get_active_provider()}


@router.post("/providers/{provider}/key")
def set_provider_key(provider: str, body: KeyBody):
    """Add or replace the API key for a provider."""
    auth = _require_auth()
    if provider not in {e["name"] for e in LLM_CATALOG}:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    if provider == "ollama":
        raise HTTPException(status_code=400, detail="ollama does not require an API key")
    if not body.key.strip():
        raise HTTPException(status_code=400, detail="key cannot be empty")
    ok = auth.login_with_key(provider, body.key.strip())
    return {"ok": ok, "state": auth.get_provider_state(provider)}


@router.delete("/providers/{provider}/key")
def delete_provider_key(provider: str):
    """Remove the saved API key for a provider."""
    auth = _require_auth()
    removed = auth.delete_credential(provider)
    return {"removed": removed, "state": auth.get_provider_state(provider)}


@router.post("/providers/{provider}/activate")
def activate_provider(provider: str):
    """Mark a provider as the active one (the LLM in current use)."""
    auth = _require_auth()
    if provider not in {e["name"] for e in LLM_CATALOG}:
        raise HTTPException(status_code=404, detail=f"Unknown provider: {provider}")
    state = auth.get_provider_state(provider)
    if state == "empty":
        raise HTTPException(status_code=400, detail=f"{provider} has no credential")
    ok = auth.set_active_provider(provider)
    return {"ok": ok, "active": auth.get_active_provider()}


@router.get("/providers/ollama/models")
def list_ollama_models():
    """List models installed in the local Ollama instance."""
    try:
        from core.llm.llm_providers import LLMProvider
        provider = LLMProvider.create("ollama")
        models = provider.list_models() if hasattr(provider, "list_models") else []
        return {"models": models, "endpoint": "localhost:11434"}
    except Exception as e:
        return {"models": [], "error": str(e)}


# =============================================================================
# Zone 2 — Coding agents
# =============================================================================

@router.get("/agents")
def list_agents():
    """List every known coding agent with detection + auth state."""
    return {"agents": CodingAgentSkill.list_agents_state()}


@router.post("/agents/{name}/default")
def set_default_agent(name: str):
    """Mark a coding agent as the default (used by skills when nothing else specified)."""
    if name not in CodingAgentSkill.AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    ok = CodingAgentSkill.set_default_agent(name)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to persist default agent")
    return {"ok": True, "default": name}


@router.get("/agents/{name}/install")
def get_agent_install(name: str):
    """Return the install command for an agent (caller decides whether to run it)."""
    if name not in CodingAgentSkill.AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    cmd = CodingAgentSkill.get_install_command(name)
    agent = CodingAgentSkill.AGENTS[name]
    return {
        "name": name,
        "install_cmd": cmd,
        "install_alt": agent.get("install_alt"),
        "auth_cmd": agent.get("auth_cmd"),
        "note": "Run this command in your shell. ARIA does not auto-execute installers.",
    }


@router.get("/agents/{name}/uninstall")
def get_agent_uninstall(name: str):
    """Return the uninstall command for an agent (caller decides whether to run it)."""
    if name not in CodingAgentSkill.AGENTS:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    cmd = CodingAgentSkill.get_uninstall_command(name)
    if not cmd:
        raise HTTPException(status_code=404, detail=f"No safe uninstall recipe for {name}")
    return {
        "name": name,
        "uninstall_cmd": cmd,
        "note": "Run this command in your shell. ARIA does not auto-execute uninstallers.",
    }


# =============================================================================
# Zone 3 — Services
# =============================================================================

@router.get("/services")
def list_services():
    """List third-party services with their current connection state."""
    auth = _require_auth()
    out = []
    for svc in SERVICES_CATALOG:
        connected = False
        if svc.get("planned"):
            state = "planned"
        elif svc.get("auth_type") == "oauth":
            provider = svc.get("oauth_provider", "")
            connected = auth.has_credential(provider) if provider else False
            state = "connected" if connected else "unconfigured"
        else:
            state = "unconfigured"
        out.append({**svc, "state": state, "connected": connected})
    return {"services": out}


@router.post("/oauth/{provider}/start")
def oauth_start(provider: str):
    """
    Start an OAuth login flow for a service provider (e.g. 'google').

    Returns an ``auth_url`` that the frontend should open in the user's
    browser.  A background callback listener waits for the redirect.
    Poll ``GET /oauth/{provider}/status`` to detect completion.
    """
    auth = _require_auth()
    try:
        auth_url = auth.start_oauth_for_web(provider)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    if not auth_url:
        raise HTTPException(status_code=500, detail="Could not build OAuth URL — check server logs")
    return {"ok": True, "provider": provider, "auth_url": auth_url}


@router.get("/oauth/{provider}/status")
def oauth_status(provider: str):
    """
    Poll the status of a pending OAuth flow started via ``/start``.

    Returns ``{"status": "pending"|"success"|"error"|"none", ...}``.
    """
    auth = _require_auth()
    return auth.oauth_poll_status(provider)


@router.post("/oauth/{provider}/revoke")
def oauth_revoke(provider: str):
    """Revoke OAuth tokens for a service provider."""
    auth = _require_auth()
    ok = auth.revoke_oauth(provider)
    return {"ok": ok, "provider": provider}
