"""
ARIA - Multi-Provider LLM Interface
====================================

Support for multiple LLM providers:
- Anthropic (Claude)
- OpenAI (GPT-4, GPT-3.5)
- Google (Gemini)
- DeepSeek
- Ollama (local)
- OpenRouter (multiple models)

Usage:
    provider = LLMProvider.create("anthropic", api_key="...")
    response = provider.chat("Hello, how are you?")
"""

import json
import os
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Generator
from enum import Enum

logger = logging.getLogger("aria.llm")


class ProviderType(Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"


@dataclass
class ToolCall:
    """Standardized tool call from any LLM"""
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class LLMResponse:
    """Standardized response from any LLM"""
    content: str
    model: str
    provider: str
    usage: Dict[str, int] = None
    raw_response: Any = None
    tool_calls: Optional[List[ToolCall]] = None


@dataclass
class LLMConfig:
    """Configuration for an LLM provider"""
    provider: ProviderType
    api_key: str
    model: str
    max_tokens: int = 1024
    temperature: float = 0.7
    base_url: Optional[str] = None  # For Ollama or custom endpoints


@dataclass
class StreamChunk:
    """A single chunk from a streaming LLM response."""
    text: str = ""                          # Text delta (may be empty)
    done: bool = False                      # True on final chunk
    tool_calls: Optional[List[ToolCall]] = None  # Set on final chunk if tools were called
    usage: Optional[Dict[str, int]] = None  # Set on final chunk
    raw_response: Any = None                # Full response on final chunk


class BaseLLMProvider(ABC):
    """Base class for all LLM providers"""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client = None
        self._initialize()

    @abstractmethod
    def _initialize(self):
        """Initialize the provider client"""
        pass

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        """Send messages and get response"""
        pass

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> Generator[StreamChunk, None, None]:
        """Stream response token by token. Default: fallback to non-streaming."""
        response = self.chat(messages, system, **kwargs)
        yield StreamChunk(text=response.content, done=True,
                          tool_calls=response.tool_calls,
                          usage=response.usage, raw_response=response.raw_response)

    def simple_chat(self, user_message: str, system: str = None) -> str:
        """Simplified method for a single question"""
        messages = [{"role": "user", "content": user_message}]
        response = self.chat(messages, system=system)
        return response.content

    @property
    def name(self) -> str:
        return self.config.provider.value


class AnthropicProvider(BaseLLMProvider):
    """Provider for Anthropic (Claude)"""

    DEFAULT_MODEL = "claude-sonnet-4-20250514"

    def _initialize(self):
        try:
            from anthropic import Anthropic
            self.client = Anthropic(api_key=self.config.api_key)
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        create_kwargs = dict(
            model=self.config.model or self.DEFAULT_MODEL,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            system=system or "",
            messages=messages,
        )

        # Function calling support
        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _anthropic_format_tools(tools)

        response = self.client.messages.create(**create_kwargs)

        # Extract text content and tool calls
        text_parts = []
        tool_calls = []
        for block in response.content:
            if hasattr(block, "text"):
                text_parts.append(block.text)
            elif hasattr(block, "type") and block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    args=block.input if isinstance(block.input, dict) else {},
                ))

        return LLMResponse(
            content="\n".join(text_parts),
            model=self.config.model,
            provider="anthropic",
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            },
            raw_response=response,
            tool_calls=tool_calls if tool_calls else None,
        )

    def stream_chat(self, messages, system=None, **kwargs):
        """Stream tokens from Anthropic Claude."""
        create_kwargs = dict(
            model=self.config.model or self.DEFAULT_MODEL,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            system=system or "",
            messages=messages,
        )

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _anthropic_format_tools(tools)

        collected_text = ""
        tool_calls = []
        usage = {}
        current_tool_block = None

        with self.client.messages.stream(**create_kwargs) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if hasattr(event.content_block, "type") and event.content_block.type == "tool_use":
                        current_tool_block = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input_json": "",
                        }

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        collected_text += event.delta.text
                        yield StreamChunk(text=event.delta.text)
                    elif hasattr(event.delta, "partial_json") and current_tool_block is not None:
                        current_tool_block["input_json"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if current_tool_block is not None:
                        try:
                            args = json.loads(current_tool_block["input_json"]) if current_tool_block["input_json"] else {}
                        except json.JSONDecodeError:
                            args = {}
                        tool_calls.append(ToolCall(
                            id=current_tool_block["id"],
                            name=current_tool_block["name"],
                            args=args,
                        ))
                        current_tool_block = None

                elif event.type == "message_delta":
                    if hasattr(event, "usage") and event.usage:
                        usage["output_tokens"] = getattr(event.usage, "output_tokens", 0)

                elif event.type == "message_start":
                    if hasattr(event, "message") and hasattr(event.message, "usage"):
                        usage["input_tokens"] = getattr(event.message.usage, "input_tokens", 0)

        yield StreamChunk(
            text="", done=True,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage if usage else None,
        )


class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI (GPT-4, GPT-3.5)"""

    DEFAULT_MODEL = "gpt-4o"

    def _initialize(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url  # Allows custom endpoints
            )
        except ImportError:
            raise ImportError("Install openai: pip install openai")

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        # OpenAI uses system message in the message list
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs = dict(
            model=self.config.model or self.DEFAULT_MODEL,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            temperature=kwargs.get("temperature", self.config.temperature),
            messages=full_messages,
        )

        # Function calling support
        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _openai_format_tools(tools)

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        return LLMResponse(
            content=msg.content or "",
            model=self.config.model,
            provider="openai",
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            },
            raw_response=response,
            tool_calls=_openai_parse_tool_calls(msg),
        )

    def stream_chat(self, messages, system=None, **kwargs):
        return _openai_stream_chat(
            self.client, messages, system, "openai",
            self.config.model or self.DEFAULT_MODEL, self.config, **kwargs)


class GoogleProvider(BaseLLMProvider):
    """Provider for Google (Gemini)"""

    DEFAULT_MODEL = "gemini-1.5-pro"

    def _initialize(self):
        try:
            import google.generativeai as genai
            genai.configure(api_key=self.config.api_key)
            self.genai = genai
            self.client = genai.GenerativeModel(
                self.config.model or self.DEFAULT_MODEL
            )
        except ImportError:
            raise ImportError("Install google-generativeai: pip install google-generativeai")

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        # Convert message format to Gemini
        gemini_messages = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            gemini_messages.append({
                "role": role,
                "parts": [msg["content"]]
            })

        # Gemini handles system prompt differently
        if system:
            # Prepend system as context
            gemini_messages.insert(0, {
                "role": "user",
                "parts": [f"System instructions: {system}"]
            })
            gemini_messages.insert(1, {
                "role": "model",
                "parts": ["Understood. I'll follow these instructions."]
            })

        # Function calling support
        tools_param = kwargs.get("tools")
        genai_tools = None
        if tools_param:
            genai_tools = _google_format_tools(tools_param, self.genai)

        if genai_tools:
            model = self.genai.GenerativeModel(
                self.config.model or self.DEFAULT_MODEL,
                tools=genai_tools,
            )
        else:
            model = self.client

        chat = model.start_chat(history=gemini_messages[:-1])
        response = chat.send_message(gemini_messages[-1]["parts"][0])

        # Parse tool calls from response
        tool_calls = _google_parse_tool_calls(response)

        return LLMResponse(
            content=response.text if not tool_calls else "",
            model=self.config.model or self.DEFAULT_MODEL,
            provider="google",
            usage=None,
            raw_response=response,
            tool_calls=tool_calls,
        )


class DeepSeekProvider(BaseLLMProvider):
    """Provider for DeepSeek (OpenAI API compatible)"""

    DEFAULT_MODEL = "deepseek-chat"
    BASE_URL = "https://api.deepseek.com/v1"

    def _initialize(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url or self.BASE_URL
            )
        except ImportError:
            raise ImportError("Install openai: pip install openai")

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs = dict(
            model=self.config.model or self.DEFAULT_MODEL,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            temperature=kwargs.get("temperature", self.config.temperature),
            messages=full_messages,
        )

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _openai_format_tools(tools)

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        return LLMResponse(
            content=msg.content or "",
            model=self.config.model or self.DEFAULT_MODEL,
            provider="deepseek",
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            } if response.usage else None,
            raw_response=response,
            tool_calls=_openai_parse_tool_calls(msg),
        )

    def stream_chat(self, messages, system=None, **kwargs):
        return _openai_stream_chat(
            self.client, messages, system, "deepseek",
            self.config.model or self.DEFAULT_MODEL, self.config, **kwargs)


class OllamaProvider(BaseLLMProvider):
    """Provider for Ollama (local models)"""

    DEFAULT_MODEL = "llama3"
    DEFAULT_BASE_URL = "http://localhost:11434/v1"

    def _initialize(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key="ollama",
                base_url=self.config.base_url or self.DEFAULT_BASE_URL
            )
        except ImportError:
            raise ImportError("Install openai: pip install openai")

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs = dict(
            model=self.config.model or self.DEFAULT_MODEL,
            messages=full_messages,
        )

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _openai_format_tools(tools)

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        return LLMResponse(
            content=msg.content or "",
            model=self.config.model or self.DEFAULT_MODEL,
            provider="ollama",
            usage=None,
            raw_response=response,
            tool_calls=_openai_parse_tool_calls(msg),
        )

    def stream_chat(self, messages, system=None, **kwargs):
        return _openai_stream_chat(
            self.client, messages, system, "ollama",
            self.config.model or self.DEFAULT_MODEL, self.config, **kwargs)

    def list_models(self) -> List[Dict[str, Any]]:
        """List models installed in the local Ollama instance.

        Returns a list of dicts with at least 'name' and 'size' (bytes).
        Returns [] if Ollama is not reachable.
        """
        import urllib.request
        import json as _json
        base = (self.config.base_url or self.DEFAULT_BASE_URL).rstrip("/")
        # The /v1 suffix is OpenAI-compat; native API lives at the root
        if base.endswith("/v1"):
            base = base[:-3]
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=2) as resp:
                data = _json.loads(resp.read().decode("utf-8"))
            return [
                {
                    "name": m.get("name", ""),
                    "size": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                }
                for m in data.get("models", [])
            ]
        except Exception:
            return []


class OpenRouterProvider(BaseLLMProvider):
    """Provider for OpenRouter (access to multiple models)"""

    DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
    BASE_URL = "https://openrouter.ai/api/v1"

    def _initialize(self):
        try:
            from openai import OpenAI
            self.client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.BASE_URL
            )
        except ImportError:
            raise ImportError("Install openai: pip install openai")

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> LLMResponse:
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        create_kwargs = dict(
            model=self.config.model or self.DEFAULT_MODEL,
            max_tokens=kwargs.get("max_tokens", self.config.max_tokens),
            messages=full_messages,
            extra_headers={
                "HTTP-Referer": "https://github.com/aria-ai",
                "X-Title": "ARIA"
            },
        )

        tools = kwargs.get("tools")
        if tools:
            create_kwargs["tools"] = _openai_format_tools(tools)

        response = self.client.chat.completions.create(**create_kwargs)
        msg = response.choices[0].message

        return LLMResponse(
            content=msg.content or "",
            model=self.config.model or self.DEFAULT_MODEL,
            provider="openrouter",
            usage={
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens
            } if response.usage else None,
            raw_response=response,
            tool_calls=_openai_parse_tool_calls(msg),
        )

    def stream_chat(self, messages, system=None, **kwargs):
        return _openai_stream_chat(
            self.client, messages, system, "openrouter",
            self.config.model or self.DEFAULT_MODEL, self.config,
            extra_headers={"HTTP-Referer": "https://github.com/aria-ai", "X-Title": "ARIA"},
            **kwargs)


# =============================================================================
# STREAMING HELPER FOR OPENAI-COMPATIBLE PROVIDERS
# =============================================================================

def _openai_stream_chat(
    client,
    messages: List[Dict[str, str]],
    system: str,
    provider_name: str,
    model: str,
    config: LLMConfig,
    **kwargs,
) -> Generator[StreamChunk, None, None]:
    """Shared streaming implementation for all OpenAI-compatible providers.

    Works for: OpenAI, DeepSeek, Ollama, OpenRouter.
    Yields StreamChunk objects with text deltas.
    Final chunk has done=True and includes tool_calls if any.
    """
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)

    create_kwargs = dict(
        model=model or config.model,
        max_tokens=kwargs.get("max_tokens", config.max_tokens),
        messages=full_messages,
        stream=True,
    )

    # Temperature (some providers don't support it)
    if hasattr(config, "temperature") and config.temperature is not None:
        create_kwargs["temperature"] = kwargs.get("temperature", config.temperature)

    # Tools
    tools = kwargs.get("tools")
    if tools:
        create_kwargs["tools"] = _openai_format_tools(tools)

    # Extra headers for OpenRouter
    extra_headers = kwargs.get("extra_headers")
    if extra_headers:
        create_kwargs["extra_headers"] = extra_headers

    stream = client.chat.completions.create(**create_kwargs)

    collected_text = ""
    # Accumulate tool call deltas: {index: {id, name, arguments}}
    tool_call_acc: Dict[int, Dict[str, str]] = {}

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        finish_reason = chunk.choices[0].finish_reason

        # Text content
        if delta and delta.content:
            collected_text += delta.content
            yield StreamChunk(text=delta.content)

        # Tool call deltas
        if delta and hasattr(delta, "tool_calls") and delta.tool_calls:
            for tc_delta in delta.tool_calls:
                idx = tc_delta.index
                if idx not in tool_call_acc:
                    tool_call_acc[idx] = {
                        "id": tc_delta.id or "",
                        "name": "",
                        "arguments": "",
                    }
                if tc_delta.id:
                    tool_call_acc[idx]["id"] = tc_delta.id
                if tc_delta.function:
                    if tc_delta.function.name:
                        tool_call_acc[idx]["name"] = tc_delta.function.name
                    if tc_delta.function.arguments:
                        tool_call_acc[idx]["arguments"] += tc_delta.function.arguments

        # Final chunk
        if finish_reason:
            tool_calls = None
            if tool_call_acc:
                tool_calls = []
                for idx in sorted(tool_call_acc):
                    tc = tool_call_acc[idx]
                    try:
                        args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                    except json.JSONDecodeError:
                        args = {}
                    tool_calls.append(ToolCall(id=tc["id"], name=tc["name"], args=args))

            usage = None
            if hasattr(chunk, "usage") and chunk.usage:
                usage = {
                    "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }

            yield StreamChunk(
                text="",
                done=True,
                tool_calls=tool_calls if tool_calls else None,
                usage=usage,
            )
            return

    # If we exit without finish_reason (shouldn't happen)
    yield StreamChunk(text="", done=True)


# =============================================================================
# TOOL CALL FORMAT HELPERS
# =============================================================================

def _openai_format_tools(tools: List[dict]) -> List[dict]:
    """Convert ARIA tool schemas to OpenAI format.
    Works for: OpenAI, DeepSeek, Ollama, OpenRouter.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _openai_parse_tool_calls(msg) -> Optional[List[ToolCall]]:
    """Parse tool calls from OpenAI-format response message."""
    if not hasattr(msg, "tool_calls") or not msg.tool_calls:
        return None
    import json
    calls = []
    for tc in msg.tool_calls:
        try:
            args = json.loads(tc.function.arguments) if isinstance(tc.function.arguments, str) else tc.function.arguments
        except (json.JSONDecodeError, AttributeError):
            args = {}
        calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
    return calls if calls else None


def _anthropic_format_tools(tools: List[dict]) -> List[dict]:
    """Convert ARIA tool schemas to Anthropic format."""
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]


def _google_format_tools(tools: List[dict], genai_module):
    """Convert ARIA tool schemas to Google Gemini format."""
    try:
        declarations = []
        for t in tools:
            params = t.get("parameters", {})
            # Gemini needs protos-style schema; simplify to basic dict
            declarations.append({
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": params,
            })
        return [genai_module.types.Tool(function_declarations=declarations)]
    except Exception as e:
        logger.warning(f"Failed to format Google tools: {e}")
        return None


def _google_parse_tool_calls(response) -> Optional[List[ToolCall]]:
    """Parse tool calls from Gemini response."""
    try:
        calls = []
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if hasattr(part, "function_call") and part.function_call:
                    fc = part.function_call
                    args = dict(fc.args) if fc.args else {}
                    calls.append(ToolCall(id=f"google_{fc.name}", name=fc.name, args=args))
        return calls if calls else None
    except Exception:
        return None


# =============================================================================
# FACTORY AND MANAGER
# =============================================================================

class LLMProvider:
    """Factory for creating LLM providers"""

    PROVIDERS = {
        ProviderType.ANTHROPIC: AnthropicProvider,
        ProviderType.OPENAI: OpenAIProvider,
        ProviderType.GOOGLE: GoogleProvider,
        ProviderType.DEEPSEEK: DeepSeekProvider,
        ProviderType.OLLAMA: OllamaProvider,
        ProviderType.OPENROUTER: OpenRouterProvider,
    }

    # Shared AuthManager instance (set via set_auth_manager)
    _auth_manager = None

    @classmethod
    def set_auth_manager(cls, auth_manager):
        """Set a shared AuthManager for credential resolution."""
        cls._auth_manager = auth_manager

    @classmethod
    def create(
        cls,
        provider: str,
        api_key: str = None,
        model: str = None,
        **kwargs
    ) -> BaseLLMProvider:
        """
        Create an LLM provider.

        Args:
            provider: "anthropic", "openai", "google", "deepseek", "ollama", "openrouter"
            api_key: API key (or environment variable or AuthManager)
            model: Specific model (optional)

        Returns:
            Provider instance
        """
        # Normalize provider name
        try:
            provider_type = ProviderType(provider.lower())
        except ValueError:
            available = [p.value for p in ProviderType]
            raise ValueError(f"Provider '{provider}' not supported. Available: {available}")

        # Resolve API key: explicit > AuthManager > env var
        if not api_key and cls._auth_manager:
            api_key = cls._auth_manager.get_credential(provider.lower())

        if not api_key:
            env_vars = {
                ProviderType.ANTHROPIC: "ANTHROPIC_API_KEY",
                ProviderType.OPENAI: "OPENAI_API_KEY",
                ProviderType.GOOGLE: "GOOGLE_API_KEY",
                ProviderType.DEEPSEEK: "DEEPSEEK_API_KEY",
                ProviderType.OLLAMA: None,  # Not needed
                ProviderType.OPENROUTER: "OPENROUTER_API_KEY",
            }
            env_var = env_vars.get(provider_type)
            if env_var:
                api_key = os.environ.get(env_var)
                if not api_key and provider_type != ProviderType.OLLAMA:
                    raise ValueError(f"API key not found. Configure {env_var}")

        config = LLMConfig(
            provider=provider_type,
            api_key=api_key or "",
            model=model,
            **kwargs
        )

        provider_class = cls.PROVIDERS[provider_type]
        return provider_class(config)

    @classmethod
    def from_env(cls, auth_manager=None) -> BaseLLMProvider:
        """
        Create a provider based on available credentials.
        Uses AuthManager if provided, falls back to env vars.
        Priority: ANTHROPIC > OPENAI > GOOGLE > DEEPSEEK > OPENROUTER > OLLAMA
        """
        if auth_manager:
            cls.set_auth_manager(auth_manager)

        # If AuthManager is set, use it for provider discovery
        if cls._auth_manager:
            available = cls._auth_manager.get_available_providers()
            # Honor explicit active provider selection if available
            active = None
            if hasattr(cls._auth_manager, "get_active_provider"):
                active = cls._auth_manager.get_active_provider()
            if active and active in available:
                return cls.create(active)
            priority_order = ["anthropic", "openai", "google", "deepseek", "openrouter"]
            for provider in priority_order:
                if provider in available:
                    return cls.create(provider)

        # Fallback to direct env var check
        priority = [
            ("ANTHROPIC_API_KEY", "anthropic"),
            ("OPENAI_API_KEY", "openai"),
            ("GOOGLE_API_KEY", "google"),
            ("DEEPSEEK_API_KEY", "deepseek"),
            ("OPENROUTER_API_KEY", "openrouter"),
        ]

        for env_var, provider in priority:
            if os.environ.get(env_var):
                return cls.create(provider)

        # Try Ollama as fallback (local, doesn't need key)
        try:
            return cls.create("ollama")
        except Exception:
            pass

        raise ValueError(
            "No API key found configured.\n"
            "Configure one of these environment variables:\n"
            "  - ANTHROPIC_API_KEY\n"
            "  - OPENAI_API_KEY\n"
            "  - GOOGLE_API_KEY\n"
            "  - DEEPSEEK_API_KEY\n"
            "  - OPENROUTER_API_KEY\n"
            "Or install Ollama to use local models."
        )


class LLMManager:
    """
    Manager for handling multiple providers and fallbacks.
    """

    def __init__(self):
        self.providers: Dict[str, BaseLLMProvider] = {}
        self.primary: Optional[str] = None
        self.fallbacks: List[str] = []

    def add_provider(
        self,
        name: str,
        provider: str,
        api_key: str = None,
        model: str = None,
        is_primary: bool = False,
        **kwargs
    ):
        """Add a provider to the manager"""
        self.providers[name] = LLMProvider.create(provider, api_key, model, **kwargs)

        if is_primary or self.primary is None:
            self.primary = name
        else:
            self.fallbacks.append(name)

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        provider_name: str = None,
        **kwargs
    ) -> LLMResponse:
        """
        Send messages using the specified or primary provider.
        With automatic fallback on failure.
        """
        providers_to_try = []

        if provider_name:
            providers_to_try.append(provider_name)
        else:
            providers_to_try.append(self.primary)
            providers_to_try.extend(self.fallbacks)

        last_error = None
        for name in providers_to_try:
            if name not in self.providers:
                continue
            try:
                response = self.providers[name].chat(messages, system, **kwargs)
                # Report success to AuthManager if available
                if LLMProvider._auth_manager:
                    provider_name = self.providers[name].name
                    LLMProvider._auth_manager.report_success(provider_name)
                return response
            except Exception as e:
                last_error = e
                # Report failure to AuthManager for rotation
                if LLMProvider._auth_manager:
                    from .auth_manager import classify_error
                    provider_name = self.providers[name].name
                    error_type = classify_error(e)
                    LLMProvider._auth_manager.report_failure(provider_name, error_type)
                    logger.warning(f"Provider {name} failed: {e}")
                continue

        raise last_error or ValueError("No providers available")

    def simple_chat(self, message: str, system: str = None) -> str:
        """Simplified chat"""
        response = self.chat([{"role": "user", "content": message}], system)
        return response.content

    def list_providers(self) -> Dict[str, str]:
        """List configured providers"""
        return {
            name: f"{p.name} ({p.config.model or 'default'})"
            for name, p in self.providers.items()
        }


# =============================================================================
# UTILITIES
# =============================================================================

def get_available_providers() -> List[str]:
    """Return providers that have API key configured"""
    available = []

    checks = [
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
    ]

    for provider, env_var in checks:
        if os.environ.get(env_var):
            available.append(provider)

    # Ollama always available if installed
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        available.append("ollama")
    except Exception:
        pass

    return available


def quick_test():
    """Quick test of available providers"""
    available = get_available_providers()
    print(f"Available providers: {available}")

    if available:
        provider = LLMProvider.create(available[0])
        response = provider.simple_chat("Say 'hello' in English")
        print(f"\n{provider.name}: {response}")


if __name__ == "__main__":
    quick_test()
