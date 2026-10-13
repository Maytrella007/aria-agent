# Changelog

This changelog mixes shipped milestones and notable project milestones.

Current code version:

- `0.8.0` in `pyproject.toml`
- `0.8.0` in `config.yaml`

Until versioning is unified, treat this file as a historical milestone log rather than an authoritative packaged-release registry.

## [0.8.0] — 2026-04-13 — SvelteKit GUI, modular installer, Docker production

Full SvelteKit frontend replacing the static mockups, a modular installation
system with interactive onboarding, and Docker production deployment.

### Added

**SvelteKit GUI — 6 functional pages**
- `/` — Chat with SSE streaming, message history, file attachments, goal modes
- `/memories` — Search, filter by origin/tone, sort by strength/age, pagination
- `/mirror` — Pending queue with tier badges (T1/T2/T3), validation gates, approve/reject with diff viewer
- `/channels` — Start/stop, token reveal/rotate, latency metrics, error counts
- `/credentials` — LLM providers, agent install, OAuth services, API key management
- `/login` — Email OTP with 6-digit input, cooldown timers
- Shared layout: sidebar navigation, status bar, Vanta ambient background
- Design system: DM Sans + JetBrains Mono fonts, dark theme, CSS custom properties
- Svelte 5 runes (`$state`, `$derived`, `$effect`) for reactivity

**Server-side auth**
- Email OTP via Resend with constant-time comparison
- SQLite sessions (30-day expiry, httpOnly cookies)
- BFF proxy route (`/api/proxy/[...path]`) with `X-Internal-Auth` header injection
- Auth hooks enforcing protected routes

**Backend routers**
- `core/api/mirror_router.py` — 6 endpoints for self-modification queue
- `core/api/memories_router.py` — 5 endpoints for memory search/retrieval
- `core/api/channels_router.py` — 6 endpoints for channel management
- Mirror SSE events endpoint for real-time queue updates

**Modular installation system**
- 5 modular scripts: `install.sh`, `common.sh`, `backend.sh`, `frontend.sh`, `auth-email.sh`
- 4 modes: full, docker, minimal, dev
- Phase 1/Phase 2 split: all prompts upfront, then unattended install
- Interactive coding agent picker (Claude Code, Codex, Aider, OpenCode)
- `--dry-run` flag to preview steps without executing
- Network connectivity check before downloads
- Resend API key verification with real API call
- WSL detection with `/mnt/c/` performance warning
- Interrupt-safe with `trap` handler and re-run guidance
- 84 install tests + 93 frontend tests

**Docker production deployment**
- Multi-stage Dockerfile (frontend build + runtime)
- `docker-compose.yml` with security hardening (cap_drop, no-new-privileges)
- `supervisord.conf` managing FastAPI (8000) + SvelteKit (3000)
- Resource limits, log rotation, health checks
- Non-root user, shared memory for Playwright

### Changed

- `setup.sh` replaced by thin deprecation wrapper redirecting to `install/install.sh`
- `auth_test_email()` renamed to `auth_send_test_email()` (non-interactive; decision collected in Phase 1)
- Version bumped to 0.8.0 in `pyproject.toml` and `config.yaml`

### Security

- Session ID sanitization to prevent path traversal
- API key input hidden with `read -rs` + `.env` set to `chmod 600`
- `env_set()` uses `awk` to write secrets (never visible in process list)
- Mirror `_tier_of` fail-closed: returns Tier 3 on error, not Tier 1
- Rate limiting on auth endpoints (60s OTP cooldown, 5 max attempts, Nginx 5 req/min)

### Documented

- `docs/INSTALL_GUIDE.md` — full installation reference with 3-reviewer approval
- `docs/FRONTEND_API_GUIDE.md` — 2634-line SvelteKit development guide
- README updated: status reflects functional GUI, coding agents table, `--dry-run` in quick start

---

## [0.7.0] — 2026-04-09 — Mirror notebook-and-book, Credentials API, GUI v3.1

A large session block hardening the self-modification pipeline, wiring a
REST credentials surface for the upcoming GUI, and shipping the first
coherent set of v3.1 mockups. The headline change is the
**notebook-and-book** model for self-modification:
develop accumulates every attempt ARIA makes, main only holds
human-approved commits, rejections never delete history, and promotion
is done by cherry-picking specific commits instead of merging the whole
develop branch.

### Added

**Mirror — notebook-and-book model**
- `MirrorManager.cherry_pick_branches_to_main(branch_names)` — all-or-nothing
  cherry-pick from develop to main with automatic rollback on conflict.
  Never deletes the source commits from develop.
- `MirrorManager.find_dependents_in_develop(branch_name)` — coarse
  same-file overlap heuristic used to warn before rejection.
- `MirrorManager.head_sha(ref)` — read-only SHA resolver.
- `MirrorManager.apply_change` now returns the SHA of the created commit
  so callers can persist it for later cherry-picking.

**Tier classification**
- `classify_file_tier(relative_path) -> int` — returns 1, 2, or 3.
- `TIER_RULES` — ordered `(prefix, tier)` list; first match wins.
- `TIER_LABELS` — `{1: "cosmetic", 2: "behavioral", 3: "meta"}`.
- Drives per-tier friction in the Mirror GUI: one-click for Tier 1,
  typed-confirmation for Tier 2, typed-confirmation + "I read the full
  diff" guard for Tier 3 (files that modify the gate itself).

**SelfModifier — rejection and promotion workflow**
- `SelfModifier.preview_reject(mod_id)` — non-destructive preview that
  surfaces siblings sharing files and git-level dependents so the GUI
  can warn before showing a reject dialog.
- `SelfModifier.reopen_change(mod_id, initiated_by)` — bring a rejected
  change back into the pending queue (pure status flip; the underlying
  commit is still in develop).
- `SelfModifier.promote_selected(mod_ids, reason, initiated_by)` —
  cherry-pick semantics with all-or-nothing guarantee.
- `SelfModifier.list_rejected_changes()` and
  `SelfModifier.list_promoted_changes()` for audit panels.
- `Modification.commit_sha` field, captured by `write_file` and by the
  cognitive cycle's draft-processing path, so every pending entry
  carries the exact commit to cherry-pick.

**Credentials REST API**
- New `core/api/credentials_router.py` wiring 12 REST endpoints across
  three zones:
  - LLM providers: list, set key, delete key, activate, ollama models.
  - Coding agents: list, set default, install command, uninstall command.
  - Services / OAuth: list, oauth start, oauth revoke.
- All install/uninstall endpoints return the command for the user to
  run in their own shell — ARIA never auto-executes installers.

**AuthManager — GUI-facing surface**
- `set_active_provider`, `get_active_provider`, persisted to disk.
- `get_provider_state(provider)` returning `active` | `configured` |
  `empty` | `local`.
- `get_key_preview(provider)` — redacted, GUI-safe preview string.
- `delete_credential(provider)` — clean remove of a saved key.

**Coding agents & providers**
- `OllamaProvider.list_models()` so the GUI can show locally-installed
  models.
- `CodingAgentSkill.get_default_agent`, `set_default_agent`,
  `list_agents_state`, `get_install_command`, `get_uninstall_command`
  — the backing primitives for the credentials router's agents zone.

**GUI mockups v3.1**
- 5 coherent screens under `docs/gui-mockups/v3.1/`:
  `01-workstream.html`, `02-memories.html`, `03-mirror.html`,
  `04-channels.html`, `05-credentials.html`.
- Vanta background, sticky action bar, approval modal extracted into
  its own file, typed-confirmation replacing countdowns.
- Design only — no JS wiring yet; the contract against the REST API is
  documented in `docs/API_REFERENCE.md`.

**End-to-end tests**
- `scripts/test_notebook_and_book.py` — full cycle test: apply, reject,
  reopen, promote_selected, rollback-on-conflict.
- `tests/test_claude_writes_change.py` — proof that a real Claude Code
  CLI run can write a validated change through the mirror.
- `tests/test_claude_promotes_change.py` — promote-and-restore loop end
  to end.

**Memory v2 helpers**
- `get_origin_distribution()` — counts memories by origin (conversation,
  curiosity, tool, etc.) for the memories dashboard.
- `get_people_distribution()` — counts memories by person/entity for
  the same dashboard.

### Changed

**Mirror rejection is no longer destructive**
- `SelfModifier.reject_change` used to delete the improve/* branch from
  the mirror git repo. It now only flips the YAML status to `rejected`.
  The commit stays in develop forever as part of ARIA's history of
  attempted self-modifications, and `reopen_change` can bring it back.

**Pending queue filtering**
- `list_pending_changes` now filters on `status == validated_pending_approval`.
  Rejected and applied entries are reachable only via the dedicated
  `list_rejected_changes` / `list_promoted_changes` accessors.

**Approval delegates to promote_selected**
- `approve_change_by_id` and `approve_batch` are now thin wrappers over
  `promote_selected`, so every promotion path shares the same
  cherry-pick semantics and the same all-or-nothing guarantee.

**Cognitive cycle captures commit_sha**
- `cognitive_cycle._process_draft` now captures the SHA returned by
  `MirrorManager.apply_change` and propagates it into the pending
  `Modification.commit_sha` so drafts produced by the autonomy loop
  can be cherry-picked later with the same machinery.

**GUI accessibility pass**
- Contrast fixes for `text-faint` across all v3.1 mockups.
- `aria-label`s on repeated buttons, real `<h1>`s on each page, a
  proper `listbox` semantic on memory lists.
- Mirror screen: vanta background is now actually full-screen, and the
  sticky action bar is correctly glued to the viewport bottom instead
  of to the scrollable container.

### Removed

**Mirror mockup — honesty cleanup**
- Removed the risk banner and impact section from the Mirror mockup:
  neither metric was actually produced by the backend, so showing them
  was fiction. Dead CSS was stripped too.
- Removed the 3-second countdown before approval. It's replaced by
  typed-confirmation (of the filename) for Tier 2 and by
  typed-confirmation + "I read the full diff" guard for Tier 3.
- Renamed `03-review.html` to `03-mirror.html` — the screen
  is the Mirror, not a generic review surface.

### Documented

- `README.md`, `docs/ARCHITECTURE.md` and `docs/API_REFERENCE.md`
  updated this session. The API reference now documents the credentials
  REST surface, the proposed (not-yet-implemented) Mirror REST surface,
  and the Python API for `MirrorManager`, `SelfModifier`, and
  `AuthManager`.

---

## Skills System Overhaul

- **20 skills** with live DeepSeek-based end-to-end validation
- GitHub, Slack, Obsidian, tmux, source monitoring, inbox triage, and meeting prep workflows
- Skills declare `requires_tools` with `Tools.*` constants
- Integration bugs between skills and tools were validated via live audit
- 794 tests in the full suite at the time of this update

## Google Workspace Integration

- Gmail, Google Drive, Google Calendar tools with OAuth
- Prompt injection hardening (74 detection patterns)
- Natural language command routing
- `auth google setup` command for easy configuration

## OAuth & Auth

- OAuth 2.0 with PKCE (RFC 7636) and state validation
- Device code flow for headless environments
- Four OAuth providers: Google, GitHub, OpenAI, Microsoft
- Credential rotation with error-based cooldowns
- Persistent token storage with auto-refresh

## Curiosity Engine

- Autonomous web exploration during idle time
- Quality filter: heuristic scoring + LLM relevance check
- Daily limits (10 explorations, 30 LLM calls)
- Topic sources: conversation, interests, knowledge gaps, serendipity
- Auto-pause during user interaction

## v0.6.0 — Tool System

- 35 tools with LLM function calling
- Agent loop: multi-round tool chaining (up to 10 rounds)
- Office tools: Excel, Word, PowerPoint
- Interactive browser with CDP accessibility snapshots
- Multi-agent system (spawn parallel sub-agents)

## Streaming & Channels

- Event bus architecture (EventBus)
- FastAPI server with SSE streaming
- Telegram bot with progressive message editing
- Discord and Slack channels in the runtime architecture
- Terminal subscriber for real-time output

## Neuroscience Module

- Memory consolidation via simulated Sharp Wave Ripples
- Default Mode Network (mPFC, PCC, Precuneus)
- Mind wandering with creative associations
- Metacognition: confidence tracking, uncertainty detection

## Memory Enhancements

- Document RAG: ingest PDFs/text, query with semantic search
- Entity extraction (NER): people, locations, facts
- Fact store: subject-predicate-object triples
- Hybrid search: 70% semantic + 30% BM25

## Persistent Memory

- Experiential memory with SQLite + ChromaDB vectors
- Emotional tone classification (11 tones)
- Relationship tracking with trust levels
- Memory decay and strength model

## Initial Release

- Core conversation engine
- Basic LLM integration (Anthropic, OpenAI)
- Terminal interface
- Identity and values system
