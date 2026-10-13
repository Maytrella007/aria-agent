# ARIA API Reference

ARIA exposes two programmable surfaces:

1. An **HTTP API** (REST + SSE) served by `core.api.server` — used by the GUI,
   third-party integrations, and the in-browser mockups under
   `docs/gui-mockups/`.
2. A **Python API** — the internal classes and functions you import when
   embedding ARIA, writing tools/skills, or scripting the mirror.

This document enumerates both. It is intentionally honest about what is
**implemented** today vs what is only **proposed** (marked clearly).

## Runtime channels

The HTTP API is one runtime surface among several current channels:

- terminal
- Telegram
- Discord
- Slack
- REST + SSE API

## Starting the server

```bash
python -m core.api.server --port 8000
```

The server wires the base chat/stream/status routes (below) plus four routers:

- credentials (`core.api.credentials_router`) → `/api/credentials`
- memories (`core.api.memories_router`) → `/api/memories`
- mirror (`core.api.mirror_router`) → `/api/mirror`
- channels (`core.api.channels_router`) → `/api/channels`

---

# HTTP API

## Chat / Stream / Status (existing)

### GET /api/status

Health check and system info.

**Response:**
```json
{
  "status": "ok",
  "llm_available": true,
  "tools_count": 41
}
```

`status` is `"not_initialized"` if ARIA hasn't finished startup.

**curl:**
```bash
curl http://localhost:8000/api/status
```

---

### POST /api/chat

Send a message to ARIA. Returns a `run_id` for streaming the response.

**Request:**
```json
{
  "message": "What can you do?",
  "user": "web_user"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `message` | string | *required* | User message |
| `user` | string | `web_user` | User identifier |

**Response:**
```json
{
  "run_id": "a1b2c3d4"
}
```

Processing happens asynchronously. Use the `run_id` to stream events.

**curl:**
```bash
curl -X POST http://localhost:8000/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message":"hello"}'
```

---

### GET /api/stream/{run_id}

Server-Sent Events (SSE) endpoint for real-time streaming.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_id` | string | *required* | Run ID from `/api/chat`, or `"all"` for all runs |
| `since_seq` | int | 0 | Replay events after this sequence number |

**Response:** `text/event-stream`

```
data: {"stream":"lifecycle","event":"start","data":{"run_id":"a1b2c3d4"},"seq":1}

data: {"stream":"lifecycle","event":"thinking","data":{},"seq":2}

data: {"stream":"assistant","event":"delta","data":{"text":"I can "},"seq":3}

data: {"stream":"assistant","event":"delta","data":{"text":"help you "},"seq":4}

data: {"stream":"assistant","event":"done","data":{"full_text":"I can help you...","usage":{}},"seq":10}

data: {"stream":"lifecycle","event":"end","data":{"duration_ms":1234},"seq":11}
```

**Behavior:**
- Keepalive comments (`: keepalive\n\n`) sent every 30 seconds
- Replays missed events on reconnection via `since_seq`
- Stream closes when `lifecycle:end` event is emitted (unless `run_id="all"`)

---

### GET /api/history/{run_id}

Retrieve missed events for reconnection.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `run_id` | string | *required* | Run ID |
| `since_seq` | int | 0 | Only events after this sequence |

**Response:**
```json
[
  {
    "run_id": "a1b2c3d4",
    "stream": "assistant",
    "event": "delta",
    "data": {"text": "Hello"},
    "seq": 3
  }
]
```

---

## Credentials API (new)

All routes live under `/api/credentials` and are wired from
`core/api/credentials_router.py`. They back the credentials screen in
`docs/gui-mockups/v3.1/05-credentials.html` and are organized in three
zones: **LLM providers**, **coding agents**, **services / OAuth**.

Provider state is one of:

| State | Meaning |
|-------|---------|
| `active` | Current LLM in use |
| `configured` | Key is saved but another provider is active |
| `empty` | No credential stored |
| `local` | Local provider (Ollama), no key required |

### Zone 1 — LLM providers

#### GET /api/credentials/providers

List every known LLM provider with its current state.

**Response:**
```json
{
  "providers": [
    {
      "name": "anthropic",
      "model": "claude-sonnet-4-20250514",
      "state": "active",
      "key_preview": "sk-...abcd",
      "auth_methods": ["api_key"]
    }
  ],
  "active": "anthropic"
}
```

**curl:**
```bash
curl http://localhost:8000/api/credentials/providers
```

---

#### POST /api/credentials/providers/{provider}/key

Add or replace the API key for a provider. Rejects `ollama` (no key needed)
and empty strings.

**Body:**
```json
{ "key": "sk-ant-..." }
```

**Response:**
```json
{ "ok": true, "state": "configured" }
```

**curl:**
```bash
curl -X POST http://localhost:8000/api/credentials/providers/openai/key \
  -H 'Content-Type: application/json' \
  -d '{"key":"sk-..."}'
```

---

#### DELETE /api/credentials/providers/{provider}/key

Remove the saved API key for a provider.

**Response:**
```json
{ "removed": true, "state": "empty" }
```

---

#### POST /api/credentials/providers/{provider}/activate

Mark a provider as the active one. Fails with 400 if the provider has no
credential.

**Response:**
```json
{ "ok": true, "active": "openai" }
```

---

#### GET /api/credentials/providers/ollama/models

List models installed in the local Ollama instance (via
`OllamaProvider.list_models()`).

**Response:**
```json
{
  "models": ["llama3", "qwen2.5-coder"],
  "endpoint": "localhost:11434"
}
```

Returns `{"models": [], "error": "..."}` if Ollama is unreachable.

---

### Zone 2 — Coding agents

#### GET /api/credentials/agents

List every known coding agent with detection + auth state
(`CodingAgentSkill.list_agents_state()`).

**Response:**
```json
{
  "agents": [
    {
      "name": "claude",
      "description": "Anthropic Claude Code CLI",
      "binary": "claude",
      "installed": true,
      "authenticated": true,
      "is_default": true,
      "env_keys": ["ANTHROPIC_API_KEY"],
      "install_cmd": "npm install -g @anthropic-ai/claude-code",
      "install_alt": null,
      "auth_cmd": "claude login"
    }
  ]
}
```

---

#### POST /api/credentials/agents/{name}/default

Mark a coding agent as the default used by skills.

**Response:**
```json
{ "ok": true, "default": "claude" }
```

---

#### GET /api/credentials/agents/{name}/install

Return the install command for an agent. **Does not execute** — the
caller (shell or GUI) decides whether to run it.

**Response:**
```json
{
  "name": "claude",
  "install_cmd": "npm install -g @anthropic-ai/claude-code",
  "install_alt": null,
  "auth_cmd": "claude login",
  "note": "Run this command in your shell. ARIA does not auto-execute installers."
}
```

---

#### GET /api/credentials/agents/{name}/uninstall

Return the uninstall command (or 404 if there's no safe recipe). Same
"do not auto-execute" contract as install.

---

### Zone 3 — Services

#### GET /api/credentials/services

List third-party services with their current connection state. Possible
states: `connected`, `unconfigured`, `planned`.

**Response:**
```json
{
  "services": [
    {
      "name": "google_workspace",
      "label": "Google Workspace",
      "auth_type": "oauth",
      "scopes": ["gmail", "drive", "calendar"],
      "oauth_provider": "google",
      "planned": false,
      "state": "connected",
      "connected": true
    }
  ]
}
```

---

#### POST /api/credentials/oauth/{provider}/start

Start an OAuth login flow for a service provider (`google`, `github`, ...).
Currently calls `AuthManager.login_oauth(provider, method="auto")`, which
opens a browser or emits a device code in the server logs.

**Response:**
```json
{ "ok": true, "provider": "google" }
```

---

#### POST /api/credentials/oauth/{provider}/revoke

Revoke OAuth tokens for a service provider.

**Response:**
```json
{ "ok": true, "provider": "google" }
```

---

## Mirror API

Implemented in `core/api/mirror_router.py` and mounted at `/api/mirror` by
`core/api/server.py` (via `init_mirror_router`). It backs the Mirror screen
in the SvelteKit GUI. Each row shows the route and the `SelfModifier` /
`MirrorManager` method it delegates to.

| Method | Path | Delegates to |
|--------|------|--------------|
| GET    | `/api/mirror/status` | live Mirror/queue state |
| GET    | `/api/mirror/pending` | `SelfModifier.list_pending_changes()` |
| GET    | `/api/mirror/changes?status=rejected\|promoted\|all` | rejected / promoted / audit views |
| GET    | `/api/mirror/changes/{id}` | one change with diff |
| GET    | `/api/mirror/file-history/{path}` | per-file change history |
| GET    | `/api/mirror/preview-reject/{id}` | `SelfModifier.preview_reject(mod_id)` |
| GET    | `/api/mirror/preview-promote?ids=...` | dry-run of a selective promote |
| POST   | `/api/mirror/reject/{id}` | `SelfModifier.reject_change(mod_id, reason, initiated_by)` |
| POST   | `/api/mirror/request-changes/{id}` | ask for revisions on a pending change |
| POST   | `/api/mirror/reopen/{id}` | `SelfModifier.reopen_change(mod_id, initiated_by)` |
| POST   | `/api/mirror/promote` | `SelfModifier.promote_selected(ids, reason, initiated_by)` |
| POST   | `/api/mirror/freeze` / `/unfreeze` | pause / resume promotion |
| POST   | `/api/mirror/emergency-rollback` | restore the live tree to baseline |
| GET    | `/api/mirror/events` | SSE stream of Mirror events |

**Request bodies:**

```jsonc
// POST /api/mirror/promote
{ "ids": ["mod_abc", "mod_def"], "reason": "approved by william" }

// POST /api/mirror/reject/{id}
{ "reason": "wrong approach", "initiated_by": "william" }
```

**Proposed response shape for `/api/mirror/pending`:**

```json
[
  {
    "id": "mod_abc123",
    "target_file": "core/memory/memory_v2.py",
    "branch": "improve/mod_abc123",
    "commit_sha": "9f1e2a...",
    "status": "validated_pending_approval",
    "modification_type": "replace",
    "tier": 2
  }
]
```

The same functionality is also reachable directly via the Python API (see below).

---

## Event types

All SSE events follow this structure:

```json
{
  "stream": "string",
  "event": "string",
  "data": {},
  "run_id": "string",
  "seq": 0,
  "timestamp": 1234567890.123
}
```

### Lifecycle events

| Event | When | Data |
|-------|------|------|
| `lifecycle:start` | User sends message | `{run_id}` |
| `lifecycle:thinking` | LLM processing begins | `{}` |
| `lifecycle:end` | Response complete | `{duration_ms}` |

### Assistant events

| Event | When | Data |
|-------|------|------|
| `assistant:delta` | Each token from LLM | `{text}` |
| `assistant:done` | Full response ready | `{full_text, usage}` |

### Tool events

| Event | When | Data |
|-------|------|------|
| `tool:start` | Tool invoked | `{name, args, round}` |
| `tool:result` | Tool finished | `{success, preview, error, elapsed_ms}` |

### Error events

| Event | When | Data |
|-------|------|------|
| `error:error` | Any error | `{message, type}` |

---

## Example — Streaming client (Python)

```python
import requests
import json

resp = requests.post("http://localhost:8000/api/chat", json={
    "message": "What's the weather in Madrid?"
})
run_id = resp.json()["run_id"]

with requests.get(
    f"http://localhost:8000/api/stream/{run_id}",
    stream=True
) as stream:
    for line in stream.iter_lines():
        if line and line.startswith(b"data: "):
            event = json.loads(line[6:])
            if event["stream"] == "assistant" and event["event"] == "delta":
                print(event["data"]["text"], end="", flush=True)
            elif event["stream"] == "lifecycle" and event["event"] == "end":
                break
```

## Example — Streaming client (JavaScript)

```javascript
const resp = await fetch("http://localhost:8000/api/chat", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "What's the weather in Madrid?" })
});
const { run_id } = await resp.json();

const source = new EventSource(`http://localhost:8000/api/stream/${run_id}`);
source.onmessage = (e) => {
  const event = JSON.parse(e.data);
  if (event.stream === "assistant" && event.event === "delta") {
    process.stdout.write(event.data.text);
  }
  if (event.stream === "lifecycle" && event.event === "end") {
    source.close();
  }
};
```

---

## Event Bus Architecture

```
LLM Stream ──> Agent Loop ──> EventBus ──┬── Terminal (print)
                                         ├── SSE endpoint (/api/stream)
                                         ├── Telegram (progressive edits)
                                         └── Custom subscribers
```

- Max 50 run_ids retained in history
- Max 500 events per run_id
- Thread-safe pub/sub with bounded queues
- Supports sync callbacks, blocking queues, and async queues

---

# Python API

Internal classes and functions that are meant to be imported and used
directly. The Mirror screen, the credentials router, and the cognitive
cycle all use these primitives.

## core.cognition.mirror

Self-modification is staged in a standalone git repo under `data/mirror/`
with three layers of branches:

- `main`   — human-approved state
- `develop` — auto-merged changes that passed validation
- `improve/<name>` — individual in-flight change branches

We call this the *notebook-and-book* model: develop is
the notebook where ARIA writes every attempt (including rejected ones),
main is the book where only human-approved chapters live. Rejecting a
change never deletes it from the notebook.

### Tier classification

Every structural file belongs to one of three criticality tiers. The
Mirror UI uses the tier to decide how much friction to add before
approval (simple button, typed-confirmation, typed-confirmation + "I
read the full diff" guard).

| Tier | Label | Examples | GUI friction |
|------|-------|----------|--------------|
| 1 | `cosmetic` | docs, tests, scripts, mockups | one-click approve |
| 2 | `behavioral` | most of `core/`, `aria.py`, `config.yaml` | typed-confirmation of filename |
| 3 | `meta` | `mirror.py`, `self_modification.py`, `quality_gate.py`, `auth_manager.py` | typed-confirmation + "I read the full diff" guard |

```python
from core.cognition.mirror import (
    classify_file_tier,
    TIER_RULES,
    TIER_LABELS,
)

classify_file_tier("core/cognition/mirror.py")   # -> 3
classify_file_tier("core/memory/memory_v2.py")    # -> 2
classify_file_tier("docs/API_REFERENCE.md")       # -> 1
```

- `classify_file_tier(relative_path: str) -> int` — returns 1, 2, or 3.
  Uses forward-slash paths relative to the project root. First match in
  `TIER_RULES` wins; unmatched paths fall back to Tier 1.
- `TIER_RULES: List[Tuple[str, int]]` — ordered `(prefix, tier)` rules.
- `TIER_LABELS: Dict[int, str]` — `{1: "cosmetic", 2: "behavioral", 3: "meta"}`.

### class MirrorManager

```python
from core.cognition.mirror import MirrorManager

mirror = MirrorManager(project_root="/path/to/ARIA")
```

Constructor:

```python
MirrorManager(
    project_root: str,
    mirror_dir: str = "data/mirror",
    config: Optional[Dict] = None,
    memory_system = None,
)
```

**Core primitives:**

```python
mirror.sync()
# Copy live files into main and auto-merge into develop.

mirror.apply_change(relative_path: str, content: str,
                    branch: Optional[str] = None) -> str
# Write + commit a change on `branch` (or the current branch).
# Returns the SHA of the resulting commit, which callers persist so
# they can cherry-pick it on approval. Empty string on failure.

mirror.head_sha(ref: str = "HEAD") -> str
# Return the SHA of the given ref. Empty string on failure.

mirror.validate(relative_path: str) -> ValidationResult
# Syntax + import + test validation on the currently-checked-out branch.
# ValidationResult fields: syntax_ok, import_ok, tests_ok, errors,
# duration_seconds; plus `.all_ok` property.

mirror.list_branches() -> List[Dict]
# Every improve/* branch with commits + diff_summary, used by the Mirror
# queue.

mirror.get_develop_log(limit: int = 20) -> List[Dict]
# Chronological log of the develop branch — the raw audit trail of every
# attempt ARIA has made. Tier-2 and tier-3 entries always show up here
# even if they were rejected.

mirror.status() -> dict
# Snapshot of mirror state: current branch, last sync, pending branches.
```

**Notebook-and-book primitives (new):**

```python
mirror.cherry_pick_branches_to_main(branch_names: List[str]) -> Dict
```

Cherry-picks the head commits of one or more improve branches from
develop into main, then copies the affected files to live. All-or-nothing:
if any cherry-pick fails, main is reset to its starting SHA and live is
left untouched. The improve/* branches are **never deleted** — they
remain in develop as part of ARIA's history.

Return shape:

```python
{
    "success": bool,
    "promoted_files": List[str],      # files copied to live
    "promoted_branches": List[str],   # branches whose commits made it
    "conflict": bool,                 # True if any cherry-pick conflicted
    "conflict_branch": str,           # which branch failed
    "conflict_files": List[str],      # files involved in the conflict
    "error": str,                     # human-readable explanation
}
```

```python
mirror.find_dependents_in_develop(branch_name: str) -> List[str]
```

Heuristic: list other improve/* branches that touch the same files as
`branch_name`. Used by `SelfModifier.preview_reject` to warn the human
before they reject a change that other pending changes may depend on.
This is coarse (same-file overlap, not real dependency analysis); real
dependency surfacing happens at cherry-pick time when git reports a
conflict.

**Existing promotion paths (kept for compatibility):**

```python
mirror.promote(relative_path: str)             # single-file promote
mirror.promote_batch(paths: List[str])         # multi-file promote
mirror.promote_to_main() -> Dict                # merge develop -> main
mirror.rollback(relative_path: str)             # discard change on live
mirror.rollback_branch(branch: str)             # delete an improve branch
```

---

## core.cognition.self_modification

The user-facing wrapper over MirrorManager. Owns the pending store
(`data/mirror/pending_promotions.yaml`), the modification log, and the
status machine (`validated_pending_approval` → `applied` | `rejected`).

### class Modification

Dataclass representing one modification event. All fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | str | Short unique id |
| `timestamp` | str | ISO timestamp |
| `target_file` | str | Relative path |
| `modification_type` | str | `replace` `insert` `delete` `create` `rewrite` `promote` `reject` `reopen` |
| `original_content` | Optional[str] | Previous content (for revert) |
| `new_content` | str | New content |
| `reason` | str | Human-readable reason |
| `initiated_by` | str | `aria` `william` `system` `user` |
| `success` | bool | Whether the modification succeeded |
| `error_message` | Optional[str] | Populated on failure |
| `status` | str | `applied` `rejected` `failed` `validated_pending_approval` |
| `validation_result` | Optional[Dict] | Snapshot of the mirror's `ValidationResult` |
| `commit_sha` | str | **New.** Commit SHA on develop, captured by `write_file` and `cognitive_cycle`. Used by `promote_selected` to cherry-pick the exact commit. |

### class SelfModifier

```python
from core.cognition.self_modification import SelfModifier

mod = SelfModifier()
```

Constructor:

```python
SelfModifier(
    project_root: Optional[str] = None,
    log_path: str = "data/modification_log.yaml",
    backup_dir: Optional[str] = None,
    mirror: Optional[MirrorManager] = None,
    mirror_config: Optional[Dict] = None,
)
```

**Pending queue:**

```python
mod.list_pending_changes() -> List[Dict]
# Only changes in status 'validated_pending_approval'. Additionally
# surfaces raw mirror branches that don't have a YAML entry yet (e.g.
# those produced by the cognitive cycle).

mod.list_rejected_changes() -> List[Dict]
# Changes explicitly rejected by the human. The commits still live in
# develop; reopen them if you change your mind.

mod.list_promoted_changes() -> List[Dict]
# Changes that have been cherry-picked into main and copied to live.

mod.get_pending_change(mod_id: str) -> Optional[Dict]
```

**Rejection workflow:**

```python
mod.preview_reject(mod_id: str) -> Dict
```

Non-destructive preview of what would happen if the given change were
rejected. Returns:

```python
{
    "found": bool,
    "rejectable": bool,
    "target_file": str,
    "status": str,
    "files_touched": List[str],
    "siblings_sharing_files": List[Dict],  # other pending entries with same file
    "git_dependents": List[str],           # from MirrorManager.find_dependents_in_develop
    "warning": str,                        # human-readable, empty if none
}
```

```python
mod.reject_change(
    mod_id: str,
    reason: str = "User rejected mirror promotion",
    initiated_by: str = "user",
) -> Modification
```

**Does not touch git** — only flips the YAML status to `rejected`. The
commit stays in develop so ARIA remembers what was tried. Previously
this method was destructive (deleted the branch); that behavior has
been removed.

```python
mod.reopen_change(
    mod_id: str,
    initiated_by: str = "user",
) -> Modification
```

Bring a previously rejected change back into the pending queue. Only
works when the entry is in `rejected` state. Pure status flip — no
replay, no regeneration (the underlying git commit was never deleted).

**Promotion workflow:**

```python
mod.promote_selected(
    mod_ids: List[str],
    reason: str = "User approved mirror promotion",
    initiated_by: str = "user",
) -> List[Modification]
```

Cherry-pick the given pending changes from develop to main, then copy
affected files to live. All-or-nothing: if any cherry-pick fails, main
is rolled back and **none** of the changes are promoted. Each caller
gets one `Modification` per requested id (either successful or with an
`error_message` explaining the conflict). On success, each YAML entry
flips to status `applied` but **stays in the store** for audit.

```python
mod.approve_change_by_id(mod_id, reason, initiated_by) -> Modification
mod.approve_batch(mod_ids, reason, initiated_by) -> List[Modification]
```

Both are thin wrappers over `promote_selected` — they share the same
cherry-pick semantics and all-or-nothing guarantee.

**Legacy write path (still used by scripts and tools):**

```python
mod.write_file(
    relative_path: str,
    content: str,
    reason: str,
    ...
) -> Modification
```

Writes a file through the mirror pipeline. As of this release, the
resulting commit SHA is captured into `Modification.commit_sha` and
stored in the pending YAML, so the new cherry-pick semantics apply to
these changes too.

**Audit & rollback:**

```python
mod.get_modification_history(limit: Optional[int] = None) -> List[Dict]
# Full replay of the modification log.

mod.restore_from_backup(
    relative_path: str,
    backup_timestamp: Optional[str] = None,
) -> bool
# Restore a file from a previous backup taken before a modification.
```

Example — approve one change, reject another:

```python
pending = mod.list_pending_changes()
# pending[0] -> {'id': 'mod_abc', 'target_file': 'core/x.py', ...}

mod.preview_reject(pending[1]["id"])
# Shows siblings that depend on pending[1]

results = mod.promote_selected([pending[0]["id"]], reason="LGTM")
mod.reject_change(pending[1]["id"], reason="wrong approach")
```

---

## core.infra.auth_manager

Central credential store. Powers the credentials router above and the
`auth` CLI commands.

### class AuthManager

```python
from core.infra.auth_manager import AuthManager

auth = AuthManager.from_config(config)   # or AuthManager.from_env()
```

**State model:**

`get_provider_state(provider) -> str` returns one of:

| State | Meaning |
|-------|---------|
| `active` | This provider is the currently active LLM |
| `configured` | Credential exists but another provider is active |
| `empty` | No credential stored |
| `local` | Provider is local (Ollama) and needs no credential |

**Methods used by the credentials router:**

```python
auth.set_active_provider(provider: str) -> bool
# Mark `provider` as the current LLM. Persists to disk so the next
# process boot uses the same provider.

auth.get_active_provider() -> Optional[str]
# Name of the currently active provider (or None).

auth.get_provider_state(provider: str) -> str
# See table above.

auth.get_key_preview(provider: str) -> Optional[str]
# A redacted preview like 'sk-...abcd' suitable to display in a GUI.
# Never returns the full key.

auth.delete_credential(provider: str) -> bool
# Remove the saved API key for a provider. Returns True if something
# was actually removed.

auth.login_with_key(provider: str, api_key: str) -> bool
# Persist a new API key for `provider` after validating its format.

auth.login_oauth(provider: str, method: str = "auto") -> bool
# Kick off an OAuth flow (browser or device-code fallback).

auth.revoke_oauth(provider: str) -> bool
# Revoke OAuth tokens for a provider.

auth.has_credential(provider: str) -> bool
auth.get_credential(provider: str) -> Optional[str]
auth.status() -> Dict[str, Any]
```

Example — switch active LLM from Python:

```python
auth = AuthManager.from_config(config)
auth.login_with_key("openai", "sk-...")
auth.set_active_provider("openai")
print(auth.get_active_provider())   # -> "openai"
print(auth.get_key_preview("openai"))  # -> "sk-...xxxx"
```
