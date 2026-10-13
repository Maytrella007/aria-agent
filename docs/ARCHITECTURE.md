# Architecture

Deep-dive into ARIA's internal design. This document privileges the parts of
the system that are load-bearing for self-modification — the cognitive cycle
and the Mirror *notebook-and-book* model — because they are the most
load-bearing, the most unusual, and the most easy to misunderstand.

Honest about what exists, what is half-built, and what is only on paper.

---

## High-Level Overview

```
User Input
    |
    v
[Channel Layer]  Terminal / Telegram / Discord / Slack / API
    |
    v
[Intent Detector] ──> Slash command? ──> Execute (fast path)
    |  NO
    v
[Skill Registry] ──> Skill match? ──> Execute skill
    |  NO
    v
[Agent Loop] ──> LLM + Tool chaining (up to 10 rounds)
    |
    v
[Memory + Neuroscience] ──> Store, consolidate, reflect
    |
    v
Response
```

A second, slower loop runs in parallel inside the process:
reflection → insight evaluation → cognitive cycle → Mirror pending.
That loop never reaches `live` on its own — a human has to cherry-pick.

---

## The Mirror: *notebook-and-book* model

This is the most important section in this document. Everything ARIA writes
about itself flows through it.

### Philosophy: notebook, book, live

ARIA's self-modification world has three states, and each has a very
specific social meaning:

| State     | Git equivalent                        | Meaning                                                      |
|-----------|---------------------------------------|--------------------------------------------------------------|
| `develop` | branch inside `data/mirror/.git`      | **ARIA's personal notebook**. Everything she validates automatically lands here. Nothing is ever deleted. |
| `main`    | branch inside `data/mirror/.git`      | **The curated book**. Only commits that the human explicitly cherry-picked from develop live here. |
| `live`    | the real files under the project root | **The body**. What's actually running. `main` gets copied into `live` during promotion. |

`develop` is ARIA's writing; `main` is what the human published; `live` is
what the organism is actually made of. They are kept deliberately
separate.

See `core/cognition/mirror.py:542-561` for the in-code articulation of
this philosophy.

### Why reject ≠ delete

Standard review systems (Gerrit, Phabricator, GitHub PR reviews) treat a
rejected change as something to erase: revert the commit, delete the
branch, drop the draft. ARIA goes the other way.

**`reject_change` never touches git.** It flips a status field in the
YAML pending store and that's all. The underlying commit still lives in
`develop` forever.

```python
# core/cognition/self_modification.py:497
# Flip the status. Crucially we do NOT remove the entry from the
# YAML and we do NOT touch the underlying improve/* branch in git.
# The change lives on in develop as part of ARIA's history.
```

Reason: ARIA is an agent with episodic memory. If she tries something
and the human rejects it, she needs to be able to *read her own notebook
later* and see exactly what she tried and what got rejected. Erasing
rejected work is erasing part of her honest self-model. It would force
her to pretend the attempt never happened, which is the opposite of the
introspective posture the rest of the system assumes.

A corollary: **reopen is a status flip, not a replay.** Because the
commit is still there, bringing a rejected change back into the queue
just flips `rejected → validated_pending_approval`. No regeneration, no
new LLM call, no risk of drift. See
`core/cognition/self_modification.py:521-591`.

### Cherry-pick atómico

Promotion is all-or-nothing. When the human approves `{A, B, C}`:

```
main HEAD is recorded as main_starting_sha
cherry-pick A  ──> ok
cherry-pick B  ──> conflict
  git cherry-pick --abort
  git reset --hard main_starting_sha   ← main is rolled back
  return { success: False, conflict: True,
           conflict_branch: B, conflict_files: [...] }
```

If *any* cherry-pick in the batch fails, `main` is reset to where it
was and `live` is not touched. The contract is implemented in
`core/cognition/mirror.py:562-706` (`cherry_pick_branches_to_main`) and
surfaced to the SelfModifier layer at
`core/cognition/self_modification.py:656-804` (`promote_selected`).

Crucially, conflicts are **not** errors — they are **structured
information**:

```python
{
  "conflict": True,
  "conflict_branch": "improve/foo",
  "conflict_files": ["core/memory/memory_v2.py"],
  "error": "cherry-pick conflict on improve/foo: depends on changes not in main",
}
```

This lets the GUI say something like *"change B depends on change A;
approve A first or reopen it"* instead of a generic 500. The reason we
can do this cleanly is exactly because `develop` is append-only: git
can replay one commit at a time without worrying about what the state
of the working tree used to be.

### Alternativas descartadas

Four models were considered before notebook-and-book was adopted. Each
was rejected for a specific reason:

| Alternative                 | Rejected because                                                                                   |
|-----------------------------|----------------------------------------------------------------------------------------------------|
| `git revert` on reject      | Leaves a noisy "revert of revert of revert" log. Makes ARIA's introspection of her own log hostile. |
| History rewrite (`rebase -i`) | Mutates SHAs. Any commit ID ARIA remembered in memory or logs goes stale.                         |
| No auto-merge to develop    | Every change becomes a floating branch. `dependents` detection collapses. Operations become O(branches). |
| Cherry-pick selectivo pero sin all-or-nothing | Half-promoted batches leave `main` in an arbitrary state nobody asked for. |

Notebook-and-book is the only model where:
1. Develop is a monotonic append-only log (cheap to reason about).
2. Main only ever moves forward via explicit human action.
3. Rejection is memory-preserving.
4. Promotion is transactional.

### Flujo end-to-end

```
               ┌────────────┐
               │ Reflection │   (LLM: DeepSeek-class)
               └─────┬──────┘
                     v
              ┌──────────────┐
              │ Insight      │   (LLM: filters actionable)
              │ Evaluator    │
              └──────┬───────┘
                     v draft
         ┌───────────────────────┐
         │ CognitiveCycle        │
         │  _process_draft       │
         └──┬────────────────────┘
            │
            │  1. Pre-eval          ─► claude code (Read/Glob/Grep)
            │  2. create_branch     ─► improve/<slug> from develop
            │  3. generate code     ─► claude code (Edit)
            │  4. apply_change      ─► commit on branch, capture SHA
            │  5. validate          ─► syntax + import + tests
            │  6. post-eval review  ─► claude code (judge diff)
            │  7. merge_to_develop  ─► branch merged into develop
            │  8. _store_pending    ─► YAML entry with commit_sha
            v
       ┌─────────────────────────┐
       │   develop (notebook)    │
       │  A → B → C → D → E ...  │   append-only, never touched
       └──────┬──────────────────┘
              │
              │  human opens Review Panel
              │  selects {A, C, E}, clicks Promote
              v
       ┌──────────────────────────┐
       │ cherry_pick_branches_    │
       │ to_main(refs=[A,C,E])    │   all-or-nothing
       └──────┬───────────────────┘
              │   success
              v
       ┌───────────────┐          ┌──────────────┐
       │ main (book)   │ ──copy─► │ live (body)  │
       └───────────────┘          └──────────────┘

              rejection path:
                reject_change(B)
                  ├─ YAML: status "rejected"
                  └─ git:  nothing

              reopen path:
                reopen_change(B)
                  └─ YAML: status "validated_pending_approval"
                     (commit B is still in develop, unchanged)
```

---

## Tier classification

Every file that Mirror can touch has a criticality tier. The tier
decides the approval ceremony the GUI imposes on the human when
promoting. Implemented in `core/cognition/mirror.py:72-116`.

| Tier | Label        | Ceremony                                      | Examples                                                 |
|------|--------------|-----------------------------------------------|----------------------------------------------------------|
| 1    | `cosmetic`   | Single-click approve                          | `docs/`, `tests/`, `scripts/`, `*.md`, `README`          |
| 2    | `behavioral` | Typed filename confirmation before approve   | most of `core/`, `aria.py`, `config.yaml`                |
| 3    | `meta`       | Typed confirmation **+** "I read the full diff" guard | see below                                           |

Tier 3 is the interesting one. These are the files that decide what is
safe to modify. Modifying them is ARIA editing the rules that constrain
ARIA:

```python
# core/cognition/mirror.py:72
TIER_RULES = [
    # Tier 3 — meta-modification of the safety machinery itself
    ("core/cognition/mirror.py",            3),
    ("core/cognition/quality_gate.py",      3),
    ("core/cognition/self_modification.py", 3),
    ("core/cognition/modification_log.py",  3),
    ("core/infra/security.py",              3),
    ("core/infra/auth_manager.py",          3),
    # Tier 2 — runtime behavior, hot path
    ("core/cognition/",                     2),
    ("core/llm/",                           2),
    ("core/memory/",                        2),
    ("core/agents/",                        2),
    ("core/skills/",                        2),
    ("core/tools/",                         2),
    ("core/api/",                           2),
    ("core/channels/",                      2),
    ("core/interaction/",                   2),
    ("core/autonomy/",                      2),
    ("core/infra/",                         2),
    ("aria.py",                             2),
    ("config.yaml",                         2),
]
```

The classifier walks the rules in order and takes the first match.
Anything that doesn't match falls to Tier 1. `classify_file_tier(path)`
is the public entry point.

The GUI is expected to honor this by adjusting the confirmation dialog
per tier — the backend does not enforce the ceremony. That is a deliberate
split of concerns: the backend says "this is tier 3"; the GUI decides
how much friction tier 3 deserves.

---

## División del trabajo: LLM vs coding agent

A structural design decision: **the LLM does reasoning; the coding
agent (Claude Code) does all the technical work.** They are different
kinds of model and we use them for what each is good at.

- **LLM (DeepSeek-class, configurable)** — reflection, insight
  evaluation, generating proposal drafts. Text-in, text-out. Does not
  touch files.
- **Coding agent (Claude Code)** — the three moments where code
  actually has to be read, written, or judged.

The coding agent is invoked at three precise points in the cognitive
cycle:

### 1. Pre-eval gate

Before we spend any tokens generating code, Claude Code is asked to
look at the real target file and decide whether the idea is worth
coding. The agent has `Read`, `Glob`, and `Grep` access. See
`core/cognition/quality_gate.py:271-332` (`_agent_pre_evaluate`):

```python
# core/cognition/quality_gate.py:292
cmd = [agent, "-p", "--output-format", "text", "--max-budget-usd", "0.25"]
if agent == "claude":
    cmd.extend(["--allowedTools", "Read", "Glob", "Grep"])
    cmd.extend(["--dangerously-skip-permissions"])
```

The agent responds with `VERDICT: PROCEED | SKIP` and one sentence.
A SKIP verdict saves the tokens that would have been spent on code
generation and feeds the reason back to the reflection engine so
DeepSeek learns to stop proposing that class of change.

### 2. Code generation

If pre-eval says PROCEED, Claude Code is invoked a second time to
actually write the change — *surgically*, with `Edit`. See
`core/cognition/cognitive_cycle.py:642-715`
(`_generate_code_via_agent`):

```python
# core/cognition/cognitive_cycle.py:677
cmd = [self._coding_agent, "-p", "--output-format", "text",
       "--max-budget-usd", "0.50"]
if self._coding_agent == "claude":
    cmd.extend(["--allowedTools", "Edit,Read,Glob,Grep",
                 "--dangerously-skip-permissions"])
```

The agent runs with its CWD set to the mirror working tree, so every
file it reads or edits lives on `improve/<slug>` — never on live. The
orchestrator then reads the modified file back and runs `ast.parse`
on it before accepting the result.

If Claude Code is not installed, the cycle falls back to LLM full-file
generation with up to 3 retries, then to a targeted-patch splicer
(`_attempt_targeted_patch`). The agent path is the preferred one
because surgical edits preserve the rest of the file reliably; the
fallbacks exist so a dev box without a coding agent can still run the
cycle.

### 3. Post-eval review

Once the code is written and `ast.parse`/`importlib`/tests pass, the
*same* diff is handed back to Claude Code with `Read/Glob/Grep`
permissions and it is asked to judge its own work. See
`core/cognition/quality_gate.py:669-763` (`_agent_review`):

```python
# core/cognition/quality_gate.py:689
prompt = f"""You are reviewing a code change that ARIA (an AI) generated about its own source code.
Your job: determine if this is a REAL improvement or just well-formatted noise.
...
VERDICT: real_improvement / noise / marginal
SCORE: 0.0-1.0
REASON: one sentence explaining your judgment"""
```

The verdict becomes part of `QualityReport.score`. A score below
`min_quality_score` (default `0.4`) causes the branch to be rolled
back *before* it reaches develop, so the human never sees it in the
queue.

### Why not one model for both

LLMs are good at thinking about code; coding agents are good at
touching code. Asking a plain chat LLM to generate a full file is
fragile (it fabricates imports, miscounts indentation, drifts from the
rest of the file). Asking a coding agent to reflect on a philosophical
insight is wasteful and slow. We don't mix the roles.

Agent availability is detected once at orchestrator startup:
`core/cognition/cognitive_cycle.py:717-723` (`_detect_coding_agent`)
uses `shutil.which("claude")` and falls back to `shutil.which("codex")`.

---

## El cognitive cycle end-to-end

Full control flow for `CognitiveCycleOrchestrator.run_cycle` and
`_process_draft`
(`core/cognition/cognitive_cycle.py:162-489`):

1. `ReflectionEngine` produces recent reflections and insights.
2. `InsightEvaluator` scores each insight; the LLM decides which are
   actionable code changes. Output: a list of `ProposalDraft`.
3. Drafts whose `target_file` already has a pending entry are
   skipped (`_get_pending_files`) — one change in flight per file.
4. For each surviving draft, `_process_draft` runs the seven-step
   pipeline:

   | Step | Method                                      | Effect                                                                 |
   |------|---------------------------------------------|------------------------------------------------------------------------|
   | 1    | `QualityGate.pre_evaluate`                  | Claude Code verdict PROCEED/SKIP. SKIP → `pre_eval_rejected`.          |
   | 2    | `MirrorManager.sync` + `create_branch`      | `improve/<slug>` branched from fresh develop.                          |
   | 3    | `_generate_code` (→ `_generate_code_via_agent`) | Claude Code edits file in mirror working tree.                     |
   | 4    | `MirrorManager.apply_change`                | Commits on the branch. **Captures `commit_sha`.**                      |
   | 5    | `MirrorManager.validate`                    | Syntax + import + tests. Failure → branch rolled back.                 |
   | 6    | `QualityGate.evaluate`                      | Post-review. Below threshold → `quality_rejected`, branch rolled back. |
   | 7    | `MirrorManager.merge_to_develop`            | Branch merged. Conflict → `merge_conflict` (branch preserved).         |
   | 8    | `SelfModifier._store_pending_change`        | YAML entry written with `commit_sha` and `status='validated_pending_approval'`. |

5. Every outcome is recorded to episodic memory with an appropriate
   `EmotionalTone` and `importance`
   (`cognitive_cycle.py:495-569`). ARIA literally remembers what she
   tried and how it went.
6. The cycle log (`data/cognitive_cycle_log.yaml`) keeps the last 50
   runs for stats and GUI display.

The pipeline never auto-promotes. Its terminal state is
`validated_pending_approval` — waiting for a human to click.

---

## Modelo de datos

### `Modification` dataclass

Defined at `core/cognition/self_modification.py:30-68`. Every entry in
the pending store, the modification log, and the audit trail is one
of these:

| Field                 | Type               | Purpose                                                                 |
|-----------------------|--------------------|-------------------------------------------------------------------------|
| `id`                  | `str`              | Unique id from `generate_modification_id()`.                            |
| `timestamp`           | `str` (ISO)        | When the change was created.                                            |
| `target_file`         | `str`              | Relative path, forward slashes.                                         |
| `modification_type`   | `str`              | One of `replace`, `insert`, `delete`, `create`, `rewrite`, `promote`, `reject`, `reopen`. |
| `original_content`    | `Optional[str]`    | Snapshot before the change (None for creates).                          |
| `new_content`         | `str`              | Content to write.                                                       |
| `reason`              | `str`              | Why this change exists.                                                 |
| `initiated_by`        | `str`              | `'aria'`, `'william'`, `'system'`, `'user'`.                            |
| `success`             | `bool`             | Did the operation complete without error.                               |
| `error_message`       | `Optional[str]`    | Populated when `success=False`.                                         |
| `status`              | `str`              | See status table below.                                                 |
| `validation_result`   | `Optional[Dict]`   | Serialized `ValidationResult`.                                          |
| `commit_sha`          | `str` **(new)**    | SHA of the commit on develop. Used by `promote_selected` to cherry-pick the exact commit into main. |

The `commit_sha` field is what makes the notebook-and-book model
work: it decouples *what was written* from *which branch name it was
written on*, so promotion doesn't need stable branch names.

### `ValidationResult` dataclass

`core/cognition/mirror.py:29-39`:

| Field              | Type        | Purpose                                   |
|--------------------|-------------|-------------------------------------------|
| `syntax_ok`        | `bool`      | `ast.parse` succeeded.                    |
| `import_ok`        | `bool`      | Module import succeeded in a subprocess.  |
| `tests_ok`         | `bool`      | Affected tests passed (if test runner is enabled). |
| `errors`           | `List[str]` | Human-readable failure messages.          |
| `duration_seconds` | `float`     | Wall-clock cost of the validation run.    |
| `all_ok` (prop)    | `bool`      | All three flags true.                     |

### Modification.status lifecycle

```
           ┌─────────────────────────────────┐
 created ─►│ validated_pending_approval      │──promote─► applied
           └─────┬───────────────────────────┘
                 │ reject                                   ▲
                 v                                          │
           ┌─────────────┐                                  │
           │ rejected    │──reopen──────────────────────────┘
           └─────────────┘

 validation failure anywhere ──► failed
```

The pending YAML keeps every entry **forever**, tagged with one of
those statuses. Queue listing filters by status
(`core/cognition/self_modification.py:305-357`):

- `list_pending_changes()` → only `validated_pending_approval`
- `list_rejected_changes()` → only `rejected`
- `list_promoted_changes()` → only `applied`

### Persistencia en disco

| Path                                     | Content                                                                 |
|------------------------------------------|-------------------------------------------------------------------------|
| `data/mirror/.git/`                      | Standalone git repo with branches `main`, `develop`, `improve/*`.       |
| `data/mirror/aria.py`, `core/`, …        | Mirror working tree — files as they are on the current branch.          |
| `data/mirror/pending_promotions.yaml`    | Append-only list of `Modification.to_dict()` entries, all statuses.     |
| `data/mirror/post_promote_state.yaml`    | Hint to the next boot about whether a restart or module reload is needed after the last promotion. |
| `data/modification_log_full.yaml`        | Full audit log of every `Modification` recorded by `ModificationLogger`. |
| `data/auth/`                             | OAuth tokens, Google client config.                                     |

---

## Notebook operations (SelfModifier public API)

These are the methods the REST router and GUI are expected to call.
All of them are implemented in `core/cognition/self_modification.py`.

| Method                                   | Effect                                                                                     |
|------------------------------------------|--------------------------------------------------------------------------------------------|
| `list_pending_changes()`                 | Return entries with status `validated_pending_approval` + any orphan improve branches.     |
| `list_rejected_changes()`                | Return entries with status `rejected`. Commits still live in develop.                      |
| `list_promoted_changes()`                | Return entries with status `applied`. Full audit trail of human-approved changes.          |
| `get_pending_change(mod_id)`             | Fetch one pending entry by id.                                                             |
| `preview_reject(mod_id)`                 | Non-mutating preview: which files does this change touch, which other pending changes share those files, what will the warning say. Used by GUI to build the reject dialog. |
| `reject_change(mod_id, reason, by)`      | Flip status to `rejected`. **Does not touch git.** Reversible via `reopen_change`.         |
| `reopen_change(mod_id, by)`              | Flip a rejected entry back to `validated_pending_approval`. No replay, no regeneration.    |
| `promote_selected(mod_ids, reason, by)`  | Cherry-pick the given entries from develop to main and copy to live. **All-or-nothing.** On conflict returns structured failures, main is rolled back, nothing hits live. |
| `approve_change_by_id(mod_id, …)`        | Thin wrapper — delegates to `promote_selected([mod_id])`.                                  |
| `approve_batch(mod_ids, …)`              | Thin wrapper — delegates to `promote_selected(mod_ids)`. Same transactional semantics.     |
| `approve_change(path, …)`                | Legacy by-path approval. Takes the first pending entry matching that path. **Warning:** ambiguous when multiple pending entries touch the same file. |

`write_file(path, content, reason, by)`
(`self_modification.py:921-1069`) is the fundamental write operation.
For structural files it runs the full mirror dance: `sync → apply_change
→ validate → _store_pending_change`, and returns a `Modification` in
status `validated_pending_approval`. For non-structural files it writes
live directly and records an `applied` entry.

---

## Event Bus (`core/infra/event_stream.py`)

Thread-safe pub/sub system that routes all events:

```
LLM tokens ──> EventBus ──┬── Terminal subscriber
Tool results ─┘           ├── SSE API subscriber
                          ├── Telegram subscriber
                          ├── Discord subscriber
                          ├── Slack subscriber
                          └── Custom subscribers
```

**Event structure:**
```python
StreamEvent:
    stream: str      # "assistant" | "tool" | "lifecycle" | "error"
    event: str       # "delta" | "start" | "end" | "result" | "thinking"
    data: dict       # Payload
    run_id: str      # Groups related events
    seq: int         # Auto-increment per run_id
    timestamp: float
```

**Subscription modes:** sync callback, blocking queue, async queue.
**Bounds:** Max 50 run_ids, 500 events per run_id.

---

## Memory System (`core/memory/memory_v2.py`)

Two-tier storage with hybrid retrieval:

```
┌─────────────────────┐     ┌──────────────────────┐
│  Experiential Memory│     │  Semantic Memory      │
│  (SQLite)           │     │  (ChromaDB Vectors)   │
│  - Content          │     │  - Embeddings         │
│  - Emotional tone   │     │  - Similarity search  │
│  - Tags & entities  │     │                       │
│  - Decay & strength │     │                       │
└─────────┬───────────┘     └──────────┬────────────┘
          └──────────┬────────────────┘
                     v
          ┌────────────────────┐
          │  Hybrid Search     │
          │  70% Semantic (RRF)│
          │  30% BM25 Lexical  │
          └────────────────────┘
```

Each memory carries: `content`, `context`, `emotional_tone` (one of 11
tones), `emotional_intensity`, `involves_people`, `origin` (`LIVED`,
`REFLECTED`, `INJECTED`, `DISCOVERED`, `INHERITED`), `importance`,
`memory_strength`, `tags`, `consolidated`, `times_recalled`.

Relationships are tracked per person with `trust_level`, `familiarity`,
`feelings_toward`, `communication_style`, and sets of comfortable /
uncomfortable topics.

Core operations: `experience`, `recall`, `recall_enhanced`,
`remember_person`, `forget`, `apply_memory_decay`, `connect_memories`.

Self-modification events are stored here too — every cognitive cycle
outcome becomes an experiential memory
(`cognitive_cycle.py:495-569`), so ARIA can introspect on her own
attempts the same way she introspects on conversations.

---

## Neuroscience Module

Brain-inspired subsystems that run during idle time.

### Memory Consolidation (`core/neuroscience/consolidation.py`)

Simulates hippocampal Sharp Wave Ripples (SWRs):

```
Consolidation Cycle (every 1 hour):
    1. Fetch 20 unconsolidated memories (age > 1 hour)
    2. SWR burst: 10 ripples, 3 memories each
    3. Strengthen replayed memories (boost = 0.15 * replay_strength)
    4. Discover connections (Jaccard similarity + people bonus)
    5. Apply decay to non-consolidated memories
```

### Default Mode Network (`core/neuroscience/dmn.py`)

| Module     | Brain Region                 | Function                                  |
|------------|------------------------------|-------------------------------------------|
| mPFC       | Medial Prefrontal Cortex     | Self-referential processing               |
| PCC        | Posterior Cingulate Cortex   | Autobiographical memory, continuity       |
| Precuneus  | Precuneus                    | Mental imagery, episodic visualization    |

Modes: IDLE, SELF_REFLECTION, MEMORY_RETRIEVAL, FUTURE_THINKING,
SOCIAL_COGNITION.

### Metacognition (`core/cognition/reflection.py`)

- Tracks thought stream (deque, max 20).
- Triggers reflection when: conversation > 10 turns, emotional
  intensity > 0.7, or > 15 accumulated thoughts.
- Saves insights to memory with high importance.
- Feeds into the cognitive cycle orchestrator as the source of drafts.

### Mind Wandering (`core/neuroscience/mind_wandering.py`)

Spontaneous creative associations. Chain length up to 7 hops, every
30 minutes when idle.

---

## Autonomy: Curiosity Engine (`core/autonomy/curiosity.py`)

Autonomous web exploration during idle time:

```
Topic Selection ──> Web Search ──> Fetch Pages ──> Quality Filter ──> RAG Ingest
```

Topic weights: conversation-driven 35%, permanent interests 30%,
serendipity 20%, knowledge gaps 15%. Two-layer quality filter
(heuristic first, LLM only for borderline cases). Daily caps: 10
explorations, 30 LLM calls, 15 searches, 20 fetches. Pauses during
user interactions.

---

## Security (`core/infra/security.py`)

Three selectable modes: `FREE`, `PROTECTED` (recommended),
`PARANOID`. Protected mode blocks `rm -rf /`, `dd if=`, `mkfs`, fork
bombs, `cat /etc/shadow`, `curl | bash`, `shutdown`, `reboot`, etc.
Additional protections: SSRF prevention, Unicode homoglyph detection,
prompt injection detection in external data.

`require_confirmation` is used by Mirror's legacy auto-promote path
(see Risks below).

---

## Auth System (`core/infra/auth_manager.py`)

- API keys from env vars or config.
- OAuth 2.0 with PKCE + state.
- Device Code flow for headless environments.
- Token rotation across multiple profiles per provider.
- Error-based cooldowns: rate limit 30s, billing 5 min, auth 1 hour,
  network 10s.
- Storage: `data/auth/oauth_tokens.yaml`.

---

## Data Directory

```
data/
├── auth/                   # OAuth tokens, Google client config
├── mirror/                 # Standalone git repo + pending_promotions.yaml
├── memories/               # SQLite episodic memory
├── memories_v2/            # Vector embeddings + metadata
├── rag_chroma/             # ChromaDB vector storage
├── projects/               # Project knowledge base
├── reflections/            # Daily reflection files
├── thoughts/               # Thought tracking
├── logs/                   # Activity logs
├── autonomous_logs/        # Autonomous mode logs
├── backups/                # File backups before writes
├── continuity/             # Session snapshots
├── existential/            # Existential reflection state
└── perceptions/            # Image/audio analysis
```

---

## Riesgos conocidos del backend

Honest list. These came out of an audit and have not yet been fixed:

- **Zero locks.** `MirrorManager` and `SelfModifier` do not take any
  lock. If two callers trigger a cognitive cycle concurrently, or if
  a human approves while the cycle is mid-`merge_to_develop`, git
  operations can race. For now we rely on the cycle being
  single-threaded in practice, but this is a bug waiting to bite.
- **`_live_hashes` drift detection has gaps.** Hashes are only
  populated when a file is first touched (`apply_change` /
  `delete_change` / `sync`). Files that live code modified externally
  are not detected as drifted on promote if Mirror never recorded
  their pre-change hash.
- **`require_confirmation` auto-promote path is CLI-only.** When
  `mirror_config["require_confirmation"]` is true (the default),
  `write_file` prompts on stdin. This works for terminal sessions but
  is incompatible with the GUI. The notebook-and-book tests disable
  it explicitly: `sm._confirm_promote = lambda path: False`
  (`scripts/test_notebook_and_book.py:53`). The GUI path must do the
  same or the prompt will deadlock the request.
- **`list_pending_changes` surfaces merged branches as pending.** It
  adds every `improve/*` branch without a YAML entry to the pending
  list, even if that branch's commits have already been cherry-picked
  to main. The filter is "no YAML entry", not "no reachable from main".
- **`approve_change(path, …)` is ambiguous.** If two pending entries
  touch the same file, it takes the first match and ignores the
  second. Callers that actually care which entry they are promoting
  must use `approve_change_by_id` / `promote_selected` instead.
- **Quality gate agent call is blocking.** The cognitive cycle
  subprocess-calls Claude Code up to three times per draft
  (pre-eval, generation, review) with 45-120 second timeouts. A slow
  agent stalls the whole cycle.

---

## Lo que NO está implementado

This section is deliberately in here so the doc doesn't lie.

(The Mirror REST router and the SvelteKit GUI, once listed here as missing,
shipped in 0.8.0: `core/api/mirror_router.py` is mounted at `/api/mirror`
and the GUI under `web/` wires all six pages to the backend through the BFF.
The v3.1 mockups under `docs/gui-mockups/v3.1/` are now historical design
references only.)

- **Mirror locks.** See Risks above.
- **Resend integration.** Planned for outbound notifications (approve
  request emails, promotion receipts). Not started.
- **Multi-user auth.** The system assumes a single human operator.
  There is no per-user permission model, no distinct identities in
  the audit trail beyond the `initiated_by` free-text field.
- **Automatic test runner in mirror validate.** `validate` calls
  `_validate_tests` but that path is gated behind
  `mirror_config["run_tests"]`, and the tests disable it
  (`run_tests: False`) because they don't want pytest overhead. In
  real deployments this is opt-in.

---

## Request Lifecycle (Timing)

| Phase                   | Typical Duration              |
|-------------------------|-------------------------------|
| Intent detection        | ~100ms                        |
| Memory recall           | ~50ms                         |
| System prompt assembly  | ~10ms                         |
| LLM first response      | 1-3s                          |
| Tool agent loop         | 0-30s (up to 10 rounds)       |
| Memory ingestion        | ~50ms                         |
| **Conversation total**  | **2-35s** depending on tools  |
| Cognitive cycle / draft | 30-180s (3 agent subprocess calls + validation + tests) |
| Promote batch (N items) | ~2-5s (N cherry-picks + copy to live) |
