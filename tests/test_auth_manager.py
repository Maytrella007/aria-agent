"""
Tests for ARIA Auth Manager
============================

Tests for credential management, rotation, OAuth flow, and integration.
"""

import pytest
import os
import time
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.auth_manager import (
    AuthManager,
    AuthProfile,
    AuthType,
    OAuthCredential,
    OAuthFlow,
    ErrorType,
    classify_error,
)


# =============================================================================
# AUTH PROFILE TESTS
# =============================================================================

class TestAuthProfile:
    def test_api_key_available(self):
        profile = AuthProfile(
            profile_id="test",
            provider="openai",
            auth_type=AuthType.API_KEY,
            api_key="sk-test123",
        )
        assert profile.is_available()
        assert profile.get_key_value() == "sk-test123"
        assert profile.get_header() == {"Authorization": "Bearer sk-test123"}

    def test_empty_api_key_not_available(self):
        profile = AuthProfile(
            profile_id="test",
            provider="openai",
            auth_type=AuthType.API_KEY,
            api_key="",
        )
        assert not profile.is_available()

    def test_cooldown_blocks_availability(self):
        profile = AuthProfile(
            profile_id="test",
            provider="openai",
            auth_type=AuthType.API_KEY,
            api_key="sk-test123",
            cooldown_until=time.time() + 3600,  # 1 hour from now
        )
        assert not profile.is_available()

    def test_expired_cooldown_allows_availability(self):
        profile = AuthProfile(
            profile_id="test",
            provider="openai",
            auth_type=AuthType.API_KEY,
            api_key="sk-test123",
            cooldown_until=time.time() - 1,  # expired
        )
        assert profile.is_available()

    def test_oauth_needs_refresh(self):
        oauth = OAuthCredential(
            client_id="cid",
            client_secret="csec",
            token_url="https://example.com/token",
            access_token="old-token",
            refresh_token="refresh-tok",
            expires_at=time.time() - 100,  # expired
        )
        profile = AuthProfile(
            profile_id="test",
            provider="openai",
            auth_type=AuthType.OAUTH,
            oauth=oauth,
        )
        assert profile.needs_refresh()

    def test_oauth_no_refresh_when_valid(self):
        oauth = OAuthCredential(
            client_id="cid",
            client_secret="csec",
            token_url="https://example.com/token",
            access_token="valid-token",
            refresh_token="refresh-tok",
            expires_at=time.time() + 3600,  # 1 hour
        )
        profile = AuthProfile(
            profile_id="test",
            provider="openai",
            auth_type=AuthType.OAUTH,
            oauth=oauth,
        )
        assert not profile.needs_refresh()

    def test_token_type(self):
        profile = AuthProfile(
            profile_id="test",
            provider="anthropic",
            auth_type=AuthType.TOKEN,
            token="ant-tok-123",
        )
        assert profile.is_available()
        assert profile.get_key_value() == "ant-tok-123"


# =============================================================================
# OAUTH CREDENTIAL TESTS
# =============================================================================

class TestOAuthCredential:
    def test_expired(self):
        cred = OAuthCredential(
            client_id="c", client_secret="s", token_url="t",
            access_token="tok", expires_at=time.time() - 100,
        )
        assert cred.is_expired()

    def test_not_expired(self):
        cred = OAuthCredential(
            client_id="c", client_secret="s", token_url="t",
            access_token="tok", expires_at=time.time() + 3600,
        )
        assert not cred.is_expired()

    def test_no_token_is_expired(self):
        cred = OAuthCredential(
            client_id="c", client_secret="s", token_url="t",
        )
        assert cred.is_expired()

    def test_to_dict_roundtrip(self):
        cred = OAuthCredential(
            client_id="cid", client_secret="csec", token_url="https://t.co/token",
            scope="read", access_token="at", refresh_token="rt", expires_at=12345.0,
        )
        d = cred.to_dict()
        restored = OAuthCredential.from_dict(d, client_secret="csec")
        assert restored.client_id == "cid"
        assert restored.access_token == "at"
        assert restored.refresh_token == "rt"
        assert restored.expires_at == 12345.0


# =============================================================================
# AUTH MANAGER TESTS
# =============================================================================

class TestAuthManager:
    def test_from_env(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            manager = AuthManager.from_env()
            key = manager.get_credential("openai")
            assert key == "sk-test"

    def test_from_env_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            manager = AuthManager.from_env()
            key = manager.get_credential("openai")
            assert key is None

    def test_multiple_providers(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-openai",
            "ANTHROPIC_API_KEY": "sk-anthropic",
        }):
            manager = AuthManager.from_env()
            assert manager.get_credential("openai") == "sk-openai"
            assert manager.get_credential("anthropic") == "sk-anthropic"

    def test_rotation_on_failure(self):
        config = {
            "auth": {
                "profiles": {
                    "main": {
                        "provider": "openai",
                        "type": "api_key",
                        "key": "sk-main",
                    },
                    "backup": {
                        "provider": "openai",
                        "type": "api_key",
                        "key": "sk-backup",
                    },
                },
                "rotation": {"enabled": True, "cooldown_seconds": 30},
            }
        }
        manager = AuthManager.from_config(config)

        # First call gets main
        key1 = manager.get_credential("openai")
        assert key1 == "sk-main"

        # Report failure → rotates to backup
        manager.report_failure("openai", ErrorType.RATE_LIMIT)
        key2 = manager.get_credential("openai")
        assert key2 == "sk-backup"

    def test_cooldown_expiry(self):
        config = {
            "auth": {
                "profiles": {
                    "main": {
                        "provider": "openai",
                        "type": "api_key",
                        "key": "sk-main",
                    },
                },
                "rotation": {"enabled": True, "cooldown_seconds": 0},
            }
        }
        manager = AuthManager.from_config(config)

        # Fail with 0s cooldown
        manager.report_failure("openai", ErrorType.RATE_LIMIT)
        manager.cooldowns[ErrorType.RATE_LIMIT] = 0
        # Manually expire the cooldown
        profile = manager.profiles["main"]
        profile.cooldown_until = time.time() - 1

        key = manager.get_credential("openai")
        assert key == "sk-main"

    def test_report_success_resets_counters(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            manager = AuthManager.from_env()
            manager.report_failure("openai", ErrorType.UNKNOWN)
            profile = manager.profiles["openai_env"]
            assert profile.total_failures == 1

            manager.report_success("openai")
            assert profile.failure_count == 0
            assert profile.total_successes == 1

    def test_has_credential(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            manager = AuthManager.from_env()
            assert manager.has_credential("openai")
            assert not manager.has_credential("anthropic")

    def test_get_available_providers(self):
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "sk-openai",
            "DEEPSEEK_API_KEY": "sk-ds",
        }):
            manager = AuthManager.from_env()
            available = manager.get_available_providers()
            assert "openai" in available
            assert "deepseek" in available
            assert "anthropic" not in available

    def test_status(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}):
            manager = AuthManager.from_env()
            status = manager.status()
            assert "openai_env" in status
            assert status["openai_env"]["provider"] == "openai"
            assert status["openai_env"]["available"] is True

    def test_env_var_resolution_in_config(self):
        with patch.dict(os.environ, {"MY_KEY": "sk-resolved"}):
            config = {
                "auth": {
                    "profiles": {
                        "test": {
                            "provider": "openai",
                            "type": "api_key",
                            "key": "${MY_KEY}",
                        }
                    }
                }
            }
            manager = AuthManager.from_config(config)
            assert manager.get_credential("openai") == "sk-resolved"

    def test_backward_compatible_no_auth_section(self):
        """Without auth section, should fall back to env vars."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}):
            config = {"api": {"provider": "openai"}}
            manager = AuthManager.from_config(config)
            assert manager.get_credential("openai") == "sk-env"

    def test_oauth_profile_loaded(self):
        config = {
            "auth": {
                "profiles": {
                    "google_oauth": {
                        "provider": "google",
                        "type": "oauth",
                        "client_id": "goog-id",
                        "client_secret": "goog-sec",
                        "token_url": "https://oauth2.googleapis.com/token",
                        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
                        "scope": "generative-language",
                    }
                }
            }
        }
        manager = AuthManager.from_config(config)
        profile = manager.profiles["google_oauth"]
        assert profile.auth_type == AuthType.OAUTH
        assert profile.oauth.client_id == "goog-id"
        assert profile.oauth.token_url == "https://oauth2.googleapis.com/token"


# =============================================================================
# OAUTH FLOW TESTS
# =============================================================================

class TestOAuthFlow:
    def test_refresh_success(self):
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="cid", client_secret="csec",
            token_url="https://example.com/token",
            access_token="old", refresh_token="rt",
            expires_at=time.time() - 100,
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = Mock()

        with patch("requests.post", return_value=mock_response):
            result = flow.refresh(cred)
            assert result is True
            assert cred.access_token == "new-token"
            assert cred.expires_at > time.time()

    def test_refresh_failure(self):
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="cid", client_secret="csec",
            token_url="https://example.com/token",
            refresh_token="bad-rt",
        )

        with patch("requests.post", side_effect=Exception("401 Unauthorized")):
            result = flow.refresh(cred)
            assert result is False

    def test_revoke_clears_tokens(self):
        flow = OAuthFlow(data_dir="/tmp/aria_test_auth")
        cred = OAuthCredential(
            client_id="cid", client_secret="csec",
            token_url="t", access_token="tok", refresh_token="rt",
        )
        # Revoke without URL just clears locally
        result = flow.revoke(cred)
        assert result is True
        assert cred.access_token == ""
        assert cred.refresh_token == ""


# =============================================================================
# ERROR CLASSIFICATION TESTS
# =============================================================================

class TestClassifyError:
    def test_rate_limit(self):
        assert classify_error(Exception("429 Too Many Requests")) == ErrorType.RATE_LIMIT
        assert classify_error(Exception("rate_limit_exceeded")) == ErrorType.RATE_LIMIT

    def test_billing(self):
        assert classify_error(Exception("insufficient_quota")) == ErrorType.BILLING
        assert classify_error(Exception("billing issue")) == ErrorType.BILLING

    def test_auth(self):
        assert classify_error(Exception("401 Unauthorized")) == ErrorType.AUTH
        assert classify_error(Exception("invalid_api_key")) == ErrorType.AUTH

    def test_network(self):
        assert classify_error(Exception("Connection refused")) == ErrorType.NETWORK
        assert classify_error(Exception("timeout")) == ErrorType.NETWORK

    def test_unknown(self):
        assert classify_error(Exception("something weird")) == ErrorType.UNKNOWN


# =============================================================================
# INTEGRATION WITH LLM PROVIDERS
# =============================================================================

class TestAuthManagerLLMIntegration:
    def test_llm_provider_uses_auth_manager(self):
        from core.llm.llm_providers import LLMProvider

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-from-auth"}):
            manager = AuthManager.from_env()
            LLMProvider.set_auth_manager(manager)

            # Verify auth manager is consulted
            key = manager.get_credential("openai")
            assert key == "sk-from-auth"

            # Cleanup
            LLMProvider._auth_manager = None
