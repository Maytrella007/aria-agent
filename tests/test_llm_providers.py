"""
Tests for ARIA LLM Provider System
==================================

Comprehensive tests for the multi-provider LLM interface including:
- LLMProvider factory methods
- Individual provider classes
- LLMManager with fallbacks
- Error handling
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from dataclasses import asdict

# Import the module under test
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.llm.llm_providers import (
    ProviderType,
    LLMResponse,
    LLMConfig,
    BaseLLMProvider,
    AnthropicProvider,
    OpenAIProvider,
    GoogleProvider,
    DeepSeekProvider,
    OllamaProvider,
    OpenRouterProvider,
    LLMProvider,
    LLMManager,
    get_available_providers,
)


# =============================================================================
# HELPERS: Mock module injection for packages that may not be installed
# =============================================================================

def _make_mock_anthropic_module():
    """Create a mock anthropic module with Anthropic class."""
    mock_mod = MagicMock()
    return mock_mod


def _make_mock_openai_module():
    """Create a mock openai module with OpenAI class."""
    mock_mod = MagicMock()
    return mock_mod


def _make_mock_google_module():
    """Create mock google.generativeai module."""
    mock_mod = MagicMock()
    return mock_mod


def _patch_anthropic():
    """Context manager to ensure anthropic module is available for patching."""
    mock_mod = _make_mock_anthropic_module()
    return patch.dict('sys.modules', {'anthropic': mock_mod})


def _patch_openai():
    """Context manager to ensure openai module is available for patching."""
    mock_mod = _make_mock_openai_module()
    return patch.dict('sys.modules', {'openai': mock_mod})


def _patch_google():
    """Context manager to ensure google modules are available for patching."""
    mock_google = MagicMock()
    mock_genai = MagicMock()
    return patch.dict('sys.modules', {
        'google': mock_google,
        'google.generativeai': mock_genai,
    })


def _setup_anthropic_mock(mock_text="Hello from Claude!", input_tokens=10, output_tokens=20):
    """Inject anthropic mock module and return (module, client) for further assertions."""
    mock_mod = MagicMock()
    mock_client = Mock()
    mock_response = Mock()
    mock_response.content = [Mock(text=mock_text)]
    mock_response.usage = Mock(input_tokens=input_tokens, output_tokens=output_tokens)
    mock_client.messages.create.return_value = mock_response
    mock_mod.Anthropic.return_value = mock_client
    return mock_mod, mock_client


def _setup_openai_mock(mock_text="Hello from GPT!", prompt_tokens=10, completion_tokens=20):
    """Inject openai mock module and return (module, client) for further assertions."""
    mock_mod = MagicMock()
    mock_client = Mock()
    mock_response = Mock()
    mock_response.choices = [Mock(message=Mock(content=mock_text, tool_calls=None))]
    mock_response.usage = Mock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    mock_client.chat.completions.create.return_value = mock_response
    mock_mod.OpenAI.return_value = mock_client
    return mock_mod, mock_client


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def sample_messages():
    """Sample chat messages for testing."""
    return [
        {"role": "user", "content": "Hello, how are you?"}
    ]


@pytest.fixture
def sample_config():
    """Sample LLMConfig for testing."""
    return LLMConfig(
        provider=ProviderType.ANTHROPIC,
        api_key="test-api-key",
        model="claude-3-sonnet-20240229",
        max_tokens=1024,
        temperature=0.7
    )


# =============================================================================
# TESTS: LLMResponse dataclass
# =============================================================================

class TestLLMResponse:
    """Tests for LLMResponse dataclass."""

    def test_basic_creation(self):
        """Test basic LLMResponse creation."""
        response = LLMResponse(
            content="Test content",
            model="test-model",
            provider="test-provider"
        )
        assert response.content == "Test content"
        assert response.model == "test-model"
        assert response.provider == "test-provider"
        assert response.usage is None
        assert response.raw_response is None

    def test_full_creation(self):
        """Test LLMResponse with all fields."""
        raw = {"key": "value"}
        response = LLMResponse(
            content="Test content",
            model="test-model",
            provider="test-provider",
            usage={"input_tokens": 10, "output_tokens": 20},
            raw_response=raw
        )
        assert response.usage == {"input_tokens": 10, "output_tokens": 20}
        assert response.raw_response == raw

    def test_dataclass_asdict(self):
        """Test that LLMResponse works with asdict."""
        response = LLMResponse(
            content="Test",
            model="model",
            provider="provider"
        )
        d = asdict(response)
        assert "content" in d
        assert "model" in d
        assert "provider" in d


# =============================================================================
# TESTS: LLMConfig dataclass
# =============================================================================

class TestLLMConfig:
    """Tests for LLMConfig dataclass."""

    def test_basic_creation(self):
        """Test basic LLMConfig creation."""
        config = LLMConfig(
            provider=ProviderType.OPENAI,
            api_key="sk-test-key",
            model="gpt-4"
        )
        assert config.provider == ProviderType.OPENAI
        assert config.api_key == "sk-test-key"
        assert config.model == "gpt-4"
        assert config.max_tokens == 1024  # default
        assert config.temperature == 0.7  # default

    def test_custom_parameters(self):
        """Test LLMConfig with custom parameters."""
        config = LLMConfig(
            provider=ProviderType.ANTHROPIC,
            api_key="test-key",
            model="claude-3-opus",
            max_tokens=4096,
            temperature=0.0,
            base_url="https://custom.api.com"
        )
        assert config.max_tokens == 4096
        assert config.temperature == 0.0
        assert config.base_url == "https://custom.api.com"


# =============================================================================
# TESTS: AnthropicProvider
# =============================================================================

class TestAnthropicProvider:
    """Tests for AnthropicProvider."""

    def test_initialization(self, sample_config):
        """Test AnthropicProvider initializes correctly."""
        mock_mod, mock_client = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = AnthropicProvider(sample_config)
            assert provider.client is not None
            assert provider.name == "anthropic"
            mock_mod.Anthropic.assert_called_once_with(api_key="test-api-key")

    def test_initialization_import_error(self, sample_config):
        """Test AnthropicProvider raises error when anthropic not installed."""
        real_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == 'anthropic':
                raise ImportError("No module named 'anthropic'")
            return real_import(name, *args, **kwargs)

        with patch.dict('sys.modules', {'anthropic': None}):
            with patch('builtins.__import__', side_effect=mock_import):
                with pytest.raises(ImportError, match="Install anthropic"):
                    AnthropicProvider(sample_config)

    def test_chat(self, sample_config, sample_messages):
        """Test AnthropicProvider.chat() returns correct response."""
        mock_mod, mock_client = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = AnthropicProvider(sample_config)
            response = provider.chat(sample_messages, system="You are helpful")

            assert response.content == "Hello from Claude!"
            assert response.provider == "anthropic"
            assert response.usage["input_tokens"] == 10
            assert response.usage["output_tokens"] == 20

            mock_client.messages.create.assert_called_once()

    def test_simple_chat(self, sample_config):
        """Test AnthropicProvider.simple_chat() convenience method."""
        mock_mod, mock_client = _setup_anthropic_mock(mock_text="Simple response")
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = AnthropicProvider(sample_config)
            result = provider.simple_chat("Hello")

            assert result == "Simple response"

    def test_default_model(self):
        """Test AnthropicProvider uses default model."""
        assert AnthropicProvider.DEFAULT_MODEL == "claude-sonnet-4-20250514"


# =============================================================================
# TESTS: OpenAIProvider
# =============================================================================

class TestOpenAIProvider:
    """Tests for OpenAIProvider."""

    @pytest.fixture
    def openai_config(self):
        return LLMConfig(
            provider=ProviderType.OPENAI,
            api_key="sk-test-key",
            model="gpt-4o"
        )

    def test_initialization(self, openai_config):
        """Test OpenAIProvider initializes correctly."""
        mock_mod, mock_client = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OpenAIProvider(openai_config)
            assert provider.client is not None
            assert provider.name == "openai"

    def test_chat_with_system_message(self, openai_config, sample_messages):
        """Test OpenAIProvider includes system message correctly."""
        mock_mod, mock_client = _setup_openai_mock(mock_text="GPT response")
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OpenAIProvider(openai_config)
            response = provider.chat(sample_messages, system="Be helpful")

            assert response.content == "GPT response"
            assert response.provider == "openai"

            # Verify system message was prepended
            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs.get('messages', call_args[1].get('messages', []))
            assert messages[0]["role"] == "system"
            assert messages[0]["content"] == "Be helpful"

    def test_chat_without_system(self, openai_config, sample_messages):
        """Test OpenAIProvider works without system message."""
        mock_mod, mock_client = _setup_openai_mock(mock_text="Response")
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OpenAIProvider(openai_config)
            response = provider.chat(sample_messages)

            call_args = mock_client.chat.completions.create.call_args
            messages = call_args.kwargs.get('messages', call_args[1].get('messages', []))
            assert messages[0]["role"] == "user"

    def test_default_model(self):
        """Test OpenAIProvider uses correct default model."""
        assert OpenAIProvider.DEFAULT_MODEL == "gpt-4o"


# =============================================================================
# TESTS: GoogleProvider
# =============================================================================

class TestGoogleProvider:
    """Tests for GoogleProvider."""

    @pytest.fixture
    def google_config(self):
        return LLMConfig(
            provider=ProviderType.GOOGLE,
            api_key="google-test-key",
            model="gemini-1.5-pro"
        )

    def _setup_google_mock(self):
        """Set up mock google.generativeai module that works with import."""
        mock_genai = MagicMock()
        mock_google = MagicMock()
        # Make google.generativeai resolve to mock_genai
        mock_google.generativeai = mock_genai
        return mock_google, mock_genai

    def test_initialization(self, google_config):
        """Test GoogleProvider initializes correctly."""
        mock_google, mock_genai = self._setup_google_mock()
        with patch.dict('sys.modules', {
            'google': mock_google,
            'google.generativeai': mock_genai,
        }):
            provider = GoogleProvider(google_config)
            mock_genai.configure.assert_called_once_with(api_key="google-test-key")

    def test_chat(self, google_config, sample_messages):
        """Test GoogleProvider.chat() works correctly."""
        mock_google, mock_genai = self._setup_google_mock()
        # Set up model/chat/response chain
        mock_model = Mock()
        mock_chat = Mock()
        mock_response = Mock(text="Gemini response")
        mock_chat.send_message.return_value = mock_response
        mock_model.start_chat.return_value = mock_chat
        mock_genai.GenerativeModel.return_value = mock_model

        with patch.dict('sys.modules', {
            'google': mock_google,
            'google.generativeai': mock_genai,
        }):
            provider = GoogleProvider(google_config)
            response = provider.chat(sample_messages)

            assert response.content == "Gemini response"
            assert response.provider == "google"
            assert response.usage is None  # Gemini doesn't report tokens the same way

    def test_default_model(self):
        """Test GoogleProvider uses correct default model."""
        assert GoogleProvider.DEFAULT_MODEL == "gemini-1.5-pro"


# =============================================================================
# TESTS: DeepSeekProvider
# =============================================================================

class TestDeepSeekProvider:
    """Tests for DeepSeekProvider."""

    @pytest.fixture
    def deepseek_config(self):
        return LLMConfig(
            provider=ProviderType.DEEPSEEK,
            api_key="deepseek-test-key",
            model="deepseek-chat"
        )

    def test_initialization_uses_correct_base_url(self, deepseek_config):
        """Test DeepSeekProvider uses correct base URL."""
        mock_mod, mock_client = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = DeepSeekProvider(deepseek_config)

            mock_mod.OpenAI.assert_called_once_with(
                api_key="deepseek-test-key",
                base_url="https://api.deepseek.com/v1"
            )

    def test_chat(self, deepseek_config, sample_messages):
        """Test DeepSeekProvider.chat() works correctly."""
        mock_mod, mock_client = _setup_openai_mock(mock_text="DeepSeek response")
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = DeepSeekProvider(deepseek_config)
            response = provider.chat(sample_messages)

            assert response.content == "DeepSeek response"
            assert response.provider == "deepseek"

    def test_default_model(self):
        """Test DeepSeekProvider uses correct default model."""
        assert DeepSeekProvider.DEFAULT_MODEL == "deepseek-chat"

    def test_base_url(self):
        """Test DeepSeekProvider has correct base URL."""
        assert DeepSeekProvider.BASE_URL == "https://api.deepseek.com/v1"


# =============================================================================
# TESTS: OllamaProvider
# =============================================================================

class TestOllamaProvider:
    """Tests for OllamaProvider."""

    @pytest.fixture
    def ollama_config(self):
        return LLMConfig(
            provider=ProviderType.OLLAMA,
            api_key="",  # Ollama doesn't need API key
            model="llama3"
        )

    def test_initialization_uses_ollama_api_key(self, ollama_config):
        """Test OllamaProvider uses 'ollama' as API key."""
        mock_mod, mock_client = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OllamaProvider(ollama_config)

            mock_mod.OpenAI.assert_called_once_with(
                api_key="ollama",
                base_url="http://localhost:11434/v1"
            )

    def test_chat_no_usage(self, ollama_config, sample_messages):
        """Test OllamaProvider.chat() returns None for usage."""
        mock_mod = MagicMock()
        mock_client = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Ollama response", tool_calls=None))]
        mock_client.chat.completions.create.return_value = mock_response
        mock_mod.OpenAI.return_value = mock_client

        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OllamaProvider(ollama_config)
            response = provider.chat(sample_messages)

            assert response.content == "Ollama response"
            assert response.provider == "ollama"
            assert response.usage is None

    def test_default_model(self):
        """Test OllamaProvider uses correct default model."""
        assert OllamaProvider.DEFAULT_MODEL == "llama3"

    def test_default_base_url(self):
        """Test OllamaProvider has correct default base URL."""
        assert OllamaProvider.DEFAULT_BASE_URL == "http://localhost:11434/v1"


# =============================================================================
# TESTS: OpenRouterProvider
# =============================================================================

class TestOpenRouterProvider:
    """Tests for OpenRouterProvider."""

    @pytest.fixture
    def openrouter_config(self):
        return LLMConfig(
            provider=ProviderType.OPENROUTER,
            api_key="openrouter-test-key",
            model="anthropic/claude-3.5-sonnet"
        )

    def test_initialization(self, openrouter_config):
        """Test OpenRouterProvider initializes with correct base URL."""
        mock_mod, mock_client = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OpenRouterProvider(openrouter_config)

            mock_mod.OpenAI.assert_called_once_with(
                api_key="openrouter-test-key",
                base_url="https://openrouter.ai/api/v1"
            )

    def test_chat_includes_headers(self, openrouter_config, sample_messages):
        """Test OpenRouterProvider includes required headers."""
        mock_mod, mock_client = _setup_openai_mock(mock_text="OpenRouter response")
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = OpenRouterProvider(openrouter_config)
            response = provider.chat(sample_messages)

            # Check extra_headers were passed
            call_args = mock_client.chat.completions.create.call_args
            extra_headers = call_args.kwargs.get('extra_headers', {})
            assert "HTTP-Referer" in extra_headers
            assert "X-Title" in extra_headers

    def test_default_model(self):
        """Test OpenRouterProvider uses correct default model."""
        assert OpenRouterProvider.DEFAULT_MODEL == "anthropic/claude-3.5-sonnet"


# =============================================================================
# TESTS: LLMProvider Factory
# =============================================================================

class TestLLMProviderFactory:
    """Tests for LLMProvider factory class."""

    def test_create_anthropic(self):
        """Test creating Anthropic provider."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = LLMProvider.create("anthropic", api_key="test-key")
            assert isinstance(provider, AnthropicProvider)

    def test_create_openai(self):
        """Test creating OpenAI provider."""
        mock_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = LLMProvider.create("openai", api_key="test-key")
            assert isinstance(provider, OpenAIProvider)

    def test_create_google(self):
        """Test creating Google provider."""
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_google.generativeai = mock_genai
        with patch.dict('sys.modules', {
            'google': mock_google,
            'google.generativeai': mock_genai,
        }):
            provider = LLMProvider.create("google", api_key="test-key")
            assert isinstance(provider, GoogleProvider)

    def test_create_deepseek(self):
        """Test creating DeepSeek provider."""
        mock_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = LLMProvider.create("deepseek", api_key="test-key")
            assert isinstance(provider, DeepSeekProvider)

    def test_create_ollama(self):
        """Test creating Ollama provider."""
        mock_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = LLMProvider.create("ollama")
            assert isinstance(provider, OllamaProvider)

    def test_create_openrouter(self):
        """Test creating OpenRouter provider."""
        mock_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {'openai': mock_mod}):
            provider = LLMProvider.create("openrouter", api_key="test-key")
            assert isinstance(provider, OpenRouterProvider)

    def test_create_case_insensitive(self):
        """Test provider creation is case insensitive."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider1 = LLMProvider.create("ANTHROPIC", api_key="test-key")
            provider2 = LLMProvider.create("Anthropic", api_key="test-key")
            assert isinstance(provider1, AnthropicProvider)
            assert isinstance(provider2, AnthropicProvider)

    def test_create_invalid_provider(self):
        """Test creating invalid provider raises error."""
        with pytest.raises(ValueError, match="not supported"):
            LLMProvider.create("invalid_provider", api_key="test-key")

    def test_create_with_model(self):
        """Test creating provider with specific model."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = LLMProvider.create(
                "anthropic",
                api_key="test-key",
                model="claude-3-opus-20240229"
            )
            assert provider.config.model == "claude-3-opus-20240229"

    def test_create_from_env_variable(self):
        """Test creating provider with API key from environment."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "env-api-key"}):
            with patch.dict('sys.modules', {'anthropic': mock_mod}):
                provider = LLMProvider.create("anthropic")
                assert provider.config.api_key == "env-api-key"

    def test_create_missing_api_key_raises_error(self):
        """Test creating provider without API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear all relevant env vars
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]:
                os.environ.pop(var, None)

            with pytest.raises(ValueError, match="API key not found"):
                LLMProvider.create("anthropic")


# =============================================================================
# TESTS: LLMProvider.from_env()
# =============================================================================

class TestLLMProviderFromEnv:
    """Tests for LLMProvider.from_env() auto-detection."""

    def test_from_env_anthropic_priority(self):
        """Test Anthropic has highest priority."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "anthropic-key",
            "OPENAI_API_KEY": "openai-key"
        }):
            with patch.dict('sys.modules', {'anthropic': mock_mod}):
                provider = LLMProvider.from_env()
                assert isinstance(provider, AnthropicProvider)

    def test_from_env_openai_second(self):
        """Test OpenAI is selected when Anthropic not available."""
        mock_mod, _ = _setup_openai_mock()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with patch.dict('sys.modules', {'openai': mock_mod}):
                provider = LLMProvider.from_env()
                assert isinstance(provider, OpenAIProvider)

    def test_from_env_google_third(self):
        """Test Google is selected when higher priority not available."""
        mock_google = MagicMock()
        mock_genai = MagicMock()
        mock_google.generativeai = mock_genai
        env = {"GOOGLE_API_KEY": "google-key"}
        with patch.dict(os.environ, env, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]:
                os.environ.pop(var, None)
            with patch.dict('sys.modules', {
                'google': mock_google,
                'google.generativeai': mock_genai,
            }):
                provider = LLMProvider.from_env()
                assert isinstance(provider, GoogleProvider)

    def test_from_env_deepseek_fourth(self):
        """Test DeepSeek is selected correctly."""
        mock_mod, _ = _setup_openai_mock()
        env = {"DEEPSEEK_API_KEY": "deepseek-key"}
        with patch.dict(os.environ, env, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"]:
                os.environ.pop(var, None)
            with patch.dict('sys.modules', {'openai': mock_mod}):
                provider = LLMProvider.from_env()
                assert isinstance(provider, DeepSeekProvider)

    def test_from_env_openrouter_fifth(self):
        """Test OpenRouter is selected correctly."""
        mock_mod, _ = _setup_openai_mock()
        env = {"OPENROUTER_API_KEY": "openrouter-key"}
        with patch.dict(os.environ, env, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "DEEPSEEK_API_KEY"]:
                os.environ.pop(var, None)
            with patch.dict('sys.modules', {'openai': mock_mod}):
                provider = LLMProvider.from_env()
                assert isinstance(provider, OpenRouterProvider)

    def test_from_env_ollama_fallback(self):
        """Test Ollama is used as fallback."""
        mock_mod, _ = _setup_openai_mock()
        with patch.dict(os.environ, {}, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                       "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"]:
                os.environ.pop(var, None)
            with patch.dict('sys.modules', {'openai': mock_mod}):
                provider = LLMProvider.from_env()
                assert isinstance(provider, OllamaProvider)

    def test_from_env_no_providers_available(self):
        """Test error when no providers available."""
        mock_mod = MagicMock()
        mock_mod.OpenAI.side_effect = Exception("Connection error")
        with patch.dict(os.environ, {}, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                       "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"]:
                os.environ.pop(var, None)
            with patch.dict('sys.modules', {'openai': mock_mod}):
                with pytest.raises(ValueError, match="No API key found"):
                    LLMProvider.from_env()


# =============================================================================
# TESTS: LLMManager
# =============================================================================

class TestLLMManager:
    """Tests for LLMManager with multiple providers and fallbacks."""

    def test_add_single_provider(self):
        """Test adding a single provider."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="test-key")

            assert "claude" in manager.providers
            assert manager.primary == "claude"
            assert manager.fallbacks == []

    def test_add_multiple_providers(self):
        """Test adding multiple providers with primary and fallbacks."""
        mock_anthropic_mod, _ = _setup_anthropic_mock()
        mock_openai_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {
            'anthropic': mock_anthropic_mod,
            'openai': mock_openai_mod,
        }):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1", is_primary=True)
            manager.add_provider("gpt", "openai", api_key="key2")

            assert manager.primary == "claude"
            assert "gpt" in manager.fallbacks

    def test_chat_uses_primary(self):
        """Test chat uses primary provider."""
        mock_mod, mock_client = _setup_anthropic_mock(mock_text="Primary response")
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1", is_primary=True)

            response = manager.chat([{"role": "user", "content": "Hello"}])
            assert response.content == "Primary response"

    def test_chat_with_specific_provider(self):
        """Test chat with specific provider name."""
        mock_anthropic_mod, mock_anthro_client = _setup_anthropic_mock(mock_text="Anthropic response")
        mock_openai_mod, mock_openai_client = _setup_openai_mock(mock_text="OpenAI response")
        with patch.dict('sys.modules', {
            'anthropic': mock_anthropic_mod,
            'openai': mock_openai_mod,
        }):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1", is_primary=True)
            manager.add_provider("gpt", "openai", api_key="key2")

            response = manager.chat(
                [{"role": "user", "content": "Hello"}],
                provider_name="gpt"
            )
            assert response.content == "OpenAI response"

    def test_fallback_on_failure(self):
        """Test fallback to secondary provider on failure."""
        # Primary (anthropic) fails
        mock_anthropic_mod = MagicMock()
        mock_anthro_client = Mock()
        mock_anthro_client.messages.create.side_effect = Exception("API Error")
        mock_anthropic_mod.Anthropic.return_value = mock_anthro_client

        # Fallback (openai) succeeds
        mock_openai_mod, mock_openai_client = _setup_openai_mock(mock_text="Fallback response")

        with patch.dict('sys.modules', {
            'anthropic': mock_anthropic_mod,
            'openai': mock_openai_mod,
        }):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1", is_primary=True)
            manager.add_provider("gpt", "openai", api_key="key2")

            response = manager.chat([{"role": "user", "content": "Hello"}])
            assert response.content == "Fallback response"

    def test_all_providers_fail(self):
        """Test error when all providers fail."""
        mock_anthropic_mod = MagicMock()
        mock_anthro_client = Mock()
        mock_anthro_client.messages.create.side_effect = Exception("Anthropic Error")
        mock_anthropic_mod.Anthropic.return_value = mock_anthro_client

        mock_openai_mod = MagicMock()
        mock_openai_client = Mock()
        mock_openai_client.chat.completions.create.side_effect = Exception("OpenAI Error")
        mock_openai_mod.OpenAI.return_value = mock_openai_client

        with patch.dict('sys.modules', {
            'anthropic': mock_anthropic_mod,
            'openai': mock_openai_mod,
        }):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1", is_primary=True)
            manager.add_provider("gpt", "openai", api_key="key2")

            with pytest.raises(Exception, match="OpenAI Error"):
                manager.chat([{"role": "user", "content": "Hello"}])

    def test_simple_chat(self):
        """Test simple_chat convenience method."""
        mock_mod, mock_client = _setup_anthropic_mock(mock_text="Simple response")
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1")

            result = manager.simple_chat("Hello")
            assert result == "Simple response"

    def test_list_providers(self):
        """Test list_providers returns correct format."""
        mock_anthropic_mod, _ = _setup_anthropic_mock()
        mock_openai_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {
            'anthropic': mock_anthropic_mod,
            'openai': mock_openai_mod,
        }):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key1", model="claude-3-sonnet")
            manager.add_provider("gpt", "openai", api_key="key2")

            providers = manager.list_providers()
            assert "claude" in providers
            assert "gpt" in providers
            assert "anthropic" in providers["claude"]

    def test_empty_manager(self):
        """Test error when manager has no providers."""
        manager = LLMManager()
        with pytest.raises(ValueError, match="No providers available"):
            manager.chat([{"role": "user", "content": "Hello"}])


# =============================================================================
# TESTS: get_available_providers()
# =============================================================================

class TestGetAvailableProviders:
    """Tests for get_available_providers utility function."""

    def test_returns_anthropic_when_key_set(self):
        """Test returns anthropic when API key is set."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
            providers = get_available_providers()
            assert "anthropic" in providers

    def test_returns_openai_when_key_set(self):
        """Test returns openai when API key is set."""
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
            providers = get_available_providers()
            assert "openai" in providers

    def test_returns_google_when_key_set(self):
        """Test returns google when API key is set."""
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "test-key"}):
            providers = get_available_providers()
            assert "google" in providers

    def test_returns_deepseek_when_key_set(self):
        """Test returns deepseek when API key is set."""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}):
            providers = get_available_providers()
            assert "deepseek" in providers

    def test_returns_openrouter_when_key_set(self):
        """Test returns openrouter when API key is set."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-key"}):
            providers = get_available_providers()
            assert "openrouter" in providers

    def test_returns_multiple_providers(self):
        """Test returns multiple providers when multiple keys set."""
        with patch.dict(os.environ, {
            "ANTHROPIC_API_KEY": "key1",
            "OPENAI_API_KEY": "key2",
            "GOOGLE_API_KEY": "key3"
        }):
            providers = get_available_providers()
            assert "anthropic" in providers
            assert "openai" in providers
            assert "google" in providers

    def test_ollama_check_with_network(self):
        """Test Ollama check makes network request."""
        with patch.dict(os.environ, {}, clear=True):
            with patch('urllib.request.urlopen') as mock_urlopen:
                mock_urlopen.return_value = Mock()
                providers = get_available_providers()
                assert "ollama" in providers

    def test_ollama_not_available_on_network_error(self):
        """Test Ollama not included on network error."""
        with patch.dict(os.environ, {}, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                       "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"]:
                os.environ.pop(var, None)
            with patch('urllib.request.urlopen') as mock_urlopen:
                mock_urlopen.side_effect = Exception("Connection refused")
                providers = get_available_providers()
                assert "ollama" not in providers

    def test_returns_empty_list_no_keys(self):
        """Test returns empty when no keys and no Ollama."""
        with patch.dict(os.environ, {}, clear=True):
            for var in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY",
                       "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"]:
                os.environ.pop(var, None)
            with patch('urllib.request.urlopen') as mock_urlopen:
                mock_urlopen.side_effect = Exception("Connection refused")
                providers = get_available_providers()
                assert providers == []


# =============================================================================
# TESTS: Error Handling
# =============================================================================

class TestErrorHandling:
    """Tests for various error conditions."""

    def test_invalid_provider_type_string(self):
        """Test invalid provider string raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            LLMProvider.create("not_a_provider", api_key="test")
        assert "not supported" in str(exc_info.value)
        assert "Available" in str(exc_info.value)

    def test_missing_api_key_anthropic(self):
        """Test missing Anthropic API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(ValueError, match="API key not found"):
                LLMProvider.create("anthropic")

    def test_missing_api_key_openai(self):
        """Test missing OpenAI API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_API_KEY", None)
            with pytest.raises(ValueError, match="API key not found"):
                LLMProvider.create("openai")

    def test_missing_api_key_google(self):
        """Test missing Google API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("GOOGLE_API_KEY", None)
            with pytest.raises(ValueError, match="API key not found"):
                LLMProvider.create("google")

    def test_import_error_anthropic(self):
        """Test ImportError when anthropic package not installed."""
        config = LLMConfig(
            provider=ProviderType.ANTHROPIC,
            api_key="test-key",
            model="claude-3-sonnet"
        )
        real_import = __import__

        def fail_anthropic(name, *args, **kwargs):
            if name == 'anthropic':
                raise ImportError("No module named 'anthropic'")
            return real_import(name, *args, **kwargs)

        with patch.dict('sys.modules', {'anthropic': None}):
            with patch('builtins.__import__', side_effect=fail_anthropic):
                with pytest.raises(ImportError, match="Install anthropic"):
                    AnthropicProvider(config)

    def test_import_error_openai(self):
        """Test ImportError when openai package not installed."""
        config = LLMConfig(
            provider=ProviderType.OPENAI,
            api_key="test-key",
            model="gpt-4"
        )
        real_import = __import__

        def fail_openai(name, *args, **kwargs):
            if name == 'openai':
                raise ImportError("No module named 'openai'")
            return real_import(name, *args, **kwargs)

        with patch.dict('sys.modules', {'openai': None}):
            with patch('builtins.__import__', side_effect=fail_openai):
                with pytest.raises(ImportError, match="Install openai"):
                    OpenAIProvider(config)

    def test_import_error_google(self):
        """Test ImportError when google-generativeai package not installed."""
        config = LLMConfig(
            provider=ProviderType.GOOGLE,
            api_key="test-key",
            model="gemini-1.5-pro"
        )
        real_import = __import__

        def fail_google(name, *args, **kwargs):
            if 'google' in name:
                raise ImportError("No module named 'google.generativeai'")
            return real_import(name, *args, **kwargs)

        with patch.dict('sys.modules', {'google': None, 'google.generativeai': None}):
            with patch('builtins.__import__', side_effect=fail_google):
                with pytest.raises(ImportError, match="Install google-generativeai"):
                    GoogleProvider(config)

    def test_chat_api_error(self):
        """Test API error during chat propagates correctly."""
        mock_mod = MagicMock()
        mock_client = Mock()
        mock_client.messages.create.side_effect = Exception("API rate limit exceeded")
        mock_mod.Anthropic.return_value = mock_client

        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = LLMProvider.create("anthropic", api_key="test-key")

            with pytest.raises(Exception, match="API rate limit exceeded"):
                provider.chat([{"role": "user", "content": "Hello"}])


# =============================================================================
# TESTS: ProviderType Enum
# =============================================================================

class TestProviderType:
    """Tests for ProviderType enum."""

    def test_all_providers_defined(self):
        """Test all expected providers are defined."""
        assert ProviderType.ANTHROPIC.value == "anthropic"
        assert ProviderType.OPENAI.value == "openai"
        assert ProviderType.GOOGLE.value == "google"
        assert ProviderType.DEEPSEEK.value == "deepseek"
        assert ProviderType.OLLAMA.value == "ollama"
        assert ProviderType.OPENROUTER.value == "openrouter"

    def test_provider_count(self):
        """Test correct number of providers."""
        assert len(ProviderType) == 6


# =============================================================================
# TESTS: BaseLLMProvider
# =============================================================================

class TestBaseLLMProvider:
    """Tests for BaseLLMProvider abstract class."""

    def test_name_property(self, sample_config):
        """Test name property returns provider value."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = AnthropicProvider(sample_config)
            assert provider.name == "anthropic"

    def test_config_stored(self, sample_config):
        """Test config is stored on provider."""
        mock_mod, _ = _setup_anthropic_mock()
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = AnthropicProvider(sample_config)
            assert provider.config == sample_config
            assert provider.config.api_key == "test-api-key"


# =============================================================================
# INTEGRATION-STYLE TESTS (still mocked, but test workflows)
# =============================================================================

class TestIntegrationWorkflows:
    """Integration-style tests for common workflows."""

    def test_manager_with_system_prompt(self):
        """Test manager passes system prompt correctly."""
        mock_mod, mock_client = _setup_anthropic_mock(mock_text="System-aware response")
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            manager = LLMManager()
            manager.add_provider("claude", "anthropic", api_key="key")

            response = manager.chat(
                [{"role": "user", "content": "Hello"}],
                system="You are a helpful assistant"
            )

            # Verify system was passed
            call_args = mock_client.messages.create.call_args
            assert call_args.kwargs.get('system') == "You are a helpful assistant"

    def test_provider_chain_creation(self):
        """Test creating a chain of providers."""
        mock_anthropic_mod, _ = _setup_anthropic_mock()
        mock_openai_mod, _ = _setup_openai_mock()
        with patch.dict('sys.modules', {
            'anthropic': mock_anthropic_mod,
            'openai': mock_openai_mod,
        }):
            manager = LLMManager()

            # Add primary
            manager.add_provider(
                "primary",
                "anthropic",
                api_key="key1",
                is_primary=True
            )

            # Add fallbacks
            manager.add_provider("fallback1", "openai", api_key="key2")
            manager.add_provider("fallback2", "openai", api_key="key3")

            assert manager.primary == "primary"
            assert len(manager.fallbacks) == 2
            assert "fallback1" in manager.fallbacks
            assert "fallback2" in manager.fallbacks

    def test_response_contains_all_fields(self):
        """Test response object has all expected fields."""
        mock_mod, mock_client = _setup_anthropic_mock(
            mock_text="Test response", input_tokens=5, output_tokens=15
        )
        with patch.dict('sys.modules', {'anthropic': mock_mod}):
            provider = LLMProvider.create("anthropic", api_key="key")
            response = provider.chat([{"role": "user", "content": "Test"}])

            assert response.content == "Test response"
            assert response.provider == "anthropic"
            assert response.usage["input_tokens"] == 5
            assert response.usage["output_tokens"] == 15
            assert response.raw_response is not None
