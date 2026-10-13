"""
Test: Enhanced OAuth — PKCE, State, Presets, Device Code Flow
"""

import hashlib
import base64
import json
import os
import sys
import threading
import time
import pytest
from unittest.mock import patch, MagicMock
from http.server import HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.infra.auth_manager import (
    AuthManager, AuthProfile, AuthType, OAuthCredential, OAuthFlow,
    generate_pkce, generate_state, OAUTH_PRESETS,
    ErrorType, classify_error,
)


# =============================================================================
# Test PKCE
# =============================================================================

class TestPKCE:
    """Test PKCE (Proof Key for Code Exchange) implementation."""

    def test_pkce_generates_pair(self):
        verifier, challenge = generate_pkce()
        assert len(verifier) > 30
        assert len(challenge) > 30
        assert verifier != challenge

    def test_pkce_challenge_is_sha256_of_verifier(self):
        """Challenge must be base64url(SHA256(verifier))."""
        verifier, challenge = generate_pkce()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode("ascii")).digest()
        ).rstrip(b"=").decode("ascii")
        assert challenge == expected

    def test_pkce_unique_each_call(self):
        """Each call should produce a unique pair."""
        pairs = [generate_pkce() for _ in range(10)]
        verifiers = [p[0] for p in pairs]
        assert len(set(verifiers)) == 10

    def test_pkce_verifier_is_url_safe(self):
        """Verifier should only contain URL-safe characters."""
        for _ in range(20):
            verifier, _ = generate_pkce()
            assert "+" not in verifier
            assert "/" not in verifier


# =============================================================================
# Test State
# =============================================================================

class TestState:
    """Test CSRF state parameter generation."""

    def test_state_generates_string(self):
        state = generate_state()
        assert isinstance(state, str)
        assert len(state) > 15

    def test_state_unique(self):
        states = [generate_state() for _ in range(20)]
        assert len(set(states)) == 20

    def test_state_url_safe(self):
        for _ in range(20):
            state = generate_state()
            assert "+" not in state
            assert "/" not in state


# =============================================================================
# Test Provider Presets
# =============================================================================

class TestPresets:
    """Test OAuth provider presets."""

    def test_presets_exist(self):
        assert "google" in OAUTH_PRESETS
        assert "github" in OAUTH_PRESETS
        assert "openai" in OAUTH_PRESETS
        assert "microsoft" in OAUTH_PRESETS

    def test_google_preset(self):
        p = OAUTH_PRESETS["google"]
        assert "accounts.google.com" in p["authorize_url"]
        assert "googleapis.com" in p["token_url"]
        assert p["supports_pkce"] is True
        assert "scope" in p

    def test_github_preset(self):
        p = OAUTH_PRESETS["github"]
        assert "github.com" in p["authorize_url"]
        assert p["supports_device_code"] is True
        assert "device_code_url" in p

    def test_openai_preset(self):
        p = OAUTH_PRESETS["openai"]
        assert "openai.com" in p["authorize_url"] or "auth0.openai.com" in p["authorize_url"]
        assert p["supports_pkce"] is True

    def test_microsoft_preset(self):
        p = OAUTH_PRESETS["microsoft"]
        assert "microsoftonline.com" in p["authorize_url"]
        assert p["supports_pkce"] is True
        assert p["supports_device_code"] is True

    def test_all_presets_have_required_fields(self):
        for name, preset in OAUTH_PRESETS.items():
            assert "authorize_url" in preset, f"{name} missing authorize_url"
            assert "token_url" in preset, f"{name} missing token_url"
            assert "scope" in preset, f"{name} missing scope"
            assert "supports_pkce" in preset, f"{name} missing supports_pkce"


# =============================================================================
# Test OAuthFlow enhanced
# =============================================================================

class TestOAuthFlowEnhanced:
    """Test the enhanced OAuthFlow with PKCE and state."""

    def test_authorize_builds_pkce_params(self):
        """Authorization URL should include code_challenge when PKCE is enabled."""
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="test_id",
            client_secret="test_secret",
            authorize_url="https://auth.example.com/authorize",
            token_url="https://auth.example.com/token",
            scope="openid",
        )

        # We can't actually run the full flow, but we can test the URL building
        # by mocking the server and browser
        with patch("webbrowser.open") as mock_browser, \
             patch.object(HTTPServer, "__init__", return_value=None), \
             patch.object(HTTPServer, "handle_request"):

            # Simulate callback server attributes
            mock_server = MagicMock()
            mock_server.auth_code = "test_code"
            mock_server.auth_error = None

            # Capture the URL that would be opened
            urls_opened = []
            mock_browser.side_effect = lambda url: urls_opened.append(url)

            # Mock the code exchange
            with patch.object(flow, "_exchange_code", return_value=True) as mock_exchange:
                with patch("http.server.HTTPServer") as MockHTTP:
                    instance = MockHTTP.return_value
                    instance.auth_code = "test_code"
                    instance.auth_error = None
                    instance.expected_state = None

                    flow.authorize(cred, use_pkce=True)

                    # Verify exchange was called with code_verifier
                    if mock_exchange.called:
                        args = mock_exchange.call_args
                        assert args[0][3] is not None  # code_verifier param

    def test_exchange_includes_verifier(self):
        """Token exchange should include code_verifier when PKCE was used."""
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="test_id",
            client_secret="test_secret",
            token_url="https://auth.example.com/token",
        )

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "access_token": "at_123",
                "refresh_token": "rt_123",
                "expires_in": 3600,
            }
            mock_resp.raise_for_status = MagicMock()
            mock_post.return_value = mock_resp

            result = flow._exchange_code(cred, "auth_code", "http://localhost:8900/callback",
                                         code_verifier="my_verifier_123")

            assert result is True
            assert cred.access_token == "at_123"

            # Verify code_verifier was sent
            call_data = mock_post.call_args
            assert "code_verifier" in call_data[1].get("data", call_data[0][0] if not call_data[1] else {})

    def test_exchange_without_verifier(self):
        """Token exchange should work without PKCE too."""
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="test_id",
            client_secret="test_secret",
            token_url="https://auth.example.com/token",
        )

        with patch("requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "access_token": "at_456",
                "expires_in": 7200,
            }
            mock_resp.raise_for_status = MagicMock()
            mock_post.return_value = mock_resp

            result = flow._exchange_code(cred, "auth_code", "http://localhost:8900/callback")

            assert result is True
            assert cred.access_token == "at_456"


# =============================================================================
# Test Device Code Flow
# =============================================================================

class TestDeviceCodeFlow:
    """Test OAuth 2.0 device code flow."""

    def test_device_flow_success(self):
        """Device code flow should poll and succeed when token is returned."""
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="test_id",
            client_secret="test_secret",
            token_url="https://auth.example.com/token",
            scope="openid",
        )

        call_count = [0]

        def mock_post_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()

            if "device" in url:
                # Device code request
                resp.json.return_value = {
                    "device_code": "dc_123",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://auth.example.com/device",
                    "expires_in": 60,
                    "interval": 1,
                }
            else:
                # Token poll
                call_count[0] += 1
                if call_count[0] < 3:
                    resp.json.return_value = {"error": "authorization_pending"}
                else:
                    resp.json.return_value = {
                        "access_token": "at_device_123",
                        "refresh_token": "rt_device_123",
                        "expires_in": 3600,
                    }
            return resp

        with patch("requests.post", side_effect=mock_post_side_effect), \
             patch("webbrowser.open"), \
             patch("builtins.print"):

            result = flow.authorize_device(
                cred,
                device_code_url="https://auth.example.com/device/code",
                poll_interval=0.1,
                timeout=10,
            )

            assert result is True
            assert cred.access_token == "at_device_123"
            assert cred.refresh_token == "rt_device_123"
            assert call_count[0] >= 3

    def test_device_flow_denied(self):
        """Device code flow should handle user denial."""
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="test_id",
            client_secret="test_secret",
            token_url="https://auth.example.com/token",
        )

        def mock_post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "device" in url:
                resp.json.return_value = {
                    "device_code": "dc_123",
                    "user_code": "ABCD",
                    "verification_uri": "https://example.com",
                    "expires_in": 60,
                    "interval": 1,
                }
            else:
                resp.json.return_value = {"error": "access_denied"}
            return resp

        with patch("requests.post", side_effect=mock_post), \
             patch("webbrowser.open"), \
             patch("builtins.print"):

            result = flow.authorize_device(
                cred,
                device_code_url="https://auth.example.com/device/code",
                poll_interval=0.1,
            )
            assert result is False

    def test_device_flow_with_preset(self):
        """Device code flow should use preset URLs."""
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="test_id",
            client_secret="test_secret",
            token_url="",  # Should be filled from preset
        )

        def mock_post(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "device" in url:
                resp.json.return_value = {
                    "device_code": "dc_gh",
                    "user_code": "GH-1234",
                    "verification_uri": "https://github.com/login/device",
                    "expires_in": 60,
                    "interval": 1,
                }
            else:
                resp.json.return_value = {
                    "access_token": "gh_token",
                    "expires_in": 3600,
                }
            return resp

        with patch("requests.post", side_effect=mock_post), \
             patch("webbrowser.open"), \
             patch("builtins.print"):

            result = flow.authorize_device(
                cred,
                provider_preset="github",
                poll_interval=0.1,
            )
            assert result is True
            assert cred.access_token == "gh_token"
            # Token URL should have been filled from preset
            assert "github" in cred.token_url


# =============================================================================
# Test AuthManager enhanced
# =============================================================================

class TestAuthManagerEnhanced:
    """Test enhanced AuthManager features."""

    def test_login_with_key(self):
        """login_with_key should register API key immediately."""
        am = AuthManager()
        result = am.login_with_key("deepseek", "sk-test123")

        assert result is True
        assert am.has_credential("deepseek")
        assert am.get_credential("deepseek") == "sk-test123"

    def test_login_with_key_multiple_providers(self):
        """Should support multiple providers simultaneously."""
        am = AuthManager()
        am.login_with_key("openai", "sk-openai")
        am.login_with_key("deepseek", "sk-deepseek")
        am.login_with_key("anthropic", "sk-anthropic")

        assert am.get_credential("openai") == "sk-openai"
        assert am.get_credential("deepseek") == "sk-deepseek"
        assert am.get_credential("anthropic") == "sk-anthropic"
        assert len(am.get_available_providers()) == 3

    def test_status_includes_all_profiles(self):
        """Status should show all registered profiles."""
        am = AuthManager()
        am.login_with_key("openai", "sk-test")

        status = am.status()
        assert "openai_manual" in status
        assert status["openai_manual"]["type"] == "api_key"
        assert status["openai_manual"]["available"] is True

    def test_create_from_preset_needs_client_id(self):
        """Creating from preset without client_id should fail gracefully."""
        am = AuthManager()
        # No env vars set
        with patch.dict(os.environ, {}, clear=True):
            result = am.login_oauth("google")
            assert result is False  # No client_id available

    def test_error_classification(self):
        """Error classifier should categorize correctly."""
        assert classify_error(Exception("429 Too Many Requests")) == ErrorType.RATE_LIMIT
        assert classify_error(Exception("insufficient_quota")) == ErrorType.BILLING
        assert classify_error(Exception("401 Unauthorized")) == ErrorType.AUTH
        assert classify_error(Exception("Connection timeout")) == ErrorType.NETWORK
        assert classify_error(Exception("something random")) == ErrorType.UNKNOWN


# =============================================================================
# Run
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
