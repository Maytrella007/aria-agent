# Skills Guide

Skills are reusable orchestration layers that combine tools, LLM reasoning, and memory to solve complex tasks.

ARIA supports two types of skills:

- **Coded skills** — Python classes with multi-step orchestration logic (20 built-in)
- **Prompt skills** — YAML files with prompt templates, loaded dynamically (5 included, extensible)

---

## How Skills Work

1. User sends a natural language request
2. ARIA's skill registry matches the request to the best skill (LLM-based, semantic)
3. The skill orchestrates one or more tools, optionally using the LLM for reasoning
4. The result is returned with structured data

Each skill declares `requires_tools` — if a required tool is missing, the skill is unavailable.

Skill selection is 100% LLM-based — no regex triggers. The LLM reads all skill descriptions and decides which one best handles the request.

---

## Prompt-Based Skills (YAML)

Prompt skills are defined entirely by YAML files in `core/skills/`. No Python code needed. They are compatible with the prompt-based skill pattern used by modern AI agents.

### Creating a Custom Skill

Create a file in `core/skills/my_skill.yaml`:

```yaml
name: my_skill
description: "What this skill does (the LLM reads this to decide when to use it)"

prompt_template: |
  Your prompt here.
  Use {query} for the user's input.
  Use {tool_output} for pre-tool results (optional).

# Optional fields:
system: "System prompt for the LLM"
max_tokens: 1000
pre_tool: web_search            # Tool to run before the LLM call
pre_tool_query: "{query}"       # Query template for pre-tool
requires_tools: [web_search]    # Tools this skill needs
examples:                        # Few-shot examples improve quality
  - input: "example user message"
    output: "example response"
```

### YAML Skill Fields

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | No | filename | Skill identifier (must be unique) |
| `description` | Yes | — | What the skill does. The LLM reads this to select it |
| `prompt_template` | Yes | — | Prompt sent to LLM. `{query}` = user input, `{tool_output}` = pre-tool result |
| `system` | No | — | System prompt prepended to the conversation |
| `max_tokens` | No | 800 | Max LLM response length |
| `pre_tool` | No | — | Tool to run before the LLM call (e.g., `web_search`) |
| `pre_tool_query` | No | `{query}` | Query template for the pre-tool |
| `requires_tools` | No | [] | List of tools this skill needs to be available |
| `examples` | No | [] | Few-shot examples as `input`/`output` pairs |

### Hot Reload

Reload YAML skills without restarting ARIA:

```
skills reload
```

### Included Prompt Skills

| Skill | Description |
|-------|-------------|
| `translate` | Translate text between any languages, preserving tone |
| `email_draft` | Draft professional emails from brief instructions |
| `explain_code` | Explain code in plain language step by step |
| `brainstorm` | Generate creative ideas and solutions |
| `meeting_notes` | Organize raw notes into structured summary + action items |

### How Prompt Skills Work Internally

1. ARIA loads all `.yaml`/`.yml` files from `core/skills/` on startup
2. Each file becomes a `DynamicPromptSkill` registered in the `SkillRegistry`
3. The LLM selects skills based on their `description` (same as coded skills)
4. When selected, the skill runs `pre_tool` (if defined), then sends `prompt_template` to the LLM
5. Few-shot `examples` are injected as conversation history for better output quality
6. The `system` prompt sets the LLM persona for the skill

---

## Coded Prompt Skills

### weather

Get current weather and forecast for a location.

**Required tools:** `web_search`

**How it works:**
1. Extract location from query
2. Web search for weather data
3. LLM formats a readable summary (temp, high/low, forecast, alerts)

**Examples:**
```
weather in Madrid today
what's the forecast for San Francisco?
is it going to rain tomorrow?
```

---

## Research & Knowledge

### research

Deep multi-source research on a topic.

**Required tools:** `web_search` (optional: `web_fetch`, `rag`)

**How it works:**
1. Check memory for prior research on topic
2. Web search (5 results)
3. Fetch top 3 source pages (up to 5000 chars each)
4. LLM synthesizes findings: key points, details, sources, gaps
5. Save findings to RAG for future reference

**Examples:**
```
research the latest developments in quantum computing
deep dive into WebAssembly performance
```

### summarize

Summarize a URL, PDF, document, or text.

**Required tools:** none required (optional: `web_fetch`, `pdf_read`, `file_manager`, `web_search`)

**How it works:**
1. Detect source type (URL, PDF, file, raw text)
2. Fetch content from source
3. LLM generates structured summary: title, key points (3-5), summary, notable details

**Examples:**
```
summarize https://example.com/article
summarize /path/to/report.pdf
summarize this: <long text>
```

### daily_brief

Generate a personalized daily briefing.

**Required tools:** `web_search`

**How it works:**
1. Fetch weather for user's location (from memory or fallback)
2. Fetch top news headlines (filtered by user interests if known)
3. Check memory for pending reminders
4. LLM composes polished briefing

**Examples:**
```
give me my daily brief
morning briefing
what's happening today?
```

### knowledge_base

Save and recall project knowledge, decisions, and facts.

**Required tools:** `rag`

**How it works:**
- **Save:** Classify content (decision, pattern, convention, architecture, context), store in RAG + memory
- **Recall:** Search project knowledge, RAG, and memory, synthesize results

**Examples:**
```
remember that the API uses v2 endpoints
recall decisions about the database schema
what do we know about the auth system?
```

### research_monitor

Watch sources and summarize updates.

**Required tools:** `feed_watcher`

**How it works:**
- **Watch:** Add URL to feed watcher
- **Scan:** Check watched sources for new items, summarize with LLM
- **Items:** List unread items

**Examples:**
```
watch https://blog.example.com/feed.xml
check for updates from my sources
scan the news feed
```

### workspace_knowledge

Search and save notes in the local Obsidian vault.

**Required tools:** `obsidian`

**How it works:**
- **Save:** Write content to a note in the vault
- **Read:** Read a specific note
- **Search:** Search the vault for matching notes

**Examples:**
```
save architecture notes to design.md
search the vault for authentication
read the project guidelines note
```

---

## Developer & Operations

### git_ops

Full git workflow management (17 operations).

**Required tools:** `git`

**Operations:** status, log, diff, commit, branch, checkout, push, pull, merge, rebase, stash, tag, blame, add, clone, init, remote, overview

**Special features:**
- Auto-generate commit messages with LLM
- Auto-stage files if nothing is staged
- Conflict detection on merge

**Examples:**
```
what's my git status?
show the last 5 commits
commit these changes with message "fix auth bug"
create branch feature/payments
```

### github_ops

Remote GitHub workflows via `gh` CLI.

**Required tools:** `github`, `git`

**Operations:** clone, pr_list, pr_view, pr_create, pr_checks, issue_list, issue_view, issue_create, run_list, run_view, auth_status, api

**Examples:**
```
clone anthropic/anthropic-sdk-python
list open pull requests
show PR #42
check CI status for this PR
```

### file_ops

Smart file operations: find, organize, compress.

**Required tools:** `file_manager` (optional: `compress`)

**Examples:**
```
find all PNG files in my documents
compress the project folder into a zip
extract archive.tar.gz to Downloads
organize my desktop files by type
```

### schedule

Create reminders, cron tasks, and calendar events.

**Required tools:** `cron` (optional: `google_calendar`)

**How it works:**
- Parse time expressions: `every N minutes`, `at HH:MM`, `in N minutes`
- Calendar events created via Google Calendar if authenticated
- Cron jobs for recurring tasks

**Examples:**
```
remind me in 30 minutes to call John
set a reminder every day at 9:00 to check email
schedule a meeting tomorrow at 2pm
```

### quick_task

Execute system commands and quick automation.

**Required tools:** `shell_exec`

**Built-in patterns:** port check, kill process, ping, install package, disk usage, memory, processes, network, uptime

**Safety:** Blocks dangerous commands (`rm -rf /`, `mkfs`, `dd`, `chmod 777 /`, fork bombs)

**Examples:**
```
check what's using port 8080
what's my disk usage?
show top processes
check network connections
```

### coding_agent

Delegate programming tasks to external AI coding agents.

**Required tools:** `shell_exec`

**Supported agents:** Claude Code, Codex, OpenCode, Aider

**How it works:**
1. Detect which coding agent is installed
2. Build and execute shell command (300s timeout)
3. Format output with LLM

**Examples:**
```
write a Python script to parse JSON files
use Claude Code to refactor the API
fix the authentication bug
```

### terminal_session

Inspect and interact with tmux sessions.

**Required tools:** `tmux`

**Examples:**
```
list my tmux sessions
capture output from the build session
send 'npm test' to the dev pane
```

---

## Productivity

### data_analysis

Analyze data with calculations, queries, and statistics.

**Required tools:** none required (optional: `calculator`, `database`, `code_exec`)

**Analysis types:** calculation, SQL query, statistics, smart analysis (Python code generation)

**Examples:**
```
calculate 15% of 2340
what's the average of 10, 20, 30, 40, 50?
query the users table for active accounts
```

### doc_create

Create Word, Excel, or PowerPoint documents.

**Required tools:** none (requires LLM)

**How it works:**
1. Detect document type from query
2. LLM generates structured content
3. Create document with appropriate tool (word/excel/powerpoint)

**Examples:**
```
create a Word document about project planning
generate an Excel spreadsheet with Q4 sales data
make a PowerPoint for the team meeting
```

### gmail_assistant

Read, search, and reply to Gmail. Requires [Google OAuth](SETUP_GOOGLE_OAUTH.md).

**Required tools:** `gmail`

**Operations:** search, read, reply (draft only), inbox check

**Examples:**
```
check my inbox
search for emails from GitHub
read the latest email about the project
help me reply to that meeting request
```

### inbox_triage

Review unread mail and create action list. Requires [Google OAuth](SETUP_GOOGLE_OAUTH.md).

**Required tools:** `gmail`

**How it works:**
1. Fetch up to 10 unread emails
2. Classify each: HIGH (urgent, asap, deadline), MEDIUM (meeting, invoice, review), LOW (everything else)
3. Detect action needed (reply/review)
4. Optionally create follow-up todos for high-priority items

**Examples:**
```
triage my inbox
review unread emails and create tasks
what needs immediate attention?
```

### meeting_prep

Prepare for upcoming meetings. Requires [Google OAuth](SETUP_GOOGLE_OAUTH.md).

**Required tools:** `google_calendar` (optional: `gmail`, `google_drive`, `project_knowledge`)

**How it works:**
1. Fetch upcoming calendar events (next 7 days)
2. Match meeting from query or pick first
3. Multi-source context: related emails, docs, project knowledge, memory
4. LLM synthesizes meeting brief: purpose, context, open questions, suggested agenda

**Examples:**
```
prep for my next meeting
brief for the product review
what should I know about the standup?
```

### slack_assistant

Read Slack channels and summarize discussions. Requires [Slack setup](SETUP_SLACK.md).

**Required tools:** `slack`

**Examples:**
```
read the general channel
summarize the engineering channel
send "Deploy complete" to C0123456789
```
