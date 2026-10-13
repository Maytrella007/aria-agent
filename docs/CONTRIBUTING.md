# Contributing to ARIA

## Getting Started

```bash
git clone https://github.com/Maytrella007/aria-agent.git
cd aria-agent
pip install -r requirements.txt
```

## Running Tests

```bash
# Full unit test suite (794 tests)
python -m pytest tests/ -v

# Specific module
python -m pytest tests/test_memory.py -v
python -m pytest tests/test_tools.py -v
python -m pytest tests/test_skills.py -v

# Live integration tests (requires DEEPSEEK_API_KEY)
DEEPSEEK_API_KEY=sk-xxx python -m pytest tests/test_skills_live_deepseek.py -v
```

All tests must pass before submitting a PR.

## Project Structure

```
ARIA/
├── aria.py                 # Entry point
├── core/
│   ├── llm/                # LLM providers, agent loop, prompt builder
│   ├── memory/             # Experiential memory, entities, facts
│   ├── cognition/          # Reflection, introspection, evolution
│   ├── autonomy/           # Curiosity, initiative, autonomous tasks
│   ├── neuroscience/       # Consolidation, DMN, metacognition
│   ├── infra/              # Event bus, auth, security, continuity
│   ├── channels/           # Telegram, Discord, Slack, terminal
│   ├── interaction/        # Commands, perception, sessions
│   ├── api/                # FastAPI server
│   ├── tools/              # 39+ tool implementations
│   └── skills/             # 25 skills (19 Python + 5 YAML + inline)
├── tests/                  # Test suite
├── scripts/                # Utilities
├── docs/                   # Documentation
└── data/                   # Runtime state (not committed)
```

## Adding a New Tool

1. Create `core/tools/my_tool.py`:

```python
from core.tools.tool_base import ToolBase, ToolParam, ToolResult

class MyTool(ToolBase):
    name = "my_tool"
    description = "Short description of what the tool does"
    parameters = [
        ToolParam(name="action", type="string", description="Action to perform",
                  required=True, enum=["do_thing", "do_other"]),
        ToolParam(name="input", type="string", description="Input data"),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs.get("action")
        if action == "do_thing":
            return ToolResult(success=True, data={"result": "done"})
        return ToolResult(success=False, error="Unknown action")
```

2. Add the name constant to `core/tools/tool_names.py`:

```python
class Tools(str, Enum):
    MY_TOOL = "my_tool"
```

3. Export the tool in `core/tools/__init__.py`, add its constant in `core/tools/tool_names.py`, and register it in `aria.py`.

4. Add tests in `tests/test_tools.py` or a new test file.

## Adding a New Skill

1. Create `core/skills/my_skill.py`:

```python
from core.skills.base import SkillBase, SkillResult
from core.tools.tool_names import Tools

class MySkill(SkillBase):
    name = "my_skill"
    description = "What this skill does"
    requires_tools = [Tools.MY_TOOL]

    def _execute(self, query: str, ctx) -> SkillResult:
        result = ctx.tools.execute(Tools.MY_TOOL, action="do_thing", input=query)
        if not result.success:
            return SkillResult(success=False, error=result.error)
        return SkillResult(
            success=True,
            output="Done!",
            data=result.data
        )
```

2. Export the skill in `core/skills/__init__.py`, register it in `aria.py`, and add tests in `tests/test_skills.py` or a new file.

## Adding a New LLM Provider

1. Subclass `BaseLLMProvider` in `core/llm/llm_providers.py`
2. Implement `_initialize()`, `chat()`, and optionally `stream_chat()`
3. Add detection logic in `LLMProvider.from_env()`
4. Add env var to `AuthManager`

## Code Style

- Python 3.10+
- Type hints on public methods
- Docstrings on classes (not every method)
- Keep tools and skills focused — one responsibility each
- Use `ToolResult` and `SkillResult` for all return values
- Test with mocks for unit tests; use `test_skills_live_deepseek.py` for live DeepSeek-based integration coverage

## Security Considerations

- Never use `shell=True` in subprocess calls
- Sanitize all user input passed to shell commands
- Block private IPs in web fetch (SSRF protection)
- Use AST validation for calculator expressions
- Prevent path traversal in file/compress operations
- Mark external data as untrusted in prompts
