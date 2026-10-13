# Tools Reference

ARIA has 39+ tools organized by category (plus any number of dynamic MCP tools). Every tool exposes a typed schema for LLM function calling and can be chained in multi-round agent loops.

---

## Web & Network

### web_search

Search the web using DuckDuckGo.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | Search query |
| `num_results` | int | 5 | Max results (max 20) |
| `region` | string | wt-wt | Region filter |
| `time_range` | string | — | Time filter: `d` (day), `w` (week), `m` (month), `y` (year) |

```
search latest Python 3.13 features
```

### web_fetch

Fetch and extract readable content from a URL. Supports CSS selectors and JavaScript rendering.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | *required* | URL to fetch |
| `max_chars` | int | 50000 | Max characters returned |
| `selector` | string | — | CSS selector for specific content |
| `render_js` | bool | false | Force JavaScript rendering (Playwright) |
| `wait_for` | string | — | CSS selector to wait for before extraction |
| `timeout` | int | 30 | Request timeout in seconds |

### http_request

Make HTTP requests to APIs and web services.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | *required* | URL to request |
| `method` | string | GET | HTTP method (GET, POST, PUT, DELETE, PATCH) |
| `body` | string | — | Request body (JSON string) |
| `headers` | string | — | Custom headers as JSON |
| `timeout` | int | 30 | Timeout in seconds |

### browser

Interactive browser with persistent session using accessibility tree snapshots.

> **Limitation:** this tool wraps Playwright's **sync** API, which raises `Playwright Sync API inside the asyncio loop` when called from within a running event loop — i.e. from inside the agent runtime. It works in standalone/sync use; inside the async agent loop, web retrieval falls back to `web_fetch`.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | See actions below |
| `url` | string | — | URL for navigate/tab_new |
| `ref` | int | — | Numeric ref from snapshot for interactions |
| `text` | string | — | Text to type, option to select, or JS code |
| `direction` | string | — | Scroll direction: `up` or `down` |
| `timeout` | int | 30 | Timeout in seconds |
| `frame` | string | — | CSS selector for iframe scoping |
| `stealth` | bool | true | Launch in stealth mode |

**Actions:** `navigate`, `snapshot`, `click`, `type`, `hover`, `select`, `scroll`, `back`, `forward`, `refresh`, `screenshot`, `tab_new`, `tab_list`, `tab_switch`, `tab_close`, `cookies`, `evaluate`, `wait`, `close`

### download

Download files from URLs.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | string | *required* | File URL |
| `filename` | string | — | Save filename |
| `directory` | string | data/downloads | Save directory |

---

## Files & Documents

### file_manager

Manage files on the local filesystem.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `read`, `write`, `append`, `list`, `search`, `info`, `mkdir`, `delete` |
| `path` | string | *required* | File or directory path |
| `content` | string | — | Content to write/append |
| `pattern` | string | * | Search pattern (glob) |

### compress

Create and extract zip and tar.gz archives.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `zip`, `unzip`, `tar`, `untar`, `list` |
| `path` | string | *required* | Archive file path |
| `destination` | string | — | Output directory |
| `files` | string | — | Comma-separated files to add |

### pdf_read

Extract text from PDF files.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | *required* | Path to PDF |
| `pages` | string | — | Page range (e.g. `1-5`, `1,3,5-10`) |
| `max_chars` | int | 100000 | Max characters returned |

### word

Work with Word documents (.docx).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `read`, `create`, `edit`, `info`, `add_table`, `add_image`, `replace`, `style` |
| `path` | string | *required* | Path to .docx file |
| `content` | string | — | Text content or JSON |
| `data` | string | — | JSON data for tables, replacements, styling |
| `image_path` | string | — | Path to image for add_image |
| `image_width` | float | 5.0 | Image width in inches |
| `range` | string | — | Paragraph index or range for styling |

### excel

Work with Excel spreadsheets (.xlsx).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `read`, `create`, `write`, `info`, `add_sheet`, `delete_sheet`, `format`, `formula`, `chart` |
| `path` | string | *required* | Path to .xlsx file |
| `sheet` | string | — | Sheet name |
| `range` | string | — | Cell range (e.g. `A1:D10`, `B2`) |
| `data` | string | — | JSON data for write/create |
| `style` | string | — | JSON style for formatting |
| `chart_type` | string | — | `bar`, `line`, `pie`, `scatter`, `area` |
| `chart_title` | string | — | Chart title |

### powerpoint

Work with PowerPoint presentations (.pptx).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `read`, `create`, `add_slide`, `edit_slide`, `delete_slide`, `add_image`, `add_chart`, `info` |
| `path` | string | *required* | Path to .pptx file |
| `slide_num` | int | — | Slide number (1-based) |
| `title` | string | — | Slide title |
| `content` | string | — | Slide body text |
| `layout` | string | — | `title_slide`, `title_and_content`, `blank`, etc. |
| `image_path` | string | — | Path to image |
| `data` | string | — | JSON chart data |

---

## Code & Execution

### code_exec

Execute Python code in a controlled environment.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `code` | string | *required* | Python code to execute |
| `timeout` | int | 30 | Timeout in seconds (max 60) |

### shell_exec

Execute system commands with security validation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | string | *required* | Shell command |
| `timeout` | int | 60 | Timeout in seconds (max 300) |
| `cwd` | string | — | Working directory |

### calculator

Safely evaluate mathematical expressions (AST-sandboxed).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `expression` | string | *required* | Math expression |

Available functions: `sqrt`, `sin`, `cos`, `tan`, `log`, `log2`, `log10`, `pow`, `floor`, `ceil`, `abs`, `round`, `min`, `max`, `pi`, `e`

---

## Data & AI

### database

Execute SQL against SQLite or PostgreSQL.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `query` (SELECT only), `execute` (mutations), `tables`, `schema` |
| `sql` | string | — | SQL statement |
| `db_path` | string | — | SQLite file path |
| `db_type` | string | sqlite | `sqlite` or `postgres` |
| `table_name` | string | — | Table name for schema |
| `limit` | int | 100 | Max rows returned |
| `connection_string` | string | — | PostgreSQL connection string |

### rag

Document RAG — ingest documents and query with semantic search.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `ingest`, `query`, `list`, `remove` |
| `path` | string | — | File path for ingest/remove |
| `query` | string | — | Search query |
| `num_results` | int | 5 | Chunks to return (max 15) |
| `chunk_size` | int | 800 | Characters per chunk |

Supported formats: PDF, TXT, MD, HTML, CSV, JSON, code files

### translate

Translate text between languages using LLM.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | string | *required* | Text to translate |
| `target_language` | string | *required* | Target language code (en, es, fr, de, ja, zh, etc.) |
| `source_language` | string | — | Source language (auto-detected if omitted) |

### image_generate

Generate images from text prompts (DALL-E or Stability AI).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | *required* | Image description |
| `size` | string | 1024x1024 | `256x256`, `512x512`, `1024x1024` |
| `output_path` | string | — | File path to save |
| `provider` | string | openai | `openai` or `stability` |

---

## Version Control

### git

Local git operations (17 actions, individually hardened).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | See actions below |
| `args` | string | — | Additional arguments |
| `repo_path` | string | — | Path to repository |

**Actions:** `status`, `log`, `diff`, `commit`, `branch`, `checkout`, `pull`, `push`, `stash`, `add`, `init`, `clone`, `remote`, `merge`, `rebase`, `tag`, `blame`

### github

GitHub operations via `gh` CLI.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | See actions below |
| `repo` | string | — | Repository (`owner/name`) |
| `number` | int | — | PR or issue number |
| `title` | string | — | Title for create actions |
| `body` | string | — | Body for create actions |
| `query` | string | — | API path for api action |
| `limit` | int | 10 | Max results for list actions |

**Actions:** `auth_status`, `pr_list`, `pr_view`, `pr_create`, `pr_checks`, `issue_list`, `issue_view`, `issue_create`, `run_list`, `run_view`, `api`

---

## Scheduling & Tasks

### cron

Schedule recurring tasks and reminders.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `add`, `remove`, `list`, `enable`, `disable`, `run` |
| `name` | string | — | Job name |
| `schedule` | string | — | Schedule expression (e.g. `every 5 minutes`, `every day at 09:00`) |
| `task` | string | — | Task description or command |

### todo

Manage persistent todo list (JSON-backed).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `add`, `complete`, `list`, `remove`, `update` |
| `text` | string | — | Todo text |
| `id` | string | — | Todo ID |
| `status` | string | — | `pending`, `done`, `blocked` |

---

## System

### system_info

Monitor system resources.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `overview`, `cpu`, `memory`, `disk`, `processes`, `network` |
| `top_n` | int | 10 | Top processes to show |

### email

Send emails via SMTP.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `send`, `test` |
| `to` | string | — | Recipient(s), comma-separated |
| `subject` | string | — | Subject line |
| `body` | string | — | Body (plain text) |
| `html` | string | — | Body (HTML) |
| `attachment` | string | — | File path to attach |

---

## Google Workspace

Requires [Google OAuth setup](SETUP_GOOGLE_OAUTH.md).

### gmail

Access Gmail via OAuth.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `search`, `read`, `send`, `reply`, `labels` |
| `query` | string | — | Gmail search query |
| `message_id` | string | — | Message ID to read/reply |
| `to` | string | — | Recipient email |
| `subject` | string | — | Email subject |
| `body` | string | — | Email body |
| `max_results` | int | 10 | Max results (max 50) |

### google_calendar

Access Google Calendar via OAuth.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `list`, `create`, `update`, `delete`, `calendars` |
| `calendar_id` | string | primary | Calendar ID |
| `event_id` | string | — | Event ID |
| `summary` | string | — | Event title |
| `description` | string | — | Event description |
| `start` | string | — | Start datetime (ISO 8601) |
| `end` | string | — | End datetime (ISO 8601) |
| `location` | string | — | Event location |
| `attendees` | string | — | Comma-separated emails |
| `days_ahead` | int | 7 | Days ahead for list |
| `max_results` | int | 20 | Max events |

### google_drive

Access Google Drive via OAuth.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `search`, `list`, `read`, `info`, `download` |
| `query` | string | — | Search query |
| `file_id` | string | — | File ID |
| `folder_id` | string | root | Folder ID |
| `download_path` | string | — | Local path to save |
| `max_results` | int | 20 | Max results (max 100) |

---

## Communication

### slack

Interact with Slack workspace. Requires [Slack setup](SETUP_SLACK.md).

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `read_messages`, `send_message`, `react`, `pin` |
| `channel` | string | — | Channel ID |
| `text` | string | — | Message text |
| `timestamp` | string | — | Message timestamp |
| `emoji` | string | — | Emoji name (without colons) |
| `limit` | int | 10 | Max messages to fetch |

---

## Knowledge & Memory

### memory_search

Search ARIA's episodic memory.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | string | *required* | What to search for |
| `limit` | int | 5 | Max memories (max 15) |

### project_knowledge

Save and recall project-specific knowledge.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `save`, `recall`, `summary`, `set_preference` |
| `content` | string | — | Content to save |
| `category` | string | — | `decision`, `pattern`, `bug_fix`, `convention`, `architecture`, `context` |
| `query` | string | — | Search query |
| `key` | string | — | Preference key |
| `value` | string | — | Preference value |
| `limit` | int | 10 | Max results |

### curiosity

Research topics and manage curiosity interests.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `explore`, `add_interest`, `remove_interest`, `status`, `log` |
| `topic` | string | — | Topic to explore/manage |
| `add_to_interests` | bool | true | Add topic to permanent interests |

### feed_watcher

Monitor RSS/Atom feeds and web pages for updates.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `add`, `list`, `scan`, `items`, `mark_read`, `remove` |
| `url` | string | — | Feed or page URL |
| `label` | string | — | Optional label |
| `item_id` | string | — | Item ID to mark read |
| `limit` | int | 10 | Max items |
| `unread_only` | bool | true | Only unread items |

### obsidian

Manage local Obsidian vault for notes.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `list`, `search`, `read`, `write`, `append` |
| `path` | string | — | Relative note path |
| `query` | string | — | Search query |
| `content` | string | — | Content to write/append |

### tmux

Interact with tmux terminal sessions.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `list_sessions`, `capture`, `send_keys`, `select_target` |
| `target` | string | — | Session/window/pane target |
| `text` | string | — | Text to send |
| `lines` | int | 50 | Lines to capture |

---

## Agents

### subagent

Spawn lightweight sub-agents for parallel task execution.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `action` | string | *required* | `spawn`, `status`, `result`, `list` |
| `task` | string | — | Task description |
| `role` | string | — | `researcher`, `coder`, `analyst`, `writer`, `general` |
| `agent_id` | string | — | Agent ID for status/result |
| `wait` | bool | false | Wait for completion |
