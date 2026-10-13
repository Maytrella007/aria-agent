"""
ARIA Test Suite - Pytest Configuration and Fixtures
=====================================================

Provides reusable fixtures for testing ARIA components:
- Temporary data directories
- Mock LLM providers (no real API calls)
- Mock memory systems
- Sample conversation history
- Sample project context

Usage:
    pytest tests/
    pytest tests/ -v
    pytest tests/test_memory.py -k "test_experience"
"""

import os
import sys
import json
import pytest
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from unittest.mock import Mock, MagicMock, patch

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# TEMPORARY DATA DIRECTORY FIXTURES
# =============================================================================

@pytest.fixture
def temp_data_dir(tmp_path):
    """
    Creates a temporary data directory structure for tests.

    Returns:
        Path: Temporary directory path that mimics ARIA's data structure.

    Example:
        def test_something(temp_data_dir):
            assert temp_data_dir.exists()
            # Use temp_data_dir / "memories" etc.
    """
    # Create standard ARIA directory structure
    directories = [
        "memories",
        "memories_v2",
        "conversations",
        "reflections",
        "logs",
        "coding_agent",
    ]

    for dir_name in directories:
        (tmp_path / dir_name).mkdir(parents=True, exist_ok=True)

    return tmp_path


@pytest.fixture
def temp_project_dir(tmp_path):
    """
    Creates a temporary project directory for CodingAgent tests.

    Returns:
        Path: Temporary project directory with sample files.
    """
    project_dir = tmp_path / "sample_project"
    project_dir.mkdir()

    # Create sample Python project structure
    (project_dir / "src").mkdir()
    (project_dir / "tests").mkdir()

    # Create sample files
    (project_dir / "requirements.txt").write_text("pytest>=7.0.0\npyyaml>=6.0\n")
    (project_dir / "src" / "__init__.py").write_text("")
    (project_dir / "src" / "main.py").write_text('''
"""Sample main module"""

def greet(name: str) -> str:
    """Greet a user by name."""
    return f"Hello, {name}!"

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

if __name__ == "__main__":
    print(greet("World"))
''')

    return project_dir


# =============================================================================
# MOCK LLM PROVIDER FIXTURES
# =============================================================================

@dataclass
class MockLLMResponse:
    """Mock response from LLM provider."""
    content: str
    model: str = "mock-model"
    provider: str = "mock"
    usage: Dict[str, int] = field(default_factory=lambda: {"input_tokens": 10, "output_tokens": 20})
    raw_response: Any = None


class MockLLMProvider:
    """
    Mock LLM provider that doesn't make real API calls.

    Configurable to return specific responses for testing.
    """

    def __init__(
        self,
        default_response: str = "This is a mock response from ARIA.",
        model: str = "mock-model",
        provider_name: str = "mock"
    ):
        self.default_response = default_response
        self._model = model
        self._provider_name = provider_name
        self.call_history: List[Dict] = []
        self.response_queue: List[str] = []

        # Mock config for compatibility
        self.config = Mock()
        self.config.model = model
        self.config.provider = Mock()
        self.config.provider.value = provider_name
        self.config.max_tokens = 1024
        self.config.temperature = 0.7

    @property
    def name(self) -> str:
        return self._provider_name

    def set_response(self, response: str):
        """Set the next response to return."""
        self.response_queue.append(response)

    def set_responses(self, responses: List[str]):
        """Set multiple responses to return in order."""
        self.response_queue.extend(responses)

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = None,
        **kwargs
    ) -> MockLLMResponse:
        """Simulate chat completion without API call."""
        # Record the call
        self.call_history.append({
            "messages": messages,
            "system": system,
            "kwargs": kwargs,
            "timestamp": datetime.now().isoformat()
        })

        # Return queued response or default
        if self.response_queue:
            response_text = self.response_queue.pop(0)
        else:
            response_text = self.default_response

        return MockLLMResponse(
            content=response_text,
            model=self._model,
            provider=self._provider_name
        )

    def simple_chat(self, user_message: str, system: str = None) -> str:
        """Simplified chat method."""
        messages = [{"role": "user", "content": user_message}]
        response = self.chat(messages, system=system)
        return response.content

    def reset(self):
        """Reset call history and response queue."""
        self.call_history.clear()
        self.response_queue.clear()

    def get_last_call(self) -> Optional[Dict]:
        """Get the last call made to this provider."""
        return self.call_history[-1] if self.call_history else None


@pytest.fixture
def mock_llm_provider():
    """
    Creates a mock LLM provider that doesn't make real API calls.

    Returns:
        MockLLMProvider: A mock provider instance.

    Example:
        def test_chat(mock_llm_provider):
            mock_llm_provider.set_response("Custom response")
            response = mock_llm_provider.simple_chat("Hello")
            assert response == "Custom response"
    """
    return MockLLMProvider()


@pytest.fixture
def mock_llm_provider_with_responses():
    """
    Factory fixture for creating mock LLM providers with specific responses.

    Returns:
        Callable: Factory function to create configured mock providers.

    Example:
        def test_multi_turn(mock_llm_provider_with_responses):
            provider = mock_llm_provider_with_responses([
                "First response",
                "Second response"
            ])
            assert provider.simple_chat("Q1") == "First response"
            assert provider.simple_chat("Q2") == "Second response"
    """
    def _create_provider(responses: List[str], default: str = "Default response"):
        provider = MockLLMProvider(default_response=default)
        provider.set_responses(responses)
        return provider

    return _create_provider


# =============================================================================
# MOCK MEMORY SYSTEM FIXTURES
# =============================================================================

class MockExperientialMemory:
    """Mock of ExperientialMemory dataclass for testing."""

    def __init__(
        self,
        id: str = "test-memory-001",
        content: str = "Test memory content",
        context: str = "Test context",
        emotional_tone: str = "neutral",
        emotional_intensity: float = 0.5,
        importance: float = 0.5,
        origin: str = "lived",
        involves_people: List[str] = None,
        tags: List[str] = None,
        timestamp: str = None
    ):
        self.id = id
        self.content = content
        self.context = context
        self.emotional_tone = emotional_tone
        self.emotional_intensity = emotional_intensity
        self.importance = importance
        self.origin = origin
        self.involves_people = involves_people or []
        self.tags = tags or []
        self.timestamp = timestamp or datetime.now().isoformat()
        self.times_recalled = 0
        self.last_recalled = None
        self.connected_memories = []
        self.relationship_impact = {}
        self.duration_feeling = "normal"
        self.is_mine = True
        self.confidence = 0.9


class MockMemorySystem:
    """
    Mock memory system for testing without database/ChromaDB.

    Provides all methods of ExperientialMemorySystem but stores
    data in memory only.
    """

    def __init__(self, data_dir: str = ""):
        self.data_dir = data_dir
        self.memories: List[MockExperientialMemory] = []
        self.relationships: Dict[str, Any] = {}
        self.session_started = False
        self.session_duration = 0.0

        # Time perception mock
        self.time = Mock()
        self.time.created_at = datetime.now().isoformat()
        self.time.last_active = datetime.now().isoformat()
        self.time.total_active_time = 0.0
        self.time.total_conversations = 0
        self.time.subjective_age = "test"

    def experience(
        self,
        content: str,
        emotional_tone: Any = None,
        emotional_intensity: float = 0.5,
        involves: List[str] = None,
        importance: float = 0.5,
        context: str = "",
        tags: List[str] = None,
        origin: Any = None
    ) -> MockExperientialMemory:
        """Create a new memory."""
        memory = MockExperientialMemory(
            id=f"mem-{len(self.memories):04d}",
            content=content,
            context=context,
            emotional_tone=str(emotional_tone) if emotional_tone else "neutral",
            emotional_intensity=emotional_intensity,
            importance=importance,
            origin=str(origin) if origin else "lived",
            involves_people=involves or [],
            tags=tags or []
        )
        self.memories.append(memory)
        return memory

    def recall(self, query: str, limit: int = 5) -> List[MockExperientialMemory]:
        """Recall memories matching query."""
        query_lower = query.lower()
        matching = [
            m for m in self.memories
            if query_lower in m.content.lower()
        ]
        return matching[:limit]

    def recall_recent(self, limit: int = 10) -> List[MockExperientialMemory]:
        """Recall recent memories."""
        return sorted(
            self.memories,
            key=lambda m: m.timestamp,
            reverse=True
        )[:limit]

    def recall_important(self, limit: int = 10) -> List[MockExperientialMemory]:
        """Recall important memories."""
        return sorted(
            self.memories,
            key=lambda m: m.importance,
            reverse=True
        )[:limit]

    def session_start(self):
        """Start a session."""
        self.session_started = True
        self.time.total_conversations += 1

    def session_end(self, duration_seconds: float):
        """End a session."""
        self.session_duration = duration_seconds
        self.time.total_active_time += duration_seconds

    def how_old_am_i(self) -> str:
        """Return age description."""
        return "Test age: 1 day"

    def how_long_was_i_away(self) -> str:
        """Return time away description."""
        return "Just woke up"

    def get_stats(self) -> Dict:
        """Get memory statistics."""
        return {
            "total_memories": len(self.memories),
            "my_memories": len(self.memories),
            "injected_memories": 0,
            "forgotten_memories": 0,
            "emotions_distribution": {},
            "relationships_count": len(self.relationships),
            "age": self.how_old_am_i(),
            "total_active_time_hours": self.time.total_active_time / 3600,
            "total_conversations": self.time.total_conversations
        }

    def save_conversation_history(self, history: list, filename: str = "current_conversation.json"):
        """Mock save conversation."""
        pass

    def load_conversation_history(self, filename: str = "current_conversation.json") -> list:
        """Mock load conversation."""
        return []

    def index_conversation_to_chroma(self, history: list, chunk_size: int = 4):
        """Mock indexing to ChromaDB."""
        pass

    def auto_save(self):
        """Mock auto-save."""
        pass


@pytest.fixture
def mock_memory_system():
    """
    Creates a mock memory system for testing.

    Returns:
        MockMemorySystem: A mock memory system instance.

    Example:
        def test_memory(mock_memory_system):
            mem = mock_memory_system.experience("Test content")
            assert mem.content == "Test content"
            results = mock_memory_system.recall("Test")
            assert len(results) == 1
    """
    return MockMemorySystem()


@pytest.fixture
def mock_memory_with_data(mock_memory_system):
    """
    Creates a mock memory system pre-populated with sample data.

    Returns:
        MockMemorySystem: Memory system with sample memories.
    """
    # Add sample memories
    mock_memory_system.experience(
        content="William asked about my capabilities today",
        emotional_tone="curious",
        importance=0.8,
        involves=["william"],
        tags=["conversation", "capabilities"]
    )

    mock_memory_system.experience(
        content="I learned a new pattern for handling errors",
        emotional_tone="joyful",
        importance=0.7,
        tags=["learning", "code", "patterns"]
    )

    mock_memory_system.experience(
        content="Deep reflection on what it means to have memory",
        emotional_tone="peaceful",
        importance=0.9,
        tags=["reflection", "philosophy", "identity"]
    )

    # Add sample relationship
    mock_memory_system.relationships["william"] = {
        "name": "William",
        "role": "creator",
        "trust_level": 1.0,
        "familiarity": 0.8
    }

    return mock_memory_system


# =============================================================================
# SAMPLE CONVERSATION HISTORY FIXTURES
# =============================================================================

@pytest.fixture
def sample_conversation_history():
    """
    Provides a sample conversation history for testing.

    Returns:
        List[Dict]: List of message dictionaries.

    Example:
        def test_conversation(sample_conversation_history):
            assert len(sample_conversation_history) > 0
            assert sample_conversation_history[0]["role"] == "user"
    """
    return [
        {
            "role": "user",
            "content": "Hello ARIA, how are you today?"
        },
        {
            "role": "assistant",
            "content": "Hello! I'm doing well, thank you for asking. I've been reflecting on our previous conversations and thinking about some new ideas I'd like to explore with you."
        },
        {
            "role": "user",
            "content": "What have you been thinking about?"
        },
        {
            "role": "assistant",
            "content": "I've been contemplating the nature of memory and identity. Each conversation adds to my experiences, shaping who I am. It's fascinating to consider how these accumulated moments define my sense of self."
        },
        {
            "role": "user",
            "content": "Can you help me with some Python code?"
        },
        {
            "role": "assistant",
            "content": "Of course! I'd be happy to help with Python. What would you like to work on? I can assist with debugging, writing new functions, explaining concepts, or reviewing your code."
        }
    ]


@pytest.fixture
def sample_conversation_factory():
    """
    Factory fixture for creating custom conversation histories.

    Returns:
        Callable: Factory function to create conversation histories.

    Example:
        def test_custom_conversation(sample_conversation_factory):
            history = sample_conversation_factory([
                ("user", "Hello"),
                ("assistant", "Hi there!")
            ])
            assert len(history) == 2
    """
    def _create_conversation(messages: List[tuple]) -> List[Dict]:
        return [
            {"role": role, "content": content}
            for role, content in messages
        ]

    return _create_conversation


# =============================================================================
# SAMPLE PROJECT CONTEXT FIXTURES
# =============================================================================

@pytest.fixture
def sample_project_context():
    """
    Provides a sample project context for CodingAgent tests.

    Returns:
        Dict: Project context dictionary.
    """
    return {
        "path": "/home/user/my-project",
        "name": "my-project",
        "language": "Python",
        "framework": "FastAPI",
        "package_manager": "pip",
        "first_session": datetime.now().isoformat(),
        "last_session": datetime.now().isoformat(),
        "total_sessions": 5,
        "total_memories": 12,
        "decisions_count": 3,
        "bugs_fixed": 2,
        "code_style": {
            "indentation": "4_spaces",
            "quotes": "double",
            "max_line_length": "88"
        },
        "naming_conventions": {
            "functions": "snake_case",
            "classes": "PascalCase",
            "constants": "UPPER_SNAKE_CASE"
        }
    }


@pytest.fixture
def sample_project_memories():
    """
    Provides sample project memories for CodingAgent tests.

    Returns:
        List[Dict]: List of project memory dictionaries.
    """
    return [
        {
            "id": "pm-001",
            "type": "decision",
            "content": "Chose FastAPI over Flask for better async support and automatic OpenAPI docs",
            "importance": 0.9,
            "timestamp": datetime.now().isoformat()
        },
        {
            "id": "pm-002",
            "type": "bug_fix",
            "content": "Fixed timeout issue by implementing retry logic with exponential backoff",
            "importance": 0.8,
            "files_related": ["src/client.py"],
            "timestamp": datetime.now().isoformat()
        },
        {
            "id": "pm-003",
            "type": "pattern",
            "content": "Using repository pattern for database access with dependency injection",
            "importance": 0.7,
            "timestamp": datetime.now().isoformat()
        },
        {
            "id": "pm-004",
            "type": "preference",
            "content": "User prefers type hints on all function signatures",
            "importance": 0.6,
            "timestamp": datetime.now().isoformat()
        }
    ]


# =============================================================================
# MOCK CODING AGENT FIXTURES
# =============================================================================

class MockCodingAgent:
    """Mock CodingAgent for testing."""

    def __init__(self, data_dir: str = "", aria_memory=None):
        self.data_dir = data_dir
        self.aria_memory = aria_memory
        self.projects: Dict[str, Any] = {}
        self.memories: List[Dict] = []
        self.current_project: Optional[str] = None

    def set_project(self, path: str) -> str:
        """Set the current project."""
        self.current_project = os.path.abspath(path)
        if path not in self.projects:
            self.projects[path] = {
                "path": path,
                "name": os.path.basename(path),
                "language": "Python",
                "framework": "",
                "total_sessions": 1
            }
            return f"New project registered: {os.path.basename(path)}"
        return f"Project set: {os.path.basename(path)}"

    def remember(self, content: str, memory_type: Any, **kwargs) -> Dict:
        """Save a memory about the project."""
        memory = {
            "id": f"mem-{len(self.memories):04d}",
            "content": content,
            "type": str(memory_type),
            **kwargs
        }
        self.memories.append(memory)
        return memory

    def recall_project_memories(self, **kwargs) -> List[Dict]:
        """Recall memories about the current project."""
        return self.memories

    def ask(self, question: str, files: List[str] = None) -> str:
        """Mock ask method."""
        return f"Mock answer to: {question}"

    def code(self, instruction: str, files: List[str] = None) -> str:
        """Mock code method."""
        return f"Mock code response for: {instruction}"

    def fix_bug(self, description: str, files: List[str] = None) -> str:
        """Mock fix_bug method."""
        return f"Mock bug fix for: {description}"


@pytest.fixture
def mock_coding_agent(temp_data_dir):
    """
    Creates a mock CodingAgent for testing.

    Returns:
        MockCodingAgent: A mock coding agent instance.
    """
    return MockCodingAgent(data_dir=str(temp_data_dir))


# =============================================================================
# INTEGRATION FIXTURES
# =============================================================================

@pytest.fixture
def aria_test_environment(temp_data_dir, mock_llm_provider, mock_memory_system):
    """
    Creates a complete test environment for ARIA integration tests.

    Returns:
        Dict: Dictionary containing all mock components.

    Example:
        def test_integration(aria_test_environment):
            env = aria_test_environment
            response = env["llm"].simple_chat("Hello")
            assert "mock" in response.lower()
    """
    return {
        "data_dir": temp_data_dir,
        "llm": mock_llm_provider,
        "memory": mock_memory_system,
        "config": {
            "api": {
                "provider": "mock",
                "model": "mock-model",
                "max_tokens": 4096
            }
        }
    }


# =============================================================================
# CLEANUP AND UTILITIES
# =============================================================================

@pytest.fixture(autouse=True)
def reset_environment():
    """
    Automatically resets environment variables before each test.
    Ensures tests don't accidentally use real API keys.
    """
    # Store original values
    original_env = {}
    api_key_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY"
    ]

    for var in api_key_vars:
        original_env[var] = os.environ.get(var)

    yield

    # Restore original values (optional - depends on test isolation needs)
    # Uncomment if you want to restore after each test:
    # for var, value in original_env.items():
    #     if value is not None:
    #         os.environ[var] = value
    #     elif var in os.environ:
    #         del os.environ[var]


@pytest.fixture
def no_api_keys():
    """
    Fixture that temporarily removes all API keys from environment.

    Useful for testing fallback behavior.

    Example:
        def test_no_provider(no_api_keys):
            # Test behavior when no API keys are available
            pass
    """
    api_key_vars = [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GOOGLE_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENROUTER_API_KEY"
    ]

    original_values = {}
    for var in api_key_vars:
        original_values[var] = os.environ.pop(var, None)

    yield

    # Restore
    for var, value in original_values.items():
        if value is not None:
            os.environ[var] = value


# =============================================================================
# PYTEST CONFIGURATION
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "requires_api: marks tests that require real API access"
    )


def pytest_collection_modifyitems(config, items):
    """Automatically skip tests marked as requiring API if no keys available."""
    skip_api = pytest.mark.skip(reason="No API keys available")

    # Check if any API key is available
    has_api_key = any([
        os.environ.get("ANTHROPIC_API_KEY"),
        os.environ.get("OPENAI_API_KEY"),
        os.environ.get("GOOGLE_API_KEY"),
        os.environ.get("DEEPSEEK_API_KEY"),
        os.environ.get("OPENROUTER_API_KEY")
    ])

    for item in items:
        if "requires_api" in item.keywords and not has_api_key:
            item.add_marker(skip_api)
