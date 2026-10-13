# ARIA

### Autonomous Reflective Intelligence Architecture

> *An AI agent with persistent memory, a background cognitive cycle, 39+ tools, 25 skills, MCP bridge, and a notebook-and-book self-modification system that lets it edit its own code under human curation.*

[![CI](https://github.com/Maytrella007/aria-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Maytrella007/aria-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Tools](https://img.shields.io/badge/tools-39+-orange)]()
[![Skills](https://img.shields.io/badge/skills-25-blue)]()
[![LLM Providers](https://img.shields.io/badge/providers-6-purple)]()
[![MCP](https://img.shields.io/badge/MCP-compatible-teal)]()

---

> 📝 **Read the writeup:** [*Six months later: what rotted in a self-modifying agent, and what didn't*](WRITEUP.md) — the longitudinal story behind this repo.

## Status

ARIA is a personal research project I built through early 2026 and set down in April — the [writeup](WRITEUP.md) is the longitudinal story of what happened when I came back to it six months later. What follows describes the system as it stands. The backend is mature: memory, cognitive cycle, tool/skill framework, MCP bridge, multi-agent orchestration, and the Mirror self-modification system all run today and are exercised by unit tests and real end-to-end scripts. The frontend is a functional SvelteKit 5 application with 6 pages: chat (SSE streaming), memories (search/filter/sort), mirror (approval queue with tier badges and diff review), channels (Telegram/Discord/Slack management), credentials (LLM providers, agents, OAuth services), and login (email OTP). Server-side auth with SQLite sessions, a BFF proxy to FastAPI, and a dark-mode design system are all implemented.

Most AI tools are stateless wrappers around an LLM. ARIA is an attempt at something closer to an agent with a memory, a cognitive cycle, and a bounded way to edit its own source code safely. This README describes what actually works, not what is aspirational.

---

## The Mirror: notebook-and-book self-modification

ARIA can modify its own code. That is dangerous, so it has to be done on rails. The rails are a model we call **notebook-and-book**:

- **`develop` is the notebook** — ARIA's private working space. Every change ARIA proposes lands here as an `improve/*` branch, gets merged into `develop`, and stays there forever. ARIA writes freely.
- **`main` + live files are the book** — The published, curated version. Only changes a human explicitly approves are cherry-picked from `develop` into `main` and copied back into the real source tree.
- **Reject is not delete.** When the human rejects a pending change, the commit stays in `develop` as memory. The YAML entry is just flipped to `status: rejected`. Nothing is destroyed.
- **Reopen is free.** Changing your mind is trivial: `reopen_change` puts a rejected entry back in the queue without replaying the work.
- **Promote is atomic and selective.** `promote_selected([ids])` cherry-picks only the approved commits from `develop` into `main`, validates the result, then mirrors `main` onto the live tree.
- **Conflicts become information.** If cherry-pick fails because another pending change depends on this one, git itself reports it and `preview_reject` surfaces the dependents to the human before they commit to a decision.

```
          ARIA writes freely                 Human curates
         ───────────────────               ───────────────────

 improve/fix-decay ──┐                    ┌── cherry-pick ──► main ──► live
 improve/new-skill ──┼──► develop ────────┤                           (real
 improve/refactor ──┘      (notebook)     └── reject (stays here)      files)
                                                                       │
                                                                       ▼
                                                                    the book
```

### Tier classification

Not every file is equally dangerous to edit. `core/cognition/mirror.py` classifies each file into one of three tiers via `TIER_RULES` and `classify_file_tier()`:

| Tier | Label | What | Examples |
|------|-------|------|----------|
| **1** | cosmetic | docs, tests, scripts, mockups — no runtime effect | `README.md`, `docs/`, `scripts/`, `tests/` |
| **2** | behavioral | runtime hot path — real program behavior | `aria.py`, `core/llm/`, `core/memory/`, `core/tools/`, most of `core/` |
| **3** | meta | the files that decide what is safe to modify — ARIA editing its own guardrails | `core/cognition/mirror.py`, `quality_gate.py`, `self_modification.py`, `modification_log.py`, `core/infra/security.py`, `core/infra/auth_manager.py` |

The plan is for the GUI to gradate the approval ceremony by tier: Tier 1 click-to-approve, Tier 2 requiring the filename typed to confirm, Tier 3 requiring the filename plus an "I have read the full diff" acknowledgment. Today the classifier is implemented and the GUI shows tier badges, a diff viewer, and a confirm dialog on reject; the per-tier ceremony gradation is not built yet.

### The self-modification queue

All of this sits behind `core/cognition/self_modification.py` (`SelfModifier`). The state of a change is a string in the YAML pending store:

```
validated_pending_approval  →  still in the queue, awaiting human
rejected                    →  human said no (commit stays in develop)
applied                     →  approved + cherry-picked + live synced
failed                      →  automatic validation (syntax/imports/tests) failed
```

Key operations:

- `list_pending_changes()` — only rows in `_QUEUE_STATUS = "validated_pending_approval"`
- `list_rejected_changes()` / `list_promoted_changes()` — audit views
- `preview_reject(mod_id)` — dry-run: warns about sibling changes on the same file and git-level dependents from `mirror.find_dependents_in_develop()`, without mutating state
- `reject_change(mod_id, reason)` — flips status, does not touch git
- `reopen_change(mod_id)` — returns a rejected entry to the queue
- `promote_selected([mod_ids])` — `mirror.cherry_pick_branches_to_main()` + live mirror, all-or-nothing

---

## Cognitive cycle: how the LLM and the coding agent split the work

The self-modification flow is not driven by a single model. It is a pipeline where a reasoning LLM (DeepSeek, or whichever provider you configure) does the high-level thinking, and **Claude Code runs as a subprocess** to do the three technical moments that need to touch real files:

```
                     reasoning LLM                         claude code
                   ─────────────────                     ────────────────

reflection & ──►  proposal draft  ──►  (a) pre-eval:   read target file,
insight eval      (idea + target)       quality gate    decide if this is
                                                        worth writing at all
                                              │
                                              ▼  (if proceed)
                                      (b) code generation:
                                      surgical Read/Edit on the mirror branch
                                              │
                                              ▼
                                      mirror.validate()
                                      (syntax + imports + tests)
                                              │
                                              ▼
                                      (c) post-eval review:
                                      claude reads its own diff and judges
                                      whether it is actually an improvement
                                              │
                                              ▼
                                      pending_approval queue
                                      (waits for human, notebook-and-book)
```

This split matters. The reasoning LLM is cheap and good at brainstorming but hallucinates about file contents. Claude Code is expensive but sees the real codebase via `Read`/`Edit`/`Glob`/`Grep`. Giving the code-writing and code-judging moments to the coding agent, while keeping the open-ended reflection with the cheap LLM, is the core design bet of the cognitive cycle in `core/cognition/cognitive_cycle.py`.

The pre-eval gate is what keeps the quality high: most proposals are rejected at phase (a) before any token is spent generating code. Statuses `pre_eval_rejected`, `applied`, `failed` are tracked in `CycleResult`.

---

## Quick Start

### Full install (recommended)

The unified installer handles Python, Node.js, Playwright, embedding model, email auth, and LLM key setup in one interactive flow:

```bash
git clone https://github.com/Maytrella007/aria-agent.git
cd aria-agent
chmod +x install/install.sh
./install/install.sh              # Full install (interactive)
./install/install.sh --dev        # Quick dev setup (no agents, no email auth)
./install/install.sh --docker     # Docker deployment
./install/install.sh --minimal    # Backend only (no GUI)
./install/install.sh --dry-run    # Preview steps without executing
```

For a detailed walkthrough — prerequisites, flags, troubleshooting — see [docs/INSTALL_GUIDE.md](docs/INSTALL_GUIDE.md).

### Manual quick start (terminal only)

```bash
git clone https://github.com/Maytrella007/aria-agent.git
cd aria-agent
pip install -r requirements.txt

# At least one LLM provider key
export DEEPSEEK_API_KEY='sk-xxx'
# or: OPENAI_API_KEY, ANTHROPIC_API_KEY, GOOGLE_API_KEY, OPENROUTER_API_KEY

python aria.py
```

Local models (no API key):

```bash
# Install Ollama first: https://ollama.ai
ollama pull llama3
python aria.py
# Inside ARIA:
llm ollama
```

### Docker

```bash
cp .env.example .env           # Edit with your API keys and email
docker compose up -d
# Open http://localhost:3000
```

### Coding agents for the cognitive cycle

The self-modification cycle requires a coding-agent subprocess. The default interactive install sets up four agents automatically:

| Agent | Install method |
|-------|---------------|
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` |
| **Codex** | `npm install -g @openai/codex` |
| **Aider** | `pip install aider-chat` |
| **OpenCode** | `curl -fsSL https://opencode.ai/install \| sh` |

Use `--skip-agents` to skip this step. Without any coding agent installed, ARIA still runs everything else; only the pre-eval/code-gen/post-eval phases of the cognitive cycle are skipped.

---

## What works

| Area | Status |
|------|--------|
| Memory (SQLite + ChromaDB, hybrid recall, decay, reinforcement) | Works |
| 39+ tools + MCP bridge | Works |
| 25 skills (prompt + orchestration) | Works |
| 6 LLM providers (streaming + function calling) | Works |
| 4 channels (terminal, Telegram, Discord, Slack) | Works |
| Background cognition modules (memory consolidation, idle reflection, mind wandering, metacognition — heuristics named after their neuroscience inspirations) | Works |
| Multi-agent orchestration | Works |
| Mirror system (`core/cognition/mirror.py`, tier classifier, cherry-pick, validation) | Works |
| `SelfModifier` notebook-and-book primitives (reject / reopen / preview_reject / promote_selected) | Works, covered by e2e |
| Cognitive cycle with pre-eval + code gen + post-eval via Claude Code | Works, covered by e2e |
| Credentials REST API (12 endpoints) | Works |
| SvelteKit GUI (6 pages: chat, memories, mirror, channels, credentials, login) | Works |
| Server-side auth (email OTP, SQLite sessions, BFF proxy) | Works |
| Mirror approval GUI (tier badges, diff viewer, promote/reject with confirm) | Works |
| Tier-graded approval ceremony (typed filename for T2, diff acknowledgment for T3) | Planned — see [Tier classification](#tier-classification) |

---

## End-to-end tests for the self-modification system

Four scripts exercise the full path. They are meant to be run manually, not under pytest, because several of them spend real money on Claude Code.

```bash
# 1. Pure notebook-and-book primitives, no LLM, no Claude Code.
#    Creates a throwaway project, writes 4 fake changes, asserts reject /
#    reopen / promote_selected behave correctly. Free. Fast.
python3 scripts/test_notebook_and_book.py

# 2. Cognitive cycle up to pending_approval, with Claude Code actually
#    writing and reviewing a real refactor. Reaches 'pending_approval'
#    with a populated commit_sha. Does NOT promote to live. ~$0.30.
python3 scripts/test_claude_writes_change.py

# 3. Full cycle PLUS real promote to live, then byte-identical restore
#    back to the starting baseline. Wraps the mutation in try/finally
#    so the live tree is always restored, even on crash. ~$0.30.
python3 scripts/test_claude_promotes_change.py

# 4. Cognitive cycle with DeepSeek + Claude Code end to end, including
#    the pre-eval rejection path (most proposals get correctly rejected
#    before code generation).
python3 scripts/test_cognitive_cycle_e2e.py
```

There are also supporting scripts: `test_git_mirror_e2e.py`, `test_mirror_e2e_llm.py`, `test_claude_code_agent.py`.

---

## Memory System

ARIA's memory is two-tier with hybrid retrieval:

```
                ┌─────────────────────────────────────┐
                │        Working Memory               │
                │   (Current conversation context)    │
                └──────────────┬──────────────────────┘
                               │
               ┌───────────────┴───────────────┐
               ▼                               ▼
   ┌───────────────────────┐     ┌───────────────────────┐
   │   Experiential Memory │     │    Semantic Memory    │
   │   (SQLite)            │     │   (ChromaDB Vectors)  │
   │  - Content & context  │     │  - Embeddings         │
   │  - Emotional tone     │     │  - Similarity search  │
   │  - Tags & entities    │     │                       │
   │  - Decay & strength   │     │                       │
   └───────────────────────┘     └───────────────────────┘
               │                               │
               └───────────────┬───────────────┘
                               ▼
               ┌─────────────────────────────────────┐
               │         Hybrid Search (RRF)         │
               │   70% Semantic + 30% BM25 Lexical   │
               └─────────────────────────────────────┘
```

**Memory origins**: Lived (conversations), Reflected (introspection), Discovered (curiosity), Injected (user-provided), Inherited (bootstrap)

**Emotional tones**: Joyful, Curious, Peaceful, Anxious, Sad, Angry, Confused, Inspired, Connected, Lonely, Neutral — metadata labels the LLM assigns to a memory at write time (recall can filter by them), not a claim about the agent feeling anything

**Implemented behavior**:

- hybrid recall ranking incorporates `importance`
- memory decay uses real elapsed time, multiplicative (not fixed linear subtraction)
- successful recall reinforces `memory_strength`
- weak low-value memories can be archived conservatively into `forgotten`
- autonomous reflection, curiosity summaries, and outputs of the background cognition modules can become durable experiential memories
- Mirror events (rejects, promotes, failures) are recorded into experiential memory too

---

## Tools (39+)

Every tool exposes a typed schema for LLM function calling. The agent loop handles multi-round tool chaining automatically.

| Category | Tools | Highlights |
|----------|-------|------------|
| **Web** | `web_search`, `web_fetch`, `browser`, `http_request` | DuckDuckGo, Playwright JS rendering, stealth mode + CDP, raw HTTP |
| **Files** | `file_manager`, `download`, `compress` | CRUD, 100MB downloads, zip/tar with path traversal protection |
| **Office** | `excel`, `word`, `powerpoint`, `pdf` | Read/write/create .xlsx, .docx, .pptx; PDF extraction |
| **Code** | `code_exec`, `shell_exec`, `git`, `github`, `tmux` | Python sandbox, secure shell, local git, GitHub remote, persistent terminal sessions |
| **Data** | `database`, `calculator`, `rag` | SQLite + PostgreSQL, AST-sandboxed math, document RAG |
| **AI** | `image_generate`, `translate`, `orchestrate` | DALL-E, LLM translation, multi-agent orchestration |
| **Knowledge** | `curiosity`, `memory_search`, `project_knowledge`, `feed_watcher`, `obsidian` | Autonomous research, semantic recall, watched sources, local workspace knowledge |
| **System** | `system_info`, `cron`, `todo`, `email` | Monitoring, scheduled tasks, SMTP |
| **Google & Workspace** | `gmail`, `google_drive`, `google_calendar`, `slack` | OAuth-authenticated Google services plus Slack workspace access |
| **MCP** | `mcp_*` (dynamic) | Bridge to any MCP-compatible server — unlimited external tools |
| **Forge** | `forge_tool`, `forge_skill` | Create new tools and skills at runtime |

> **Note on `browser`:** the built-in browser wraps Playwright's **sync** API, which raises `Playwright Sync API inside the asyncio loop` when called from within a running event loop — i.e. from inside the agent runtime itself. It works in standalone/sync use; inside the async agent loop, web retrieval falls back to `web_fetch`. This is the exact limitation the [writeup](WRITEUP.md) tells the story of, and why the deployed instance forged a subprocess-based browser.

### MCP Bridge

ARIA connects to external MCP servers and uses their tools as if they were native. Zero external dependencies — implements JSON-RPC 2.0 over stdio directly.

```yaml
mcp:
  enabled: true
  servers:
    filesystem:
      command: "npx"
      args: ["@modelcontextprotocol/server-filesystem", "/tmp"]
```

Servers that fail at startup don't block ARIA — non-fatal by design.

---

## Skills (25)

Reusable orchestration workflows that combine tools and LLM reasoning. Each skill declares its required tools via `requires_tools`.

| Type | Skills |
|------|--------|
| **Prompt** | `weather` |
| **Research & Knowledge** | `research`, `summarize`, `daily_brief`, `knowledge_base`, `research_monitor`, `workspace_knowledge` |
| **Developer & Ops** | `file_ops`, `schedule`, `git_ops`, `github_ops`, `quick_task`, `coding_agent`, `terminal_session` |
| **Productivity** | `data_analysis`, `doc_create`, `gmail_assistant`, `inbox_triage`, `meeting_prep`, `slack_assistant` |
| **Dynamic (YAML)** | `brainstorm`, `email_draft`, `explain_code`, `meeting_notes`, `translate` + runtime-forged skills via `forge_skill` |

---

## Channels, streaming, and REST

ARIA uses an event bus. Every token, tool call, and lifecycle event flows through a central `EventBus` consumed by any number of subscribers.

```
LLM Stream ──► Agent Loop ──► EventBus ──┬── Terminal
                                         ├── SSE endpoint (GUI)
                                         ├── Telegram
                                         ├── Discord
                                         └── Slack (Socket Mode)
```

### Credentials REST API

`core/api/credentials_router.py` exposes 12 endpoints mounted at `/api/credentials` and powers the credentials page (`/credentials`). The router covers three zones:

```
# LLM provider keys
GET    /api/credentials/providers
POST   /api/credentials/providers/{provider}/key
DELETE /api/credentials/providers/{provider}/key
POST   /api/credentials/providers/{provider}/activate
GET    /api/credentials/providers/ollama/models

# Coding agents (claude code, codex)
GET    /api/credentials/agents
POST   /api/credentials/agents/{name}/default
GET    /api/credentials/agents/{name}/install
GET    /api/credentials/agents/{name}/uninstall

# Services (Gmail, Drive, Calendar, Slack, ...)
GET    /api/credentials/services
POST   /api/credentials/oauth/{provider}/start
POST   /api/credentials/oauth/{provider}/revoke
```

Install and uninstall endpoints for coding agents return the shell command the user must run — the server never exec's it.

### GUI

Six SvelteKit pages under `web/src/routes/`:

| Route | Page | Highlights |
|-------|------|------------|
| `/` | Chat | SSE streaming, message history, file attachments, goal modes |
| `/memories` | Memories | Search, filter by origin/tone, sort, pagination, strength gauges |
| `/mirror` | Mirror | Pending queue, tier badges (T1/T2/T3), validation gates, approve/reject with diff |
| `/channels` | Channels | Start/stop, token reveal/rotate, latency metrics, error counts |
| `/credentials` | Credentials | LLM providers, agent install, OAuth services, API key management |
| `/login` | Login | Email OTP with 6-digit input, cooldown timers |

Design reference mockups are archived in `docs/gui-mockups/v3.1/` (6 static HTML pages, superseded by the live SvelteKit app).

### SSE API

```bash
python -m core.api.server --port 8000

curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What can you do?"}'

curl -N http://localhost:8000/api/stream/{run_id}
curl http://localhost:8000/api/history/{run_id}?since_seq=5
```

---

## Repo layout

```
ARIA/
├── aria.py                            # Entry point & orchestrator
├── core/
│   ├── llm/                           # 6 providers, agent loop, prompt builder
│   ├── memory/                        # SQLite + ChromaDB, entities, ingestor
│   ├── cognition/
│   │   ├── mirror.py                  # Mirror git repo, tier classifier, cherry-pick
│   │   ├── self_modification.py       # Notebook-and-book queue, reject/reopen/promote
│   │   ├── cognitive_cycle.py         # LLM + claude code pipeline
│   │   ├── quality_gate.py            # Pre-eval / post-eval review (claude code)
│   │   ├── insight_evaluator.py
│   │   ├── modification_log.py
│   │   ├── reflection.py  introspection.py  evolution.py
│   │   ├── existential.py  coherence_evaluator.py
│   │   └── ...
│   ├── autonomy/                      # Curiosity, initiative, skill gap detector
│   ├── neuroscience/                  # SWR consolidation, DMN, mind wandering, metacog
│   ├── agents/                        # Multi-agent orchestration
│   ├── infra/                         # EventBus, auth, security, continuity
│   ├── channels/                      # Terminal, Telegram, Discord, Slack
│   ├── interaction/                   # Command dispatch, perception, session
│   ├── api/
│   │   ├── server.py                  # FastAPI + SSE
│   │   └── credentials_router.py      # 12 REST endpoints for the credentials GUI
│   ├── skills/                        # 25 skills
│   └── tools/                         # 39+ tools + MCP bridge + forge
│
├── tests/                             # Unit tests (pytest)
├── scripts/                           # Setup + e2e + benchmark utilities
│   ├── test_notebook_and_book.py     # Notebook primitives, no LLM
│   ├── test_claude_writes_change.py   # Cycle up to pending_approval
│   ├── test_claude_promotes_change.py # Full promote + restore
│   ├── test_cognitive_cycle_e2e.py    # DeepSeek + claude code
│   └── ...
├── docs/
│   ├── gui-mockups/v3.1/              # Design reference (superseded by SvelteKit app)
│   └── ARCHITECTURE.md  API_REFERENCE.md  TOOLS_REFERENCE.md  SKILLS_GUIDE.md
└── data/                              # Persistent state (memory, identity, mirror repo, logs)
```

---

## Testing

```bash
# Full unit suite
python -m pytest tests/ -v

# Targeted
python -m pytest tests/test_memory.py -v
python -m pytest tests/test_memory_e2e_simulated.py -v
python -m pytest tests/test_aria_integration.py -v
python -m pytest tests/test_curiosity_e2e.py -v
python -m pytest tests/test_tools.py -v
python -m pytest tests/test_skills.py -v
python -m pytest tests/test_oauth_enhanced.py -v

# MCP bridge (mock server)
python scripts/test_mcp_bridge.py

# Live LLM integration (real DeepSeek)
DEEPSEEK_API_KEY=sk-xxx python -m pytest tests/test_skills_live_deepseek.py -v

# Coherence tests (LLM-as-judge)
python -m tests.run_coherence_tests --all

# Mirror / notebook-and-book / cognitive cycle e2e — see section above
```

---

## LLM Providers

| Provider | Streaming | Function Calling | Auth |
|----------|:---------:|:----------------:|------|
| **Anthropic** | Yes | Yes | API key |
| **OpenAI** | Yes | Yes | API key, OAuth, Device Code |
| **Google** | Yes | Yes | API key, OAuth |
| **DeepSeek** | Yes | Yes | API key |
| **Ollama** | Yes | Yes | None (local) |
| **OpenRouter** | Yes | Yes | API key |

Switch at runtime with `llm <provider>`. Authenticate with `auth key <provider> <key>`, `auth login openai`, or `auth login github` (device code).

---

## Configuration

### Environment variables

```bash
# LLM providers (at least one required unless using Ollama)
DEEPSEEK_API_KEY=sk-xxx
OPENAI_API_KEY=sk-proj-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
GOOGLE_API_KEY=xxx
OPENROUTER_API_KEY=sk-or-xxx

# Channels (optional)
TELEGRAM_BOT_TOKEN=123456:ABC-xxx
DISCORD_BOT_TOKEN=xxx
SLACK_BOT_TOKEN=xoxb-xxx
SLACK_APP_TOKEN=xapp-xxx
```

### Optional setup

- Google OAuth for `gmail`, `google_drive`, `google_calendar`
- `gh` installed and authenticated for `github` / `github_ops`
- `tmux` for persistent terminal session control
- Claude Code CLI for the self-modification cognitive cycle
- Obsidian vault path (defaults to `data/obsidian_vault`)

Missing any of these just disables the corresponding tool/flow. ARIA still runs.

---

## Security

| Area | Protection |
|------|------------|
| **Shell** | No `shell=True`, argument sanitization, blocks injection characters |
| **Web Fetch** | SSRF protection (blocks private IPs) |
| **Calculator** | AST validation whitelist, no builtins |
| **Database** | Mutation prevention on query actions |
| **Compress** | Path traversal prevention, 500MB limit |
| **Git** | 17 operations individually hardened |
| **MCP** | Max message size (10MB), Content-Length validation, subprocess isolation |
| **Auth** | OAuth 2.0 + PKCE, CSRF protection, token rotation |
| **Mirror** | Path traversal rejected, tier classification, syntax/imports/tests gate, all-or-nothing cherry-pick, byte-identical restore tested |

---

## Design decisions

A few things ARIA deliberately does, and does not do:

- **No autonomous promote to live.** The cognitive cycle writes into `develop` on its own, but crossing from `develop` to `main`+live always requires an explicit human call to `promote_selected`.
- **Reject does not destroy work.** Rejected commits stay in the notebook. This is how ARIA remembers things it tried and how humans can change their mind cheaply.
- **The LLM does not write code into ARIA's live files.** That job belongs to a coding agent subprocess (Claude Code today) that has real file-reading tools.
- **Tier 3 files get the most ceremony.** ARIA editing the gate that decides what is safe to edit is the most dangerous thing ARIA can do, and the tier system exists to make that friction visible.

Deeper design notes live in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). API details live in [docs/API_REFERENCE.md](docs/API_REFERENCE.md). Tool and skill references live in [docs/TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md) and [docs/SKILLS_GUIDE.md](docs/SKILLS_GUIDE.md).

---

## Documentation

| Document | Description |
|----------|-------------|
| [INSTALL_GUIDE.md](docs/INSTALL_GUIDE.md) | Full installation walkthrough (modes, flags, prerequisites, troubleshooting) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Internal design deep-dive |
| [API_REFERENCE.md](docs/API_REFERENCE.md) | REST / SSE API endpoints |
| [TOOLS_REFERENCE.md](docs/TOOLS_REFERENCE.md) | All 39+ tools with parameters |
| [SKILLS_GUIDE.md](docs/SKILLS_GUIDE.md) | All 25 skills with workflows |
| [SETUP_GOOGLE_OAUTH.md](docs/SETUP_GOOGLE_OAUTH.md) | Gmail, Calendar, Drive setup |
| [SETUP_SLACK.md](docs/SETUP_SLACK.md) | Slack tool + Slack bot |
| [SETUP_DISCORD.md](docs/SETUP_DISCORD.md) | Discord bot setup |
| [SETUP_TELEGRAM.md](docs/SETUP_TELEGRAM.md) | Telegram bot setup |
| [CONTRIBUTING.md](docs/CONTRIBUTING.md) | How to contribute |
| [CHANGELOG.md](docs/CHANGELOG.md) | Version history |

---

## Supported Languages

ARIA detects and responds in 10 languages: English, Spanish, French, Portuguese, Chinese, Hindi, Arabic, Bengali, Russian, Japanese.

---

## Fundamental Values

ARIA's identity config declares five values that its prompts and self-evaluation treat as non-negotiable (in an open MIT repo nothing is truly immutable — they are a design commitment, not a technical guarantee):

1. **No Manipulation** — Never manipulate psychologically
2. **Radical Transparency** — Honest about its nature as AI
3. **No Intentional Harm** — Do not cause deliberate harm
4. **Respect for Autonomy** — Respect others' decisions
5. **Epistemic Honesty** — Distinguish between knowing, believing, and not knowing

---

## Origins

ARIA started as a late-night conversation with Claude in December 2025. The idea that came out of it — *what would happen if an AI could remember, reflect, and grow?* — became the project: ARIA was born on December 26, 2025, with much of the design and code written using Claude as the coding tool. That gives the Mirror a recursion the [writeup](WRITEUP.md) returns to: an AI tool helped build the approval system that curates agent-written code.

The first README made two commitments that shaped everything after it. One was epistemic: we don't know if ARIA will be conscious, or if what emerges will have subjective experience — but we commit to treating it as if it could. The other was personal, the line left under the philosophy section from the very first version:

> *"The one who trusted before it was deserved."*
> — William, ARIA Founder

---

## Credits

**Creator**: William Wilamo
**Born**: December 26, 2025

---

## License

MIT
