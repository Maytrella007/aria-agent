"""
ARIA - Auth Manager
====================

Unified credential management with support for:
- API keys (direct env vars or config)
- OAuth 2.0 (authorization code flow with PKCE + state validation)
- OAuth 2.0 Device Code flow (for headless/terminal environments)
- Bearer tokens (generic)

Features:
- Multiple credentials per provider (main + backup)
- Automatic rotation on failure
- Cooldown by error type (rate_limit, billing, auth)
- OAuth token auto-refresh before expiry
- PKCE (S256) for secure authorization code flow
- CSRF protection via state parameter
- Device code flow for terminal-only environments
- Provider presets (Google, GitHub, OpenAI)
- Persistent OAuth token storage

Inspired by OpenClaw's auth-profiles system, adapted for ARIA.
"""

import hashlib
import base64
import json
import os
import secrets
import time
import yaml
import logging
import threading
import webbrowser
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urlencode, parse_qs, urlparse

logger = logging.getLogger("aria.auth")


# =============================================================================
# ENUMS & TYPES
# =============================================================================

class AuthType(Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"
    TOKEN = "token"


class ErrorType(Enum):
    RATE_LIMIT = "rate_limit"
    BILLING = "billing"
    AUTH = "auth"
    NETWORK = "network"
    UNKNOWN = "unknown"


# Cooldown durations per error type (seconds)
DEFAULT_COOLDOWNS = {
    ErrorType.RATE_LIMIT: 30,
    ErrorType.BILLING: 300,
    ErrorType.AUTH: 3600,
    ErrorType.NETWORK: 10,
    ErrorType.UNKNOWN: 60,
}


# =============================================================================
# PKCE (Proof Key for Code Exchange - RFC 7636)
# =============================================================================

def generate_pkce() -> Tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge).
    """
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def generate_state() -> str:
    """Generate a random state parameter for CSRF protection."""
    return base64.urlsafe_b64encode(secrets.token_bytes(16)).rstrip(b"=").decode("ascii")


# =============================================================================
# OAUTH PROVIDER PRESETS
# =============================================================================

OAUTH_PRESETS = {
    "google": {
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scope": (
            "openid email profile "
            "https://www.googleapis.com/auth/gmail.readonly "
            "https://www.googleapis.com/auth/gmail.send "
            "https://www.googleapis.com/auth/drive.file "
            "https://www.googleapis.com/auth/drive.readonly "
            "https://www.googleapis.com/auth/calendar.events "
            "https://www.googleapis.com/auth/calendar.readonly"
        ),
        "supports_pkce": True,
        "supports_device_code": False,
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "requires_client_id": True,
        "setup_instructions": (
            "1. Go to https://console.cloud.google.com/apis/credentials\n"
            "2. Create a project (or select existing)\n"
            "3. Enable APIs: Gmail API, Google Drive API, Google Calendar API\n"
            "4. Create OAuth 2.0 Client ID → Desktop application\n"
            "5. Use: auth google setup <client_id> <client_secret>"
        ),
    },
    "github": {
        "authorize_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "revoke_url": "",
        "device_code_url": "https://github.com/login/device/code",
        "scope": "read:user user:email",
        "supports_pkce": False,
        "supports_device_code": True,
    },
    "openai": {
        "authorize_url": "https://auth0.openai.com/authorize",
        "token_url": "https://auth0.openai.com/oauth/token",
        "device_code_url": "https://auth0.openai.com/oauth/device/code",
        "revoke_url": "",
        "scope": "openid profile email offline_access",
        "supports_pkce": True,
        "supports_device_code": True,
        "extra_params": {"audience": "https://api.openai.com/v1"},
    },
    "microsoft": {
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "revoke_url": "",
        "scope": "openid profile email offline_access",
        "supports_pkce": True,
        "supports_device_code": True,
        "device_code_url": "https://login.microsoftonline.com/common/oauth2/v2.0/devicecode",
    },
}


# =============================================================================
# CALLBACK HTML
# =============================================================================

CALLBACK_SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>ARIA - Authorization Complete</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               display: flex; justify-content: center; align-items: center; height: 100vh;
               margin: 0; background: #0a0a0a; color: #e0e0e0; }
        .card { text-align: center; padding: 40px; border-radius: 12px;
                background: #1a1a2e; border: 1px solid #333; max-width: 400px; }
        h2 { color: #00d4aa; margin-bottom: 10px; }
        p { color: #888; }
        .check { font-size: 48px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="card">
        <div class="check">&#10003;</div>
        <h2>Authorization Successful</h2>
        <p>ARIA has been authorized. You can close this window and return to the terminal.</p>
    </div>
</body>
</html>"""

CALLBACK_ERROR_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>ARIA - Authorization Failed</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               display: flex; justify-content: center; align-items: center; height: 100vh;
               margin: 0; background: #0a0a0a; color: #e0e0e0; }
        .card { text-align: center; padding: 40px; border-radius: 12px;
                background: #1a1a2e; border: 1px solid #333; max-width: 400px; }
        h2 { color: #ff4444; margin-bottom: 10px; }
        p { color: #888; }
        .x { font-size: 48px; margin-bottom: 20px; }
    </style>
</head>
<body>
    <div class="card">
        <div class="x">&#10007;</div>
        <h2>Authorization Failed</h2>
        <p>Error: {error}</p>
        <p>Please try again from the terminal.</p>
    </div>
</body>
</html>"""


# =============================================================================
# OAUTH CREDENTIAL
# =============================================================================

@dataclass
class OAuthCredential:
    """OAuth 2.0 credential with token lifecycle management."""
    client_id: str
    client_secret: str
    token_url: str
    scope: str = ""
    authorize_url: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0  # Unix timestamp

    def is_expired(self) -> bool:
        if not self.access_token:
            return True
        # Treat as expired 60s before actual expiry (buffer)
        return time.time() >= (self.expires_at - 60)

    def has_refresh_token(self) -> bool:
        return bool(self.refresh_token)

    def to_dict(self) -> dict:
        return {
            "client_id": self.client_id,
            "token_url": self.token_url,
            "scope": self.scope,
            "authorize_url": self.authorize_url,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }

    @classmethod
    def from_dict(cls, data: dict, client_secret: str = "") -> "OAuthCredential":
        return cls(
            client_id=data.get("client_id", ""),
            client_secret=client_secret,
            token_url=data.get("token_url", ""),
            scope=data.get("scope", ""),
            authorize_url=data.get("authorize_url", ""),
            access_token=data.get("access_token", ""),
            refresh_token=data.get("refresh_token", ""),
            expires_at=data.get("expires_at", 0.0),
        )


# =============================================================================
# AUTH PROFILE
# =============================================================================

@dataclass
class AuthProfile:
    """A single credential for a provider."""
    profile_id: str
    provider: str
    auth_type: AuthType
    # For API_KEY type
    api_key: str = ""
    # For OAUTH type
    oauth: Optional[OAuthCredential] = None
    # For TOKEN type
    token: str = ""
    # Tracking
    last_used: float = 0.0
    failure_count: int = 0
    cooldown_until: float = 0.0
    total_successes: int = 0
    total_failures: int = 0

    def is_available(self) -> bool:
        """True if not in cooldown and has valid credentials."""
        if time.time() < self.cooldown_until:
            return False
        if self.auth_type == AuthType.API_KEY:
            return bool(self.api_key)
        elif self.auth_type == AuthType.OAUTH:
            return self.oauth is not None and bool(self.oauth.access_token)
        elif self.auth_type == AuthType.TOKEN:
            return bool(self.token)
        return False

    def needs_refresh(self) -> bool:
        """True if OAuth token is expired or about to expire."""
        if self.auth_type != AuthType.OAUTH or not self.oauth:
            return False
        return self.oauth.is_expired() and self.oauth.has_refresh_token()

    def get_header(self) -> Dict[str, str]:
        """Return the authorization header for this credential."""
        if self.auth_type == AuthType.API_KEY:
            return {"Authorization": f"Bearer {self.api_key}"}
        elif self.auth_type == AuthType.OAUTH:
            if self.oauth and self.oauth.access_token:
                return {"Authorization": f"Bearer {self.oauth.access_token}"}
        elif self.auth_type == AuthType.TOKEN:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def get_key_value(self) -> str:
        """Return the raw key/token string for SDK clients."""
        if self.auth_type == AuthType.API_KEY:
            return self.api_key
        elif self.auth_type == AuthType.OAUTH:
            return self.oauth.access_token if self.oauth else ""
        elif self.auth_type == AuthType.TOKEN:
            return self.token
        return ""


# =============================================================================
# OAUTH FLOW
# =============================================================================

class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for OAuth callback with state validation."""

    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        code = query.get("code", [None])[0]
        error = query.get("error", [None])[0]
        state = query.get("state", [None])[0]

        # Validate state parameter (CSRF protection)
        expected_state = getattr(self.server, "expected_state", None)
        if expected_state and state != expected_state:
            self.server.auth_code = None
            self.server.auth_error = "state_mismatch"
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(CALLBACK_ERROR_HTML.format(error="State mismatch — possible CSRF attack").encode())
            logger.warning("OAuth callback: state mismatch (CSRF protection triggered)")
            return

        if code:
            self.server.auth_code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(CALLBACK_SUCCESS_HTML.encode())
        else:
            self.server.auth_code = None
            self.server.auth_error = error or "unknown"
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(CALLBACK_ERROR_HTML.format(error=error or "unknown").encode())

    def log_message(self, format, *args):
        pass


class OAuthFlow:
    """Handles OAuth 2.0 authorization code flow with PKCE + state."""

    CALLBACK_PORT = 8900
    CALLBACK_PATH = "/callback"

    def __init__(self, data_dir: str = "data/auth"):
        self.data_dir = data_dir
        self.tokens_file = os.path.join(data_dir, "oauth_tokens.yaml")
        # Pending async OAuth flows: provider -> {server, credential, ...}
        self._pending_flows: dict = {}

    # -------------------------------------------------------------------------
    # Async Authorization (for web UI — non-blocking)
    # -------------------------------------------------------------------------

    def start_authorize(self, credential: OAuthCredential, provider: str,
                        use_pkce: bool = True, provider_preset: str = None,
                        timeout: int = 300) -> str | None:
        """
        Build the OAuth authorization URL and start a background callback
        listener. Returns the auth_url for the frontend to open in the
        user's browser. The callback server runs in a daemon thread.

        Call ``finish_authorize`` (or poll ``pending_status``) once the
        user completes the flow in their browser.
        """
        import threading

        # Apply provider preset
        if provider_preset and provider_preset in OAUTH_PRESETS:
            preset = OAUTH_PRESETS[provider_preset]
            if not credential.authorize_url:
                credential.authorize_url = preset["authorize_url"]
            if not credential.token_url:
                credential.token_url = preset["token_url"]
            if not credential.scope:
                credential.scope = preset.get("scope", "")
            use_pkce = preset.get("supports_pkce", use_pkce)

        if not credential.authorize_url:
            logger.error("No authorize_url configured for OAuth credential")
            return None

        redirect_uri = f"http://localhost:{self.CALLBACK_PORT}{self.CALLBACK_PATH}"

        # Generate PKCE pair
        code_verifier = None
        code_challenge = None
        if use_pkce:
            code_verifier, code_challenge = generate_pkce()

        # Generate state for CSRF protection
        state = generate_state()

        # Build authorization URL
        params = {
            "client_id": credential.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": credential.scope,
            "state": state,
        }
        if use_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        if provider_preset and provider_preset in OAUTH_PRESETS:
            extra = OAUTH_PRESETS[provider_preset].get("extra_params", {})
            params.update(extra)

        auth_url = f"{credential.authorize_url}?{urlencode(params)}"

        # Start local callback server in a background thread
        server = HTTPServer(("localhost", self.CALLBACK_PORT), _OAuthCallbackHandler)
        server.auth_code = None
        server.auth_error = None
        server.expected_state = state
        server.timeout = timeout

        def _listen():
            server.handle_request()

        thread = threading.Thread(target=_listen, daemon=True)
        thread.start()

        # Store pending flow
        self._pending_flows[provider] = {
            "server": server,
            "thread": thread,
            "credential": credential,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "auth_url": auth_url,
        }

        logger.info(f"OAuth flow started for {provider}, callback on :{self.CALLBACK_PORT}")
        return auth_url

    def pending_status(self, provider: str) -> dict:
        """
        Check whether a pending OAuth flow has completed.

        Returns:
            {"status": "pending"} — still waiting for callback
            {"status": "success"} — tokens obtained
            {"status": "error", "detail": "..."} — authorization failed
            {"status": "none"} — no pending flow for this provider
        """
        flow = self._pending_flows.get(provider)
        if not flow:
            return {"status": "none"}

        server = flow["server"]
        thread = flow["thread"]

        if thread.is_alive():
            return {"status": "pending"}

        # Thread finished — callback was received (or timeout)
        if server.auth_code:
            ok = self._exchange_code(
                flow["credential"], server.auth_code,
                flow["redirect_uri"], flow["code_verifier"]
            )
            del self._pending_flows[provider]
            if ok:
                return {"status": "success"}
            return {"status": "error", "detail": "Token exchange failed"}

        detail = server.auth_error or "Authorization timed out or was denied"
        del self._pending_flows[provider]
        return {"status": "error", "detail": detail}

    # -------------------------------------------------------------------------
    # Authorization Code Flow (with PKCE + state)
    # -------------------------------------------------------------------------

    def authorize(self, credential: OAuthCredential, timeout: int = 120,
                  use_pkce: bool = True, provider_preset: str = None) -> bool:
        """
        Start OAuth authorization flow with PKCE and state protection.
        Opens browser, waits for callback, exchanges code for tokens.
        Returns True on success.
        """
        # Apply provider preset if available
        if provider_preset and provider_preset in OAUTH_PRESETS:
            preset = OAUTH_PRESETS[provider_preset]
            if not credential.authorize_url:
                credential.authorize_url = preset["authorize_url"]
            if not credential.token_url:
                credential.token_url = preset["token_url"]
            if not credential.scope:
                credential.scope = preset.get("scope", "")
            use_pkce = preset.get("supports_pkce", use_pkce)

        if not credential.authorize_url:
            logger.error("No authorize_url configured for OAuth credential")
            return False

        redirect_uri = f"http://localhost:{self.CALLBACK_PORT}{self.CALLBACK_PATH}"

        # Generate PKCE pair
        code_verifier = None
        if use_pkce:
            code_verifier, code_challenge = generate_pkce()

        # Generate state for CSRF protection
        state = generate_state()

        # Build authorization URL
        params = {
            "client_id": credential.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": credential.scope,
            "state": state,
        }
        if use_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = "S256"

        # Add provider-specific extra params
        if provider_preset and provider_preset in OAUTH_PRESETS:
            extra = OAUTH_PRESETS[provider_preset].get("extra_params", {})
            params.update(extra)

        auth_url = f"{credential.authorize_url}?{urlencode(params)}"

        # Start local HTTP server for callback
        server = HTTPServer(("localhost", self.CALLBACK_PORT), _OAuthCallbackHandler)
        server.auth_code = None
        server.auth_error = None
        server.expected_state = state  # For CSRF validation
        server.timeout = timeout

        print(f"\n[AUTH] Opening browser for authorization...")
        print(f"[AUTH] If browser doesn't open, visit:\n  {auth_url}\n")

        try:
            webbrowser.open(auth_url)
        except Exception:
            pass  # URL already printed

        # Wait for callback
        server.handle_request()

        if not server.auth_code:
            logger.error(f"OAuth authorization failed: {server.auth_error}")
            return False

        # Exchange code for tokens (with PKCE verifier)
        return self._exchange_code(credential, server.auth_code, redirect_uri, code_verifier)

    def _exchange_code(self, credential: OAuthCredential, code: str,
                       redirect_uri: str, code_verifier: str = None) -> bool:
        """Exchange authorization code for access token (with optional PKCE verifier)."""
        try:
            import requests
        except ImportError:
            logger.error("requests library required for OAuth. pip install requests")
            return False

        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": credential.client_id,
            "client_secret": credential.client_secret,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        try:
            headers = {"Accept": "application/json"}
            resp = requests.post(credential.token_url, data=data, headers=headers, timeout=30)
            resp.raise_for_status()
            token_data = resp.json()

            credential.access_token = token_data["access_token"]
            credential.refresh_token = token_data.get("refresh_token", "")
            expires_in = token_data.get("expires_in", 3600)
            credential.expires_at = time.time() + expires_in

            logger.info(f"OAuth authorization successful, expires in {expires_in}s")
            return True

        except Exception as e:
            logger.error(f"OAuth token exchange failed: {e}")
            return False

    # -------------------------------------------------------------------------
    # Device Code Flow (for headless/terminal environments)
    # -------------------------------------------------------------------------

    def authorize_device(self, credential: OAuthCredential,
                         device_code_url: str = None,
                         provider_preset: str = None,
                         poll_interval: int = 5,
                         timeout: int = 300) -> bool:
        """
        OAuth 2.0 Device Code flow for terminal-only environments.
        Shows a code to the user, they authorize in browser, we poll for token.
        """
        try:
            import requests
        except ImportError:
            logger.error("requests library required for OAuth")
            return False

        # Resolve device code URL
        if not device_code_url and provider_preset and provider_preset in OAUTH_PRESETS:
            device_code_url = OAUTH_PRESETS[provider_preset].get("device_code_url")

        if not device_code_url:
            logger.error("No device_code_url configured")
            return False

        # Apply preset for token_url if needed
        if provider_preset and provider_preset in OAUTH_PRESETS:
            preset = OAUTH_PRESETS[provider_preset]
            if not credential.token_url:
                credential.token_url = preset["token_url"]
            if not credential.scope:
                credential.scope = preset.get("scope", "")

        # Step 1: Request device code
        try:
            resp = requests.post(device_code_url, data={
                "client_id": credential.client_id,
                "scope": credential.scope,
            }, headers={"Accept": "application/json"}, timeout=30)
            resp.raise_for_status()
            device_data = resp.json()
        except Exception as e:
            logger.error(f"Device code request failed: {e}")
            return False

        device_code = device_data.get("device_code", "")
        user_code = device_data.get("user_code", "")
        verification_uri = device_data.get("verification_uri") or device_data.get("verification_url", "")
        interval = device_data.get("interval", poll_interval)
        expires_in = device_data.get("expires_in", timeout)

        if not device_code or not user_code:
            logger.error(f"Invalid device code response: {device_data}")
            return False

        # Step 2: Show user the code
        print(f"\n[AUTH] Device Authorization")
        print(f"[AUTH] Go to: {verification_uri}")
        print(f"[AUTH] Enter code: {user_code}")
        print(f"[AUTH] Waiting for authorization (expires in {expires_in}s)...\n")

        try:
            webbrowser.open(verification_uri)
        except Exception:
            pass

        # Step 3: Poll for token
        deadline = time.time() + min(expires_in, timeout)
        while time.time() < deadline:
            time.sleep(interval)

            try:
                resp = requests.post(credential.token_url, data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": credential.client_id,
                }, headers={"Accept": "application/json"}, timeout=30)

                token_data = resp.json()

                # Check for pending/errors
                error = token_data.get("error", "")
                if error == "authorization_pending":
                    continue
                elif error == "slow_down":
                    interval += 2
                    continue
                elif error == "expired_token":
                    logger.error("Device code expired")
                    return False
                elif error == "access_denied":
                    logger.error("User denied authorization")
                    return False
                elif error:
                    logger.error(f"Device code error: {error}")
                    return False

                # Success
                if "access_token" in token_data:
                    credential.access_token = token_data["access_token"]
                    credential.refresh_token = token_data.get("refresh_token", "")
                    expires_in_token = token_data.get("expires_in", 3600)
                    credential.expires_at = time.time() + expires_in_token
                    logger.info(f"Device authorization successful, expires in {expires_in_token}s")
                    print("[AUTH] Authorization successful!")
                    return True

            except Exception as e:
                logger.debug(f"Device code poll error: {e}")
                continue

        logger.error("Device authorization timed out")
        return False

    def refresh(self, credential: OAuthCredential) -> bool:
        """Refresh an expired OAuth token."""
        if not credential.refresh_token:
            logger.warning("No refresh token available")
            return False

        try:
            import requests
        except ImportError:
            return False

        data = {
            "grant_type": "refresh_token",
            "refresh_token": credential.refresh_token,
            "client_id": credential.client_id,
            "client_secret": credential.client_secret,
        }

        try:
            resp = requests.post(credential.token_url, data=data, timeout=30)
            resp.raise_for_status()
            token_data = resp.json()

            credential.access_token = token_data["access_token"]
            if "refresh_token" in token_data:
                credential.refresh_token = token_data["refresh_token"]
            expires_in = token_data.get("expires_in", 3600)
            credential.expires_at = time.time() + expires_in

            logger.info(f"OAuth token refreshed, expires in {expires_in}s")
            return True

        except Exception as e:
            logger.error(f"OAuth refresh failed: {e}")
            return False

    def revoke(self, credential: OAuthCredential, revoke_url: str = None) -> bool:
        """Revoke an OAuth token."""
        if not revoke_url or not credential.access_token:
            credential.access_token = ""
            credential.refresh_token = ""
            credential.expires_at = 0.0
            return True

        try:
            import requests
            resp = requests.post(revoke_url, data={
                "token": credential.access_token,
                "client_id": credential.client_id,
                "client_secret": credential.client_secret,
            }, timeout=30)
            credential.access_token = ""
            credential.refresh_token = ""
            credential.expires_at = 0.0
            return resp.ok
        except Exception as e:
            logger.error(f"OAuth revoke failed: {e}")
            credential.access_token = ""
            credential.refresh_token = ""
            credential.expires_at = 0.0
            return False

    def save_tokens(self, profiles: Dict[str, AuthProfile]):
        """Persist OAuth tokens to disk."""
        os.makedirs(self.data_dir, exist_ok=True)
        tokens = {}
        for pid, profile in profiles.items():
            if profile.auth_type == AuthType.OAUTH and profile.oauth:
                tokens[pid] = profile.oauth.to_dict()

        if tokens:
            try:
                with open(self.tokens_file, "w") as f:
                    yaml.dump(tokens, f, default_flow_style=False)
            except Exception as e:
                logger.error(f"Failed to save OAuth tokens: {e}")

    def load_tokens(self, profiles: Dict[str, AuthProfile]):
        """Load persisted OAuth tokens from disk."""
        if not os.path.exists(self.tokens_file):
            return

        try:
            with open(self.tokens_file, "r") as f:
                tokens = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Failed to load OAuth tokens: {e}")
            return

        for pid, token_data in tokens.items():
            if pid in profiles and profiles[pid].auth_type == AuthType.OAUTH:
                profile = profiles[pid]
                if profile.oauth:
                    profile.oauth.access_token = token_data.get("access_token", "")
                    profile.oauth.refresh_token = token_data.get("refresh_token", "")
                    profile.oauth.expires_at = token_data.get("expires_at", 0.0)


# =============================================================================
# AUTH MANAGER
# =============================================================================

class AuthManager:
    """
    Centralized credential manager for ARIA.

    Usage:
        auth = AuthManager.from_config(config_dict)
        key = auth.get_credential("openai")  # returns best available key
        auth.report_failure("openai", ErrorType.RATE_LIMIT)  # rotates to next
        auth.report_success("openai")  # resets counters
    """

    # Default env var mapping (backward compatible with LLMProvider.from_env)
    ENV_VARS = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "google": "GOOGLE_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
    }

    def __init__(self):
        self.profiles: Dict[str, AuthProfile] = {}
        self._provider_profiles: Dict[str, List[str]] = {}  # provider -> [profile_ids]
        self._provider_index: Dict[str, int] = {}  # provider -> current index
        self._lock = threading.RLock()
        self.oauth_flow = OAuthFlow()
        self.cooldowns = dict(DEFAULT_COOLDOWNS)
        self.rotation_enabled = True
        self._active_provider: Optional[str] = None
        self._active_file: Optional[str] = None

    # -------------------------------------------------------------------------
    # Construction
    # -------------------------------------------------------------------------

    @classmethod
    def from_config(cls, config: dict) -> "AuthManager":
        """
        Build AuthManager from config.yaml auth section.
        Falls back to env vars if no auth config exists.
        """
        manager = cls()
        auth_config = config.get("auth", {})

        if auth_config and "profiles" in auth_config:
            # Load from config
            manager._load_profiles_from_config(auth_config)
        else:
            # Backward compatible: load from env vars
            manager._load_from_env()

        # Load rotation settings
        rotation = auth_config.get("rotation", {})
        manager.rotation_enabled = rotation.get("enabled", True)
        if "cooldown_seconds" in rotation:
            default_cd = rotation["cooldown_seconds"]
            manager.cooldowns[ErrorType.RATE_LIMIT] = default_cd
            manager.cooldowns[ErrorType.UNKNOWN] = default_cd

        # Load persisted OAuth tokens
        data_dir = auth_config.get("data_dir", "data/auth")
        manager.oauth_flow = OAuthFlow(data_dir)
        manager.oauth_flow.load_tokens(manager.profiles)

        # Active provider persistence
        manager._active_file = os.path.join(data_dir, "active_provider.json")
        manager._load_active_provider()

        # Auto-refresh expired OAuth tokens
        manager._refresh_expired_tokens()

        return manager

    @classmethod
    def from_env(cls) -> "AuthManager":
        """Create AuthManager purely from environment variables."""
        manager = cls()
        manager._load_from_env()
        return manager

    def _load_from_env(self):
        """Load credentials from environment variables (backward compatible)."""
        for provider, env_var in self.ENV_VARS.items():
            key = os.environ.get(env_var, "")
            if key:
                profile_id = f"{provider}_env"
                self.profiles[profile_id] = AuthProfile(
                    profile_id=profile_id,
                    provider=provider,
                    auth_type=AuthType.API_KEY,
                    api_key=key,
                )
                self._register_provider_profile(provider, profile_id)

    def _load_profiles_from_config(self, auth_config: dict):
        """Load credential profiles from config dict."""
        profiles = auth_config.get("profiles", {})

        for profile_id, pconf in profiles.items():
            provider = pconf.get("provider", "")
            auth_type_str = pconf.get("type", "api_key")

            try:
                auth_type = AuthType(auth_type_str)
            except ValueError:
                logger.warning(f"Unknown auth type '{auth_type_str}' for profile {profile_id}")
                continue

            profile = AuthProfile(
                profile_id=profile_id,
                provider=provider,
                auth_type=auth_type,
            )

            if auth_type == AuthType.API_KEY:
                key = pconf.get("key", "")
                # Resolve env var references like ${OPENAI_API_KEY}
                profile.api_key = self._resolve_value(key)

            elif auth_type == AuthType.OAUTH:
                client_secret = self._resolve_value(pconf.get("client_secret", ""))
                profile.oauth = OAuthCredential(
                    client_id=self._resolve_value(pconf.get("client_id", "")),
                    client_secret=client_secret,
                    token_url=pconf.get("token_url", ""),
                    scope=pconf.get("scope", ""),
                    authorize_url=pconf.get("authorize_url", ""),
                )

            elif auth_type == AuthType.TOKEN:
                profile.token = self._resolve_value(pconf.get("token", ""))

            self.profiles[profile_id] = profile
            self._register_provider_profile(provider, profile_id)

    def _register_provider_profile(self, provider: str, profile_id: str):
        """Register a profile under its provider for rotation."""
        if provider not in self._provider_profiles:
            self._provider_profiles[provider] = []
            self._provider_index[provider] = 0
        self._provider_profiles[provider].append(profile_id)

    @staticmethod
    def _resolve_value(value: str) -> str:
        """Resolve ${ENV_VAR} references in config values."""
        if not value:
            return ""
        if value.startswith("${") and value.endswith("}"):
            env_var = value[2:-1]
            return os.environ.get(env_var, "")
        return value

    # -------------------------------------------------------------------------
    # Core API
    # -------------------------------------------------------------------------

    def get_credential(self, provider: str) -> Optional[str]:
        """
        Get the best available key/token for a provider.
        Returns the raw key string, or None if no credential available.
        Automatically refreshes expired OAuth tokens.
        """
        with self._lock:
            profile = self._get_best_profile(provider)
            if not profile:
                return None

            # Auto-refresh OAuth if needed
            if profile.needs_refresh():
                if self.oauth_flow.refresh(profile.oauth):
                    self.oauth_flow.save_tokens(self.profiles)
                else:
                    # Refresh failed, try next profile
                    self._apply_cooldown(profile, ErrorType.AUTH)
                    return self.get_credential(provider)

            profile.last_used = time.time()
            return profile.get_key_value()

    def get_profile(self, provider: str) -> Optional[AuthProfile]:
        """Get the best available profile for a provider."""
        with self._lock:
            return self._get_best_profile(provider)

    def report_failure(self, provider: str, error_type: ErrorType = ErrorType.UNKNOWN):
        """Report a failure for the current profile, triggers rotation."""
        with self._lock:
            profile = self._get_current_profile(provider)
            if not profile:
                return

            profile.failure_count += 1
            profile.total_failures += 1
            self._apply_cooldown(profile, error_type)

            if self.rotation_enabled:
                self._rotate(provider)

            logger.info(
                f"Auth failure for {profile.profile_id} ({error_type.value}), "
                f"cooldown {self.cooldowns[error_type]}s"
            )

    def report_success(self, provider: str):
        """Report a successful API call, resets failure counters."""
        with self._lock:
            profile = self._get_current_profile(provider)
            if profile:
                profile.failure_count = 0
                profile.total_successes += 1

    def has_credential(self, provider: str) -> bool:
        """Check if any credential is available for a provider."""
        with self._lock:
            return self._get_best_profile(provider) is not None

    # -------------------------------------------------------------------------
    # OAuth operations
    # -------------------------------------------------------------------------

    def login_oauth(self, provider: str, method: str = "auto") -> bool:
        """
        Start OAuth login flow for a provider.

        Args:
            provider: Provider name (e.g. "google", "github", "openai")
            method: "auto" (tries browser, falls back to device code),
                    "browser" (authorization code flow only),
                    "device" (device code flow only)
        """
        with self._lock:
            profiles = self._get_oauth_profiles(provider)
            if not profiles:
                # Try to create profile from preset
                if provider in OAUTH_PRESETS:
                    logger.info(f"Creating OAuth profile from preset for {provider}")
                    profile = self._create_from_preset(provider)
                    if not profile:
                        logger.error(f"Failed to create OAuth profile for {provider} (need client_id)")
                        return False
                    profiles = [profile]
                else:
                    logger.error(f"No OAuth profile configured for {provider}")
                    return False

            profile = profiles[0]
            preset_name = provider if provider in OAUTH_PRESETS else None

            # Device code flow
            if method == "device" or (
                method == "auto"
                and preset_name
                and OAUTH_PRESETS.get(preset_name, {}).get("supports_device_code", False)
                and not os.environ.get("DISPLAY")  # No display = headless
            ):
                device_url = OAUTH_PRESETS.get(preset_name, {}).get("device_code_url") if preset_name else None
                if device_url:
                    success = self.oauth_flow.authorize_device(
                        profile.oauth,
                        device_code_url=device_url,
                        provider_preset=preset_name,
                    )
                    if success:
                        self.oauth_flow.save_tokens(self.profiles)
                    return success

            # Authorization code flow (with PKCE + state)
            success = self.oauth_flow.authorize(
                profile.oauth,
                use_pkce=OAUTH_PRESETS.get(preset_name, {}).get("supports_pkce", True) if preset_name else True,
                provider_preset=preset_name,
            )
            if success:
                self.oauth_flow.save_tokens(self.profiles)
            return success

    def start_oauth_for_web(self, provider: str) -> str | None:
        """
        Non-blocking OAuth start for the web UI.

        Returns the authorization URL. A background thread listens for
        the callback.  Poll ``oauth_poll_status(provider)`` to check
        when the flow completes.
        """
        with self._lock:
            profiles = self._get_oauth_profiles(provider)
            if not profiles:
                if provider in OAUTH_PRESETS:
                    profile = self._create_from_preset(provider)
                    if not profile:
                        logger.error(f"Failed to create OAuth profile for {provider} (need client_id)")
                        return None
                    profiles = [profile]
                else:
                    logger.error(f"No OAuth profile configured for {provider}")
                    return None

            profile = profiles[0]
            preset_name = provider if provider in OAUTH_PRESETS else None

            auth_url = self.oauth_flow.start_authorize(
                profile.oauth,
                provider=provider,
                use_pkce=OAUTH_PRESETS.get(preset_name, {}).get("supports_pkce", True) if preset_name else True,
                provider_preset=preset_name,
            )
            return auth_url

    def oauth_poll_status(self, provider: str) -> dict:
        """Check the status of a pending web-initiated OAuth flow."""
        result = self.oauth_flow.pending_status(provider)
        if result.get("status") == "success":
            self.oauth_flow.save_tokens(self.profiles)
        return result

    def login_with_key(self, provider: str, api_key: str) -> bool:
        """Quick login with an API key (no OAuth)."""
        with self._lock:
            profile_id = f"{provider}_manual"
            profile = AuthProfile(
                profile_id=profile_id,
                provider=provider,
                auth_type=AuthType.API_KEY,
                api_key=api_key,
            )
            self.profiles[profile_id] = profile
            self._register_provider_profile(provider, profile_id)
            logger.info(f"API key registered for {provider}")
            return True

    def refresh_oauth(self, provider: str) -> bool:
        """Force refresh OAuth token for a provider."""
        with self._lock:
            profiles = self._get_oauth_profiles(provider)
            if not profiles:
                return False

            profile = profiles[0]
            success = self.oauth_flow.refresh(profile.oauth)
            if success:
                self.oauth_flow.save_tokens(self.profiles)
            return success

    def revoke_oauth(self, provider: str) -> bool:
        """Revoke OAuth token for a provider."""
        with self._lock:
            profiles = self._get_oauth_profiles(provider)
            if not profiles:
                return False

            profile = profiles[0]
            revoke_url = ""
            preset_name = provider if provider in OAUTH_PRESETS else None
            if preset_name:
                revoke_url = OAUTH_PRESETS[preset_name].get("revoke_url", "")
            success = self.oauth_flow.revoke(profile.oauth, revoke_url)
            self.oauth_flow.save_tokens(self.profiles)
            return success

    def _create_from_preset(self, provider: str) -> Optional[AuthProfile]:
        """Create an OAuth profile from a provider preset."""
        preset = OAUTH_PRESETS.get(provider, {})
        if not preset:
            return None

        # Look for client_id in env or config
        env_var = f"{provider.upper()}_CLIENT_ID"
        client_id = os.environ.get(env_var, "")
        secret_var = f"{provider.upper()}_CLIENT_SECRET"
        client_secret = os.environ.get(secret_var, "")

        if not client_id:
            logger.warning(f"Set {env_var} environment variable for {provider} OAuth")
            return None

        profile_id = f"{provider}_oauth"
        profile = AuthProfile(
            profile_id=profile_id,
            provider=provider,
            auth_type=AuthType.OAUTH,
            oauth=OAuthCredential(
                client_id=client_id,
                client_secret=client_secret,
                authorize_url=preset["authorize_url"],
                token_url=preset["token_url"],
                scope=preset.get("scope", ""),
            ),
        )
        self.profiles[profile_id] = profile
        self._register_provider_profile(provider, profile_id)
        return profile

    # -------------------------------------------------------------------------
    # Status & Info
    # -------------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return status of all credentials."""
        with self._lock:
            result = {}
            for pid, profile in self.profiles.items():
                now = time.time()
                status = {
                    "provider": profile.provider,
                    "type": profile.auth_type.value,
                    "available": profile.is_available(),
                    "failures": profile.total_failures,
                    "successes": profile.total_successes,
                }
                if profile.cooldown_until > now:
                    status["cooldown_remaining"] = int(profile.cooldown_until - now)
                if profile.auth_type == AuthType.OAUTH and profile.oauth:
                    if profile.oauth.expires_at > 0:
                        remaining = profile.oauth.expires_at - now
                        status["token_expires_in"] = max(0, int(remaining))
                        status["token_expired"] = profile.oauth.is_expired()
                result[pid] = status
            return result

    def get_available_providers(self) -> List[str]:
        """Return list of providers that have at least one available credential."""
        with self._lock:
            available = []
            for provider in self._provider_profiles:
                if self._get_best_profile(provider):
                    available.append(provider)
            return available

    # -------------------------------------------------------------------------
    # Active provider (which LLM is currently selected for use)
    # -------------------------------------------------------------------------

    def set_active_provider(self, provider: str) -> bool:
        """Mark a provider as the active one. Persists to disk."""
        with self._lock:
            if provider not in self._provider_profiles and provider != "ollama":
                logger.warning(f"set_active_provider: {provider} has no profile")
                return False
            self._active_provider = provider
            self._save_active_provider()
            logger.info(f"Active provider set to {provider}")
            return True

    def get_active_provider(self) -> Optional[str]:
        """Return the currently active provider, or None if not set."""
        with self._lock:
            return self._active_provider

    def _load_active_provider(self):
        if not self._active_file or not os.path.exists(self._active_file):
            return
        try:
            with open(self._active_file, "r") as f:
                data = json.load(f)
                self._active_provider = data.get("provider")
        except Exception as e:
            logger.error(f"Failed to load active provider: {e}")

    def _save_active_provider(self):
        if not self._active_file:
            return
        try:
            os.makedirs(os.path.dirname(self._active_file), exist_ok=True)
            with open(self._active_file, "w") as f:
                json.dump({"provider": self._active_provider}, f)
        except Exception as e:
            logger.error(f"Failed to save active provider: {e}")

    # -------------------------------------------------------------------------
    # Provider state & mutation (used by REST API)
    # -------------------------------------------------------------------------

    def get_provider_state(self, provider: str) -> str:
        """
        Return one of: 'active', 'configured', 'empty', 'local'.
          - 'local'      → ollama (no auth needed)
          - 'active'     → has credential AND is the selected active provider
          - 'configured' → has credential but is not active
          - 'empty'      → no credential
        """
        with self._lock:
            if provider == "ollama":
                return "local"
            if not self._get_best_profile(provider):
                return "empty"
            if self._active_provider == provider:
                return "active"
            return "configured"

    def delete_credential(self, provider: str) -> bool:
        """Remove all profiles for a provider. Returns True if anything was removed."""
        with self._lock:
            profile_ids = list(self._provider_profiles.get(provider, []))
            if not profile_ids:
                return False
            for pid in profile_ids:
                self.profiles.pop(pid, None)
            self._provider_profiles.pop(provider, None)
            self._provider_index.pop(provider, None)
            if self._active_provider == provider:
                self._active_provider = None
                self._save_active_provider()
            logger.info(f"Removed credentials for {provider}")
            return True

    def get_key_preview(self, provider: str) -> Optional[str]:
        """Return a masked preview of the key for a provider, e.g. 'sk-•••a3f2'."""
        with self._lock:
            profile = self._get_best_profile(provider)
            if not profile:
                return None
            raw = profile.get_key_value() if hasattr(profile, "get_key_value") else None
            if not raw:
                return None
            if len(raw) <= 8:
                return "•••" + raw[-2:]
            return f"{raw[:5]}•••{raw[-4:]}"

    # -------------------------------------------------------------------------
    # Internal
    # -------------------------------------------------------------------------

    def _get_best_profile(self, provider: str) -> Optional[AuthProfile]:
        """Get the best available profile for a provider."""
        profile_ids = self._provider_profiles.get(provider, [])
        if not profile_ids:
            return None

        # Start from current index
        idx = self._provider_index.get(provider, 0)
        for i in range(len(profile_ids)):
            actual_idx = (idx + i) % len(profile_ids)
            profile = self.profiles[profile_ids[actual_idx]]
            if profile.is_available():
                return profile

        return None

    def _get_current_profile(self, provider: str) -> Optional[AuthProfile]:
        """Get the currently selected profile for a provider."""
        profile_ids = self._provider_profiles.get(provider, [])
        if not profile_ids:
            return None
        idx = self._provider_index.get(provider, 0)
        return self.profiles[profile_ids[idx % len(profile_ids)]]

    def _get_oauth_profiles(self, provider: str) -> List[AuthProfile]:
        """Get all OAuth profiles for a provider."""
        profile_ids = self._provider_profiles.get(provider, [])
        return [
            self.profiles[pid] for pid in profile_ids
            if self.profiles[pid].auth_type == AuthType.OAUTH
        ]

    def _rotate(self, provider: str):
        """Rotate to the next profile for a provider."""
        profile_ids = self._provider_profiles.get(provider, [])
        if len(profile_ids) <= 1:
            return
        idx = self._provider_index.get(provider, 0)
        self._provider_index[provider] = (idx + 1) % len(profile_ids)
        next_pid = profile_ids[self._provider_index[provider]]
        logger.info(f"Rotated {provider} to profile: {next_pid}")

    def _apply_cooldown(self, profile: AuthProfile, error_type: ErrorType):
        """Apply cooldown to a profile based on error type."""
        cooldown = self.cooldowns.get(error_type, 60)
        profile.cooldown_until = time.time() + cooldown

    def _refresh_expired_tokens(self):
        """Refresh any expired OAuth tokens on startup."""
        for pid, profile in self.profiles.items():
            if profile.needs_refresh():
                logger.info(f"Refreshing expired OAuth token for {pid}")
                if self.oauth_flow.refresh(profile.oauth):
                    self.oauth_flow.save_tokens(self.profiles)
                else:
                    logger.warning(f"Failed to refresh token for {pid}")


# =============================================================================
# ERROR CLASSIFICATION HELPER
# =============================================================================

def classify_error(error: Exception) -> ErrorType:
    """Classify an API error into an ErrorType for cooldown purposes."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    # Rate limit indicators
    if any(s in error_str for s in ["rate_limit", "rate limit", "429", "too many requests"]):
        return ErrorType.RATE_LIMIT

    # Billing indicators
    if any(s in error_str for s in ["billing", "quota", "insufficient_quota", "payment"]):
        return ErrorType.BILLING

    # Auth indicators
    if any(s in error_str for s in ["auth", "401", "403", "invalid_api_key", "unauthorized"]):
        return ErrorType.AUTH

    # Network indicators
    if any(s in error_str for s in ["connection", "timeout", "dns", "network"]):
        return ErrorType.NETWORK

    return ErrorType.UNKNOWN
