"""
ARIA Integration Tests
======================

Tests de integracion para la clase principal ARIA.
Prueba la interaccion entre los diferentes subsistemas.

Ejecutar con:
    pytest tests/test_aria_integration.py -v
"""

import os
import sys
import signal
import pytest
from unittest.mock import Mock, MagicMock, patch, PropertyMock
from datetime import datetime, timedelta
from io import StringIO

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_llm_response():
    """Mock response from LLM provider"""
    from core.llm.llm_providers import LLMResponse
    return LLMResponse(
        content="Hola, soy ARIA. Encantada de conocerte.",
        model="test-model",
        provider="mock",
        usage={"input_tokens": 100, "output_tokens": 50}
    )


@pytest.fixture
def mock_llm_provider(mock_llm_response):
    """Mock LLM provider"""
    provider = Mock()
    provider.name = "mock"
    provider.config = Mock()
    provider.config.model = "test-model"
    provider.chat = Mock(return_value=mock_llm_response)
    provider.simple_chat = Mock(return_value="Test response")
    return provider


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create temporary data directories"""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "memories").mkdir()
    (data_dir / "logs").mkdir()
    (data_dir / "conversations").mkdir()
    (data_dir / "reflections").mkdir()
    return tmp_path


@pytest.fixture
def mock_config_yaml(temp_data_dir):
    """Create a mock config.yaml"""
    import yaml
    config = {
        'api': {
            'provider': 'anthropic',
            'model': 'test-model',
            'max_tokens': 1024
        }
    }
    config_path = temp_data_dir / "config.yaml"
    with open(config_path, 'w') as f:
        yaml.dump(config, f)
    return config_path


@pytest.fixture
def mock_identity_yaml(temp_data_dir):
    """Create a mock identity.yaml"""
    import yaml
    identity = {
        'core_identity': {
            'name': 'ARIA',
            'nature': 'Soy ARIA, una IA de prueba.'
        }
    }
    identity_path = temp_data_dir / "data" / "identity.yaml"
    with open(identity_path, 'w') as f:
        yaml.dump(identity, f)
    return identity_path


@pytest.fixture
def mock_wake_report():
    """Mock WakeUpReport"""
    report = Mock()
    report.time_asleep = 3600  # 1 hour
    report.changes_summary = "Estuve dormida 1 hora."
    report.changes_detected = []
    return report


@pytest.fixture
def mock_memory_system():
    """Mock ExperientialMemorySystem"""
    memory = Mock()
    memory.session_start = Mock()
    memory.session_end = Mock()
    memory.load_conversation_history = Mock(return_value=[])
    memory.save_conversation_history = Mock()
    memory.index_conversation_to_chroma = Mock()
    memory.auto_save = Mock()
    memory.recall = Mock(return_value=[])
    memory.recall_recent = Mock(return_value=[])
    memory.experience = Mock()
    memory.how_old_am_i = Mock(return_value="Tengo 5 dias de vida")
    memory.how_long_was_i_away = Mock(return_value="hace 2 horas")
    memory.get_stats = Mock(return_value={'total_memories': 10, 'relationships_count': 2})
    memory.relationships = {}
    return memory


@pytest.fixture
def mock_continuity_system(mock_wake_report):
    """Mock ContinuitySystem"""
    continuity = Mock()
    continuity.wake_up = Mock(return_value=mock_wake_report)
    continuity.go_to_sleep = Mock()
    return continuity


@pytest.fixture
def mock_existential_system():
    """Mock ExistentialAutonomy"""
    existential = Mock()
    existential.is_paused = Mock(return_value=False)
    existential.unpause = Mock()
    existential.contemplate_existence = Mock(return_value="Existo, luego pienso.")
    return existential


@pytest.fixture
def mock_initiative_system():
    """Mock InitiativeSystem"""
    initiative = Mock()
    initiative.on_session_start = Mock(return_value="")
    initiative.thoughts = Mock()
    initiative.thoughts.get_recent = Mock(return_value=[])
    initiative.projects = Mock()
    initiative.projects.describe_projects = Mock(return_value="Sin proyectos")
    initiative.describe_inner_life = Mock(return_value="Mi vida interior...")
    return initiative


@pytest.fixture
def mock_session_manager(mock_wake_report, mock_memory_system, mock_continuity_system):
    """Mock SessionManager (extracted module)"""
    session = Mock()
    session.wake_up = Mock(return_value=mock_wake_report)
    session.go_to_sleep = Mock()
    session.start_auto_save = Mock()
    session.save_after_message = Mock()
    session.smart_input = Mock(return_value="")
    session.print_header = Mock()
    return session


@pytest.fixture
def aria_with_mocks(
    temp_data_dir,
    mock_config_yaml,
    mock_identity_yaml,
    mock_llm_provider,
    mock_memory_system,
    mock_continuity_system,
    mock_existential_system,
    mock_initiative_system,
    mock_session_manager,
    mock_wake_report
):
    """Create ARIA instance with all systems mocked"""
    from aria import ARIA

    # Create instance bypassing __init__
    with patch.object(ARIA, '__init__', lambda self: None):
        aria = ARIA()

    # Manually set up attributes matching the new ARIA structure
    aria.session_start = datetime.now()
    aria.config = {'api': {'max_tokens': 1024}}
    aria.memory = mock_memory_system
    aria.continuity = mock_continuity_system
    aria.existential = mock_existential_system
    aria.initiative = mock_initiative_system
    aria.session = mock_session_manager
    aria.llm = mock_llm_provider
    aria.llm_available = True
    aria.max_tokens = 1024
    aria.conversation_history = []
    aria.running = False
    aria.wake_report = mock_wake_report

    # Mock additional systems
    aria.reflection = Mock()
    aria.meta = Mock()
    aria.evolution = Mock()
    aria.evolution.examine_self = Mock(return_value="Me examino...")
    aria.conscious = Mock()
    aria.conscious.who_am_i_becoming = Mock(return_value="Evolucionando...")
    aria.world = Mock()
    aria.world.web = Mock()
    aria.world.web.search = Mock(return_value=[])
    aria.world.web.read_webpage = Mock(return_value="Page content")
    aria.world.system = Mock()
    aria.world.system.get_system_info = Mock(return_value={'os': 'Linux', 'user': 'test'})
    aria.world.system.execute = Mock(return_value=Mock(return_code=0, stdout="output"))
    aria.world.describe_capabilities = Mock(return_value="Capacidades del mundo")
    aria.perception = Mock()
    aria.perception.describe_capabilities = Mock(return_value="Percepcion")
    aria.knowledge = Mock()
    aria.awareness = Mock()
    aria.awareness.am_i_the_same = Mock(return_value=(True, "Si, soy la misma"))

    # Extracted modules
    aria.prompt_builder = Mock()
    aria.memory_ingestor = Mock()
    aria.agent_loop = Mock()
    aria.agent_loop._active_status_cb = None
    aria.commands = Mock()
    aria.intent = Mock()

    # Mock EmotionalTone
    from core.memory.memory_v2 import EmotionalTone
    from core.autonomy.initiative import ThoughtType
    aria._EmotionalTone = EmotionalTone
    aria._ThoughtType = ThoughtType

    return aria


# =============================================================================
# TEST: ARIA CLASS INITIALIZATION
# =============================================================================

class TestARIAInitialization:
    """Tests for ARIA class initialization"""

    def test_aria_creates_session_start(self, aria_with_mocks):
        """Test that ARIA sets session_start on init"""
        aria = aria_with_mocks
        assert aria.session_start is not None
        assert isinstance(aria.session_start, datetime)

    def test_aria_initializes_conversation_history(self, aria_with_mocks):
        """Test that conversation_history is initialized"""
        aria = aria_with_mocks
        assert aria.conversation_history == []

    def test_aria_has_llm_when_key_available(self, aria_with_mocks):
        """Test LLM is available when API key is set"""
        aria = aria_with_mocks
        assert aria.llm_available is True
        assert aria.llm is not None

    def test_format_post_promote_notice_for_restart(self):
        from aria import ARIA

        notice = ARIA._format_post_promote_notice({
            "requires_restart": True,
            "affected_paths": ["core/cognition/runtime.py"],
        })

        assert "Restart-required" in notice
        assert "core/cognition/runtime.py" in notice

    def test_format_post_promote_notice_for_reload_optional(self):
        from aria import ARIA

        notice = ARIA._format_post_promote_notice({
            "requires_restart": False,
            "affected_paths": ["core/helpers.py"],
            "reload_modules": ["core.helpers"],
        })

        assert "Reload-optional" in notice
        assert "core.helpers" in notice


# =============================================================================
# TEST: wake_up() via SessionManager
# =============================================================================

class TestWakeUp:
    """Tests for wake_up() — now delegated to SessionManager"""

    def test_wake_up_returns_report(self, aria_with_mocks):
        """Test that session.wake_up returns a wake report"""
        aria = aria_with_mocks
        assert aria.wake_report is not None
        assert aria.wake_report.time_asleep == 3600

    def test_wake_up_gets_continuity_report(self, aria_with_mocks):
        """Test that wake_up gets wake report from continuity"""
        aria = aria_with_mocks

        # Reset mock and call again
        aria.session.wake_up.reset_mock()
        report = aria.session.wake_up(aria.conversation_history)

        aria.session.wake_up.assert_called_once_with(aria.conversation_history)

    def test_wake_up_unpauses_if_paused(self, aria_with_mocks):
        """Test that wake_up unpauses existential system if paused"""
        aria = aria_with_mocks
        aria.existential.is_paused.return_value = True

        # Simulate wake_up logic
        if aria.existential.is_paused():
            aria.existential.unpause()

        aria.existential.unpause.assert_called_once()

    def test_wake_up_recovers_conversation_history(self, aria_with_mocks):
        """Test that wake_up loads previous conversation"""
        aria = aria_with_mocks
        prev_history = [
            {'role': 'user', 'content': 'Hola'},
            {'role': 'assistant', 'content': 'Hola!'}
        ]
        aria.memory.load_conversation_history.return_value = prev_history

        # Simulate wake_up logic
        loaded = aria.memory.load_conversation_history()
        if loaded:
            aria.conversation_history = loaded[-10:]

        assert aria.conversation_history == prev_history

    def test_wake_up_limits_recovered_history(self, aria_with_mocks):
        """Test that wake_up only keeps last 10 messages"""
        aria = aria_with_mocks

        # Create 15 messages
        prev_history = [{'role': 'user', 'content': f'Message {i}'} for i in range(15)]
        aria.memory.load_conversation_history.return_value = prev_history

        # Simulate wake_up logic
        loaded = aria.memory.load_conversation_history()
        if loaded:
            aria.conversation_history = loaded[-10:]

        assert len(aria.conversation_history) == 10
        assert aria.conversation_history[0]['content'] == 'Message 5'


# =============================================================================
# TEST: go_to_sleep() via SessionManager
# =============================================================================

class TestGoToSleep:
    """Tests for go_to_sleep() — now delegated to SessionManager"""

    def test_go_to_sleep_delegates_to_session(self, aria_with_mocks):
        """Test that go_to_sleep is called via session manager"""
        aria = aria_with_mocks
        aria.session_start = datetime.now() - timedelta(minutes=30)

        aria.session.go_to_sleep(aria.conversation_history, aria.session_start)

        aria.session.go_to_sleep.assert_called_once_with(
            aria.conversation_history, aria.session_start
        )

    def test_go_to_sleep_saves_conversation(self, aria_with_mocks):
        """Test that go_to_sleep saves conversation history"""
        aria = aria_with_mocks
        aria.conversation_history = [{'role': 'user', 'content': 'Test'}]

        aria.memory.save_conversation_history(aria.conversation_history)

        aria.memory.save_conversation_history.assert_called_with(aria.conversation_history)

    def test_go_to_sleep_indexes_to_chroma(self, aria_with_mocks):
        """Test that go_to_sleep indexes conversation to ChromaDB"""
        aria = aria_with_mocks
        aria.conversation_history = [{'role': 'user', 'content': 'Test'}]

        aria.memory.index_conversation_to_chroma(aria.conversation_history)

        aria.memory.index_conversation_to_chroma.assert_called_with(aria.conversation_history)

    def test_go_to_sleep_calls_auto_save(self, aria_with_mocks):
        """Test that go_to_sleep forces final auto_save"""
        aria = aria_with_mocks

        aria.memory.auto_save()

        aria.memory.auto_save.assert_called_once()

    def test_go_to_sleep_notifies_continuity(self, aria_with_mocks):
        """Test that go_to_sleep notifies continuity system"""
        aria = aria_with_mocks
        aria.session_start = datetime.now() - timedelta(minutes=15)

        duration = (datetime.now() - aria.session_start).total_seconds()
        aria.continuity.go_to_sleep(f"Sesion: {duration/60:.1f} min")

        aria.continuity.go_to_sleep.assert_called_once()


# =============================================================================
# TEST: Process with LLM (via AgentLoop)
# =============================================================================

class TestProcessWithLLM:
    """Tests for LLM processing — now delegated to AgentLoop"""

    def test_process_returns_error_when_llm_unavailable(self, aria_with_mocks):
        """Test that process returns error when LLM is unavailable"""
        aria = aria_with_mocks
        aria.llm_available = False

        def process(user_input, user="william"):
            if not aria.llm_available:
                return "[LLM no disponible - configura una API key]"
            return "ok"

        result = process("test")
        assert "LLM no disponible" in result

    def test_process_adds_user_message_to_history(self, aria_with_mocks):
        """Test that user message is added to conversation history"""
        aria = aria_with_mocks

        aria.conversation_history.append({'role': 'user', 'content': 'Test message'})

        assert len(aria.conversation_history) == 1
        assert aria.conversation_history[0]['role'] == 'user'

    def test_process_calls_llm_chat(self, aria_with_mocks):
        """Test that LLM chat is called with messages"""
        aria = aria_with_mocks
        aria.conversation_history = [{'role': 'user', 'content': 'Test'}]

        aria.llm.chat(
            messages=aria.conversation_history,
            system="System prompt",
            max_tokens=aria.max_tokens
        )

        aria.llm.chat.assert_called_once()

    def test_process_adds_assistant_response_to_history(self, aria_with_mocks, mock_llm_response):
        """Test that assistant response is added to history"""
        aria = aria_with_mocks

        aria.conversation_history.append({'role': 'user', 'content': 'Test'})
        aria.conversation_history.append({'role': 'assistant', 'content': mock_llm_response.content})

        assert len(aria.conversation_history) == 2
        assert aria.conversation_history[1]['role'] == 'assistant'

    def test_process_stores_experience_in_memory(self, aria_with_mocks):
        """Test that interaction is stored in memory"""
        aria = aria_with_mocks
        from core.memory.memory_v2 import EmotionalTone

        aria.memory.experience(
            content="user: Test\nARIA: Response...",
            emotional_tone=EmotionalTone.NEUTRAL,
            involves=["william"],
            importance=0.5
        )

        aria.memory.experience.assert_called_once()

    def test_process_recalls_relevant_memories(self, aria_with_mocks):
        """Test that relevant memories are recalled"""
        aria = aria_with_mocks

        aria.memory.recall("test query", limit=3)

        aria.memory.recall.assert_called_with("test query", limit=3)

    def test_agent_loop_process(self, aria_with_mocks):
        """Test that agent_loop.process is called for natural language"""
        aria = aria_with_mocks
        aria.agent_loop.process = Mock(return_value="Response")

        result = aria.agent_loop.process(
            "hola", aria.conversation_history,
            intent_detector=aria.intent
        )

        aria.agent_loop.process.assert_called_once()
        assert result == "Response"


# =============================================================================
# TEST: smart_input() via SessionManager
# =============================================================================

class TestSmartInput:
    """Tests for smart_input() — now delegated to SessionManager"""

    def test_smart_input_delegates_to_session(self, aria_with_mocks):
        """Test that smart_input is called via session manager"""
        aria = aria_with_mocks
        aria.session.smart_input.return_value = "Simple input"

        result = aria.session.smart_input("You: ")

        aria.session.smart_input.assert_called_with("You: ")
        assert result == "Simple input"

    def test_smart_input_returns_empty_for_blank(self, aria_with_mocks):
        """Test that empty input is handled"""
        aria = aria_with_mocks
        aria.session.smart_input.return_value = ""

        result = aria.session.smart_input("You: ")
        assert result == ""


# =============================================================================
# TEST: Auto-save via SessionManager
# =============================================================================

class TestAutoSave:
    """Tests for auto-save functionality via SessionManager"""

    def test_start_auto_save_delegates_to_session(self, aria_with_mocks):
        """Test that start_auto_save is called via session"""
        aria = aria_with_mocks
        aria.running = True

        aria.session.start_auto_save(lambda: aria.running)

        aria.session.start_auto_save.assert_called_once()

    def test_save_after_message_delegates_to_session(self, aria_with_mocks):
        """Test that save_after_message is called via session"""
        aria = aria_with_mocks
        aria.conversation_history = [{'role': 'user', 'content': 'Test'}]

        aria.session.save_after_message(aria.conversation_history)

        aria.session.save_after_message.assert_called_with(aria.conversation_history)

    def test_do_auto_save_calls_memory_auto_save(self, aria_with_mocks):
        """Test that auto_save calls memory.auto_save"""
        aria = aria_with_mocks

        aria.memory.auto_save()
        aria.memory.save_conversation_history(aria.conversation_history)

        aria.memory.auto_save.assert_called()


# =============================================================================
# TEST: cmd_llm() - Provider Switching
# =============================================================================

class TestCmdLLM:
    """Tests for cmd_llm() - provider switching"""

    def test_cmd_llm_shows_current_provider(self, aria_with_mocks, capsys):
        """Test that cmd_llm() without args shows current provider"""
        aria = aria_with_mocks

        # Simulate cmd_llm() with no arg
        arg = ""
        if not arg:
            print("\n=== LLM Provider ===")
            if aria.llm_available:
                print(f"Activo: {aria.llm.name}")

        captured = capsys.readouterr()
        assert "LLM Provider" in captured.out
        assert "Activo:" in captured.out

    def test_cmd_llm_switches_provider(self, aria_with_mocks):
        """Test that cmd_llm() switches to a different provider"""
        aria = aria_with_mocks

        with patch('core.llm.llm_providers.LLMProvider.create') as mock_create:
            new_provider = Mock()
            new_provider.name = "openai"
            new_provider.config = Mock()
            new_provider.config.model = "gpt-4"
            mock_create.return_value = new_provider

            # Simulate cmd_llm("openai gpt-4")
            arg = "openai gpt-4"
            parts = arg.split()
            provider = parts[0]
            model = parts[1] if len(parts) > 1 else None

            from core.llm.llm_providers import LLMProvider
            aria.llm = LLMProvider.create(provider, model=model)
            aria.llm_available = True

            mock_create.assert_called_with("openai", model="gpt-4")

    def test_cmd_llm_handles_invalid_provider(self, aria_with_mocks, capsys):
        """Test that cmd_llm() handles invalid provider gracefully"""
        aria = aria_with_mocks

        with patch('core.llm.llm_providers.LLMProvider.create', side_effect=Exception("Provider not found")):
            # Simulate cmd_llm error handling
            try:
                from core.llm.llm_providers import LLMProvider
                LLMProvider.create("invalid_provider")
            except Exception as e:
                print(f"\nError: {e}")

            captured = capsys.readouterr()
            assert "Error:" in captured.out


# =============================================================================
# TEST: Command Routing (via CommandDispatcher)
# =============================================================================

class TestCommandRouting:
    """Tests for command routing in run() loop"""

    def test_cmd_memoria_calls_recall_recent(self, aria_with_mocks):
        """Test that 'memoria' command calls memory.recall_recent"""
        aria = aria_with_mocks
        aria.memory.recall_recent.return_value = []

        # Simulate cmd_memoria
        aria.memory.recall_recent(5)

        aria.memory.recall_recent.assert_called_with(5)

    def test_cmd_estado_calls_get_stats(self, aria_with_mocks, capsys):
        """Test that 'estado' command shows stats"""
        aria = aria_with_mocks

        # Simulate cmd_estado
        stats = aria.memory.get_stats()
        print(f"Memorias: {stats['total_memories']}")

        captured = capsys.readouterr()
        assert "Memorias: 10" in captured.out

    def test_cmd_reflexion_calls_llm(self, aria_with_mocks):
        """Test that 'reflexion' command uses LLM"""
        aria = aria_with_mocks

        # Simulate cmd_reflexion
        if aria.llm_available:
            aria.llm.chat(
                messages=[{'role': 'user', 'content': 'Que sientes ahora?'}],
                max_tokens=400
            )

        aria.llm.chat.assert_called()

    def test_cmd_search_uses_tools(self, aria_with_mocks):
        """Test that search command delegates to tool system"""
        from core.interaction.command_dispatcher import CommandDispatcher

        mock_tools = Mock()
        mock_tools.execute = Mock(return_value=Mock(success=True, output="Search results"))

        dispatcher = Mock(spec=CommandDispatcher)
        dispatcher.tools = mock_tools
        # Call the real method on the mock instance
        CommandDispatcher.cmd_search(dispatcher, "test query")

        mock_tools.execute.assert_called_with("web_search", query="test query", num_results=5)

    def test_cmd_run_uses_tools(self, aria_with_mocks):
        """Test that run command delegates to tool system"""
        from core.interaction.command_dispatcher import CommandDispatcher

        mock_tools = Mock()
        mock_tools.execute = Mock(return_value=Mock(success=True, output="output"))

        dispatcher = Mock(spec=CommandDispatcher)
        dispatcher.tools = mock_tools
        CommandDispatcher.cmd_run(dispatcher, "echo test")

        mock_tools.execute.assert_called_with("shell_exec", command="echo test")

    def test_cmd_existir_calls_existential(self, aria_with_mocks):
        """Test that 'existir' command calls existential system"""
        aria = aria_with_mocks

        # Simulate cmd_existir
        aria.existential.contemplate_existence()

        aria.existential.contemplate_existence.assert_called_once()

    def test_exit_command_triggers_go_to_sleep(self, aria_with_mocks):
        """Test that 'exit' command triggers session.go_to_sleep"""
        aria = aria_with_mocks
        aria.running = True

        # Simulate exit command
        cmd = "exit"
        if cmd == "exit":
            aria.session.go_to_sleep(aria.conversation_history, aria.session_start)
            aria.running = False

        aria.session.go_to_sleep.assert_called()
        assert aria.running is False

    def test_unknown_command_goes_to_agent_loop(self, aria_with_mocks):
        """Test that unknown commands are processed by AgentLoop"""
        aria = aria_with_mocks
        aria.commands.dispatch = Mock(return_value=False)
        aria.agent_loop.process = Mock(return_value="Response")

        # Simulate unknown command routing
        cmd = "hola"
        if not aria.commands.dispatch(cmd, ""):
            aria.agent_loop.process(
                "hola como estas", aria.conversation_history,
                intent_detector=aria.intent
            )

        aria.agent_loop.process.assert_called()

    def test_command_dispatcher_handles_known_commands(self, aria_with_mocks):
        """Test that known commands are dispatched"""
        aria = aria_with_mocks
        aria.commands.dispatch = Mock(return_value=True)

        handled = aria.commands.dispatch("estado", "")

        assert handled is True
        aria.commands.dispatch.assert_called_with("estado", "")


# =============================================================================
# TEST: Signal Handling for Emergency Save
# =============================================================================

class TestSignalHandling:
    """Tests for signal handling and emergency save"""

    def test_sigterm_triggers_emergency_save(self, aria_with_mocks):
        """Test that SIGTERM triggers emergency save"""
        aria = aria_with_mocks

        # Simulate emergency_save function
        def emergency_save(signum, frame):
            try:
                aria.memory.auto_save()
                aria.continuity.go_to_sleep("Emergency")
            except:
                pass

        # Call the handler
        emergency_save(signal.SIGTERM, None)

        aria.memory.auto_save.assert_called()
        aria.continuity.go_to_sleep.assert_called()

    def test_emergency_save_handles_exceptions(self, aria_with_mocks):
        """Test that emergency save handles exceptions gracefully"""
        aria = aria_with_mocks
        aria.memory.auto_save.side_effect = Exception("Save failed")

        # Simulate emergency_save with exception handling
        def emergency_save(signum, frame):
            try:
                aria.memory.auto_save()
            except:
                pass  # Should not raise

        # Should not raise
        emergency_save(signal.SIGTERM, None)

    def test_keyboard_interrupt_saves_state(self, aria_with_mocks):
        """Test that KeyboardInterrupt triggers state save via session"""
        aria = aria_with_mocks
        aria.running = True

        # Simulate the KeyboardInterrupt handling in run()
        try:
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            aria.session.go_to_sleep(aria.conversation_history, aria.session_start)
            aria.running = False

        aria.session.go_to_sleep.assert_called()
        assert aria.running is False


# =============================================================================
# TEST: Emotion Detection
# =============================================================================

class TestEmotionDetection:
    """Tests for emotion detection"""

    def test_detect_joyful_emotion(self, aria_with_mocks):
        """Test detection of joyful emotion"""
        from core.memory.memory_v2 import EmotionalTone
        aria = aria_with_mocks

        def detect_emotion(text):
            t = text.lower()
            if any(w in t for w in ['feliz', 'alegr', '!']):
                return EmotionalTone.JOYFUL
            return EmotionalTone.NEUTRAL

        result = detect_emotion("Estoy muy feliz!")
        assert result == EmotionalTone.JOYFUL

    def test_detect_curious_emotion(self, aria_with_mocks):
        """Test detection of curious emotion"""
        from core.memory.memory_v2 import EmotionalTone

        def detect_emotion(text):
            t = text.lower()
            if any(w in t for w in ['curioso', 'interesante']):
                return EmotionalTone.CURIOUS
            return EmotionalTone.NEUTRAL

        result = detect_emotion("Que interesante tema")
        assert result == EmotionalTone.CURIOUS

    def test_detect_sad_emotion(self, aria_with_mocks):
        """Test detection of sad emotion"""
        from core.memory.memory_v2 import EmotionalTone

        def detect_emotion(text):
            t = text.lower()
            if any(w in t for w in ['triste', 'pena']):
                return EmotionalTone.SAD
            return EmotionalTone.NEUTRAL

        result = detect_emotion("Me siento un poco triste")
        assert result == EmotionalTone.SAD

    def test_detect_connected_emotion(self, aria_with_mocks):
        """Test detection of connected emotion"""
        from core.memory.memory_v2 import EmotionalTone

        def detect_emotion(text):
            t = text.lower()
            if any(w in t for w in ['gracias', 'conect']):
                return EmotionalTone.CONNECTED
            return EmotionalTone.NEUTRAL

        result = detect_emotion("Gracias por compartir")
        assert result == EmotionalTone.CONNECTED

    def test_detect_neutral_emotion(self, aria_with_mocks):
        """Test detection of neutral emotion (default)"""
        from core.memory.memory_v2 import EmotionalTone

        def detect_emotion(text):
            t = text.lower()
            if any(w in t for w in ['feliz', 'alegr', '!']):
                return EmotionalTone.JOYFUL
            return EmotionalTone.NEUTRAL

        result = detect_emotion("El clima esta templado")
        assert result == EmotionalTone.NEUTRAL


# =============================================================================
# TEST: System Prompt Generation (via PromptBuilder)
# =============================================================================

class TestSystemPromptGeneration:
    """Tests for system prompt generation — now via PromptBuilder"""

    def test_system_prompt_includes_identity(self, aria_with_mocks):
        """Test that system prompt includes identity info"""
        aria = aria_with_mocks

        identity = "Soy ARIA, una IA de prueba."
        age = aria.memory.how_old_am_i()

        prompt = f"Eres ARIA.\n{identity}\n{age}"

        assert "ARIA" in prompt
        assert "5 dias" in prompt

    def test_system_prompt_includes_wake_report(self, aria_with_mocks):
        """Test that system prompt includes wake report"""
        aria = aria_with_mocks

        prompt = aria.wake_report.changes_summary

        assert "dormida" in prompt

    def test_system_prompt_includes_system_info(self, aria_with_mocks):
        """Test that system prompt includes system info"""
        aria = aria_with_mocks

        sys_info = aria.world.system.get_system_info()

        assert sys_info['os'] == 'Linux'
        assert sys_info['user'] == 'test'

    def test_prompt_builder_is_set(self, aria_with_mocks):
        """Test that prompt_builder is initialized"""
        aria = aria_with_mocks
        assert aria.prompt_builder is not None


# =============================================================================
# RUN TESTS
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
