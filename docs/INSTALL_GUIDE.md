# ARIA — Installation Guide

> Reference document for the unified installation script.
> Generated 2026-04-12 for review and approval before deployment.

---

## Table of Contents

1. [Overview](#overview)
2. [Script Architecture](#script-architecture)
3. [Prerequisites](#prerequisites)
4. [Installation Modes](#installation-modes)
5. [Network Connectivity Check](#network-connectivity-check)
6. [Backend Module](#backend-module)
7. [Frontend Module](#frontend-module)
8. [Auth/Email Module](#authemail-module)
9. [Coding Agents](#coding-agents)
10. [Detailed Execution Flow](#detailed-execution-flow)
11. [Production Configuration](#production-configuration)
12. [Security](#security)
13. [Troubleshooting](#troubleshooting)
14. [Differences from Previous setup.sh](#differences-from-previous-setupsh)

---

## Overview

ARIA's installation system consists of 5 modular bash scripts covering the complete project setup: Python backend, SvelteKit frontend, email OTP authentication, and production deployment.

```
install/
  common.sh        Shared utilities (colors, platform detection, helpers)
  backend.sh       Python environment, dependencies, Playwright, embedding model
  frontend.sh      Node.js, npm, SvelteKit build, Nginx, SSL
  auth-email.sh    Email configuration, Resend OTP, domains, security
  install.sh       Main orchestrator (entry point)
```

### Quick Start

```bash
# From the ARIA/ project root
chmod +x install/install.sh
./install/install.sh              # Full interactive install
./install/install.sh --docker     # Docker-only deployment
./install/install.sh --dev        # Quick dev setup (no agents, no Resend)
./install/install.sh --minimal    # Backend only (no GUI)
./install/install.sh --dry-run    # Preview what would be done (no changes)
```

### Estimated Times

| Mode | First Install | Subsequent |
|------|--------------|------------|
| Full | ~15-20 min | ~2-5 min |
| Docker | ~10-20 min | ~1-2 min |
| Dev | ~10-15 min | ~2-5 min |
| Minimal | ~5-10 min | ~1-2 min |

> **WSL on /mnt/c/**: Operations are 5-10x slower on Windows-mounted filesystems. Move to `~/` for better performance.

---

## Script Architecture

### Module Diagram

```
install.sh (orchestrator)
    │
    ├── source common.sh
    │     ├── detect_platform()      → ARIA_OS, ARIA_PKG_MGR, ARIA_IS_WSL, ARIA_ARCH
    │     ├── check_disk_space()     → Verifies minimum free space
    │     ├── check_wsl_path()       → Performance warning for /mnt/c/
    │     ├── check_network()        → Internet connectivity check (pypi, npm, huggingface)
    │     ├── validate_email()       → Email regex validation
    │     ├── generate_secret()      → Hex token (64 chars, 256 bits)
    │     ├── env_set()              → Safe .env writer (no secrets in process list)
    │     ├── cleanup_on_interrupt() → Ctrl+C trap handler
    │     └── Helpers: ok/warn/fail/step/info/ask, sedi, has_cmd, read_env_var
    │
    ├── source backend.sh
    │     ├── backend_check_prerequisites()  → Python, git, ffmpeg, curl, disk
    │     ├── backend_setup_venv()           → Create/validate .venv
    │     ├── backend_install_deps()         → pip install (with Python 3.13 fix)
    │     ├── backend_setup_playwright()     → Chromium + system deps (~280MB)
    │     ├── backend_download_model()       → sentence-transformers (~90MB)
    │     ├── backend_create_dirs()          → data/{auth,mirror,conversations,...}
    │     ├── backend_validate_env()         → LLM keys, .env permissions
    │     ├── backend_setup_docker()         → Build Docker image
    │     └── backend_health_check()         → Polling /api/status (120s timeout)
    │
    ├── source frontend.sh
    │     ├── frontend_validate_node()       → Node 18+ (recommends 22)
    │     ├── frontend_check_build_tools()   → gcc, make, Xcode CLI
    │     ├── frontend_npm_install()         → npm ci + validate better-sqlite3
    │     ├── frontend_build()               → SvelteKit build + validation
    │     ├── frontend_generate_nginx()      → Reverse proxy config (HSTS, CSP, rate limit)
    │     ├── frontend_ssl_guidance()        → Certbot / Let's Encrypt
    │     └── frontend_configure_env()       → ORIGIN, CORS
    │
    └── source auth-email.sh
          ├── auth_collect_emails()          → Primary + additional (detects existing)
          ├── auth_setup_resend()            → API key + verification + FROM (detects existing)
          ├── auth_generate_secret()         → ARIA_INTERNAL_SECRET
          ├── auth_configure_domain()        → Dev vs production
          ├── auth_dns_guidance()            → SPF, DKIM, DMARC (with rua=)
          ├── auth_security_checks()         → .env permissions, .gitignore, .dockerignore
          ├── auth_send_test_email()          → Test email via Resend (non-interactive)
          ├── auth_dev_fallback()            → Dev mode without Resend
          └── auth_firewall_guidance()       → UFW rules
```

### Design Decisions

1. **No `set -e`**: The script uses `set -uo pipefail` but NOT `set -e`. Functions return `0` even for non-critical warnings; critical failures call `fail()` which does `exit 1`. This avoids the `set -e` trap where a warning return code aborts the entire install.

2. **Questions first, installs second**: All interactive prompts happen in Phase 1, before any long-running operations. Once configuration is complete, the user can step away while Phase 2 runs unattended.

3. **Safe secret handling**: The `env_set()` function uses `awk` to write secrets to `.env`, avoiding `sed` command-line arguments that would expose values in `/proc/*/cmdline`.

4. **Interrupt safety**: A `trap` on INT/TERM displays a recovery message. The script is designed to be re-run safely — it detects existing venvs, node_modules, .env values, and secrets.

---

## Prerequisites

### Minimum (all modes)

| Dependency | Version | Purpose | Disk Space |
|------------|---------|---------|------------|
| Python | >= 3.10 | Backend, API server | ~1.5GB (venv) |
| git | any | Mirror system, version control | — |
| curl | any | API verifications, health checks | — |
| **Total minimum** | | | **~2GB** |

### Full Mode (additional)

| Dependency | Version | Purpose |
|------------|---------|---------|
| Node.js | >= 18 (recommended 22) | SvelteKit frontend |
| npm | >= 9 | Node package management |
| gcc/g++/make | any | Compile better-sqlite3 native module |
| ffmpeg | any | Audio processing (pydub, SpeechRecognition) |

### Docker Mode (additional)

| Dependency | Version | Purpose |
|------------|---------|---------|
| Docker | >= 20 | Containerization |
| docker compose | v2 | Orchestration |

### Production (additional)

| Dependency | Version | Purpose |
|------------|---------|---------|
| Nginx | any | Reverse proxy |
| certbot | any | SSL/TLS via Let's Encrypt |

---

## Installation Modes

### Full Mode (`./install/install.sh`)

Installs everything: Python backend, SvelteKit frontend, authentication, coding agents. Default, interactive mode.

**Optional flags:**
- `--skip-agents` — Don't install claude/codex/aider/opencode
- `--skip-playwright` — Don't install Chromium (web_fetch with JS won't work)
- `--skip-model` — Don't download embedding model (downloads on first use)
- `--dry-run` — Preview all steps without executing anything
- `--verify` — Run frontend smoke test after build

### Dev Mode (`--dev`)

Quick setup for developers. Automatically:
- Skips Resend configuration
- Skips coding agents
- Disables FastAPI auth (empty ARIA_INTERNAL_SECRET)
- Uses localhost defaults

### Minimal Mode (`--minimal`)

Backend Python only. No Node.js, no frontend build, no GUI. For terminal-only usage (`python aria.py`).

### Docker Mode (`--docker`)

Validates `.env`, configures auth/email, builds Docker image, starts container. The Dockerfile already includes Playwright, embedding model, and frontend build.

### Dry-Run Mode (`--dry-run`)

Prints a numbered list of every step the installer would execute, without modifying anything. Useful for reviewing the plan before committing, or for documenting what a given mode does on a specific platform.

```bash
./install/install.sh --dry-run           # Preview full install
./install/install.sh --dev --dry-run     # Preview dev mode
./install/install.sh --docker --dry-run  # Preview docker mode
```

Output includes:
- All numbered steps (prerequisites, venv, deps, Playwright, model, frontend, agents, etc.)
- Which steps are skipped based on mode and flags
- Detected platform (`linux`/`darwin`/`wsl`), architecture, and project root

---

## Network Connectivity Check

Before downloading dependencies (pip, npm, model, Docker build), the installer checks internet connectivity by reaching:

1. `https://pypi.org` (Python packages)
2. `https://registry.npmjs.org` (Node packages)
3. `https://huggingface.co` (embedding model)

If all three are unreachable, a warning is shown but the installer continues. This lets the user diagnose connectivity issues before a silent `pip install` failure midway through.

The check runs via `check_network()` in `common.sh` and sets `ARIA_NETWORK_OK=true/false`.

---

## Backend Module

### `backend_check_prerequisites()`

Checks presence and version of system dependencies:

- **Python 3.10+**: Required. Fails if missing or too old.
- **git**: Required for the mirror system.
- **ffmpeg**: Optional. Without it, audio perception won't work.
- **curl**: Optional. Without it, API verifications are skipped.
- **Disk space**: Minimum 2GB. Chromium (~280MB) + model (~90MB) + venv (~1.5GB).

### `backend_setup_venv()`

- Creates `.venv/` if it doesn't exist
- If it exists, verifies the venv Python is >= 3.10 (may be outdated if system Python was upgraded)
- Upgrades pip, setuptools, and wheel inside the venv

### `backend_install_deps()`

- Installs `requirements.txt` via pip
- **Python 3.13 fix**: Installs `onnxruntime>=1.20.0` BEFORE chromadb to avoid a compilation conflict documented in requirements.txt

### `backend_setup_playwright()`

- Runs `playwright install chromium` inside the venv (~280MB download)
- On Linux/WSL: installs system dependencies with `playwright install-deps` (requires sudo)
- Verification: imports playwright and checks it works
- **Non-critical**: If it fails, ARIA works without JS rendering in web_fetch

### `backend_download_model()`

- Downloads `paraphrase-multilingual-MiniLM-L12-v2` from Hugging Face (~90MB)
- Cached in `~/.cache/huggingface/`
- Retries: 3 attempts with progress messages
- Verification: generates a test embedding and checks dimension = 384
- **Non-critical**: If it fails, downloads on first use of semantic memory

### `backend_create_dirs()`

Creates the data directory structure:

```
data/
  auth/           → SQLite session database (permissions 700)
  mirror/         → Self-modification mirror system
  conversations/  → Conversation history
  backups/        → Backups
  reflections/    → Cognitive cycle reflections
```

### `backend_health_check()`

- Polls `http://localhost:8000/api/status` every 5 seconds
- Maximum timeout: 120 seconds (consistent with Dockerfile `start_period`)
- On failure: shows diagnostics (process running, port in use)

---

## Frontend Module

### `frontend_validate_node()`

- Checks Node.js >= 18, recommends 22 LTS
- Checks npm >= 9
- Vite 8 and TypeScript 6 (used in this project) work best with Node 22

### `frontend_check_build_tools()`

`better-sqlite3` is a native C++ module used for the authentication database. It needs:

| Platform | Requirement |
|----------|-------------|
| Linux/WSL | `build-essential` (gcc, g++, make) |
| macOS | Xcode CLI tools (`xcode-select --install`) |

### `frontend_npm_install()`

- Uses `npm ci` if `package-lock.json` exists (faster, deterministic)
- Verifies `better-sqlite3` compiled correctly by checking for the `.node` binary
- If compilation fails, suggests `npm rebuild better-sqlite3`

### `frontend_build()`

- Runs `npx svelte-kit sync` (generates types)
- Runs `npm run build` (Vite + adapter-node)
- Validates the build produced:
  - `web/build/index.js` — Node server entry point
  - `web/build/client/` — Static assets (CSS, JS, images)
  - `web/build/server/` — SSR bundle
- Shows build size

### `frontend_generate_nginx()`

Generates `deploy/nginx-aria.conf` with:

- HTTP → HTTPS redirect
- **HSTS** header (`max-age=31536000; includeSubDomains`)
- **Content-Security-Policy** (default-src 'self', script/style 'unsafe-inline')
- **Permissions-Policy** (camera, microphone, geolocation disabled)
- Proxy pass to SvelteKit (port 3000)
- **Rate limiting** for `/api/auth/` endpoints (5 req/min burst 5)
- WebSocket/SSE support for AI response streaming
- Aggressive caching for immutable assets (`/_app/immutable/`)
- `http2 on` directive (compatible with Nginx >= 1.25)

> **FastAPI is NOT exposed** — SvelteKit acts as BFF (Backend-For-Frontend).

### `frontend_ssl_guidance()`

Shows instructions for obtaining an SSL certificate with certbot:

```bash
sudo certbot --nginx -d aria.yourdomain.com --email you@email.com --agree-tos
```

### `frontend_configure_env()`

Configures `ARIA_ORIGIN` and `ARIA_CORS_ORIGINS` in `.env` using `env_set()`.

> **CRITICAL**: Without `ORIGIN` configured correctly, SvelteKit rejects ALL POST requests with a CSRF error in production. Additionally, session cookies have `secure: true` in production, so **SSL is mandatory** for login to work.

---

## Auth/Email Module

### Authentication Flow

```
User            SvelteKit (BFF)     SQLite          Resend          FastAPI
  │                  │                  │               │               │
  │ Email ──────────►│                  │               │               │
  │                  │ Check whitelist──►│               │               │
  │                  │◄─── OK ─────────│               │               │
  │                  │ Generate OTP     │               │               │
  │                  │ Store code ──────►│               │               │
  │                  │ Send email ──────────────────────►│               │
  │◄─── Email with code ──────────────────────────────-─│               │
  │                  │                  │               │               │
  │ Code ───────────►│                  │               │               │
  │                  │ Verify code ─────►│               │               │
  │                  │◄─── Match ───────│               │               │
  │                  │ Create session ──►│               │               │
  │                  │ Set cookie       │               │               │
  │◄── Session OK ──│                  │               │               │
  │                  │                  │               │               │
  │ API request ────►│ Proxy + X-Internal-Auth ────────────────────────►│
  │◄─── Response ───│◄────────────────────────────────────── Response──│
```

### `auth_collect_emails()`

- **Detects existing config**: If `ARIA_ALLOWED_EMAILS` already has non-placeholder values, asks "Change them? [y/N]" instead of re-prompting.
- **Primary email**: Required. Validated with regex, normalized to lowercase.
- **Additional emails**: Optional. Added as comma-separated list.
- Written to `.env` via `env_set()`.

> **Note**: The `allowed_emails` SQLite table is seeded from this variable on first SvelteKit start (`db.ts` line 44). Seeding only happens when the table is empty. To resync after re-running setup with new emails, delete `data/auth/auth.db` and restart.

### `auth_setup_resend()`

1. **Detects existing config**: If `RESEND_API_KEY` already has a non-placeholder value, asks "Change it? [y/N]".
2. Requests Resend API key (`re_xxxx`)
3. Validates format (prefix `re_`, length >= 20)
4. **Verifies with real API call** to `https://api.resend.com/domains` (GET)
5. Configures `RESEND_FROM_EMAIL`:
   - Free tier: `ARIA <onboarding@resend.dev>` (only sends to account holder's email)
   - Custom domain: `ARIA <aria@yourdomain.com>`

> **Free Tier Limitation**: Resend free tier only allows sending to the account holder's email. If `ARIA_ALLOWED_EMAILS` includes other emails, those users won't receive OTPs. For multiple users, you need a verified domain in Resend.

### `auth_generate_secret()`

Generates `ARIA_INTERNAL_SECRET` (64 hex characters, 256 bits) with fallbacks:

1. `python3 secrets.token_hex(32)` (preferred, CSPRNG)
2. `openssl rand -hex 32` (CSPRNG)
3. `/dev/urandom` + `xxd` (CSPRNG)

This secret is used as the `X-Internal-Auth` header in SvelteKit → FastAPI requests. If empty, FastAPI skips auth verification (development mode only).

### `auth_send_test_email()`

Sends a test email via Resend API to verify the pipeline works end-to-end. Not a real OTP — it's a setup confirmation message.

The decision to send the test email is collected during Phase 1 (interactive), but the actual send happens in Phase 2 (automated). This keeps all prompts upfront so the user can walk away during installation.

### `auth_dev_fallback()`

If Resend is not configured and mode is development:
- Offers to disable FastAPI auth (clears `ARIA_INTERNAL_SECRET`)
- Shows warning about unauthenticated API access
- Suggests terminal-only usage as alternative

---

## Coding Agents

In **full mode** (unless `--skip-agents` is passed), the installer asks the user which coding agents to install during Phase 1 (interactive), then installs them in Phase 2 (automated).

```
  ℹ Coding agents for the self-modification system:
    1) Claude Code  — Anthropic  (requires OAuth login after setup)
    2) Codex        — OpenAI     (uses OPENAI_API_KEY from .env)
    3) Aider        — Multi-LLM  (uses LLM key from .env)
    4) OpenCode     — Open-source (uses LLM key from .env)
    5) All of the above
    6) None (skip)

    Which agents to install? (e.g. 1,3 or 5 for all) [5]:
```

The user can select multiple agents by entering comma-separated numbers (e.g. `1,3` for Claude Code + Aider). Default is `5` (all).

| Agent | Install method | Purpose |
|-------|---------------|---------|
| **Claude Code** | `npm install -g @anthropic-ai/claude-code` | Anthropic's CLI coding agent |
| **Codex** | `npm install -g @openai/codex` | OpenAI's CLI coding agent |
| **Aider** | `pip install aider-chat` | Terminal-based AI pair programmer |
| **OpenCode** | `curl -fsSL https://opencode.ai/install \| sh` | Open-source coding agent |

After installation, a summary shows which agents are available:

```
  ℹ Agent status:
    ✓ claude
    ✓ codex
    · aider (not installed)
    · opencode (not installed)
```

### Post-install authentication

After installation, each agent needs access to an LLM provider:

| Agent | Authentication | Action required |
|-------|---------------|-----------------|
| **Claude Code** | OAuth (browser login) | Run `claude` once after setup — opens browser for interactive login |
| **Claude Code** | API key (alternative) | Set `ANTHROPIC_API_KEY` in your shell environment |
| **Codex** | API key | Uses `OPENAI_API_KEY` from `.env` — no extra step |
| **Aider** | API key | Uses whichever LLM key is in `.env` — no extra step |
| **OpenCode** | API key | Uses whichever LLM key is in `.env` — no extra step |

> **Claude Code is the only agent that requires a separate login step.** The installer prints a reminder after installation. If you skip it, the cognitive cycle will fall back to another available agent.

> **Note**: All four are optional. ARIA works without them, but the self-modification/mirror system uses whichever are available. Install at least one for full functionality.

---

## Detailed Execution Flow

### Phase 1: Interactive Configuration (upfront)

All questions are asked before any long-running operations. This includes the test email prompt — the user decides now, the email is sent later in Phase 2.

```
[1/N] Configuration...
      Your email: user@example.com
      ✓ Primary email: user@example.com
      ✓ Emails configured in .env
      Resend API key: re_xxx...
      ✓ API key verified
      ✓ Sender: ARIA <onboarding@resend.dev>
      ✓ Internal secret generated
      Deployment: 1) Local  2) Production
      LLM provider: 1) DeepSeek ...
      ✓ DeepSeek configured
      Send a test email to user@example.com after setup? [Y/n]: Y
      ✓ Configuration complete. Starting automated installation...
      You can step away — the rest runs unattended.
```

### Phase 2: Automated Installation (unattended)

Begins with a network connectivity check, then proceeds with all installations.

```
       ℹ Checking internet connectivity...
       ✓ Internet reachable

[2/N]  Checking system prerequisites...
       ✓ Python 3.12.3
       ✓ git 2.43.0
       ✓ Sufficient disk space

[3/N]  Setting up Python virtual environment...
       ✓ Venv created → .venv/
       ✓ pip/setuptools/wheel upgraded

[4/N]  Installing Python dependencies...
       ✓ Python dependencies installed

[5/N]  Installing Playwright and Chromium (~280MB)...
       ✓ Chromium installed via Playwright

[6/N]  Downloading embedding model (~90MB)...
       ✓ Embedding model ready

[7/N]  Creating data directories...
       ✓ data/ directories created

[8/N]  Checking Node.js...
       ✓ Node.js v22.12.0

[9/N]  Checking build tools...
       ✓ Build tools ready

[10/N] Installing Node.js dependencies...
       ✓ Dependencies installed (npm ci)
       ✓ better-sqlite3 native module compiled

[11/N] Building SvelteKit frontend...
       ✓ Build validated (4.2M) → web/build/
```

---

## Production Configuration

### Deployment Checklist

- [ ] Server with at least 4 vCPU, 8 GB RAM (e.g. Hetzner CX32)
- [ ] Domain configured with DNS pointing to server
- [ ] Docker and docker compose installed
- [ ] Run `./install/install.sh --docker`
- [ ] Install Nginx config: `sudo cp deploy/nginx-aria.conf /etc/nginx/sites-available/aria`
- [ ] Enable site: `sudo ln -sf /etc/nginx/sites-available/aria /etc/nginx/sites-enabled/`
- [ ] Add rate limit zone to `/etc/nginx/nginx.conf` (see generated config comments)
- [ ] Obtain SSL: `sudo certbot --nginx -d yourdomain.com`
- [ ] Configure firewall (only ports 22, 80, 443)
- [ ] Verify: `curl https://yourdomain.com`

### Ports

| Port | Service | Exposed? |
|------|---------|----------|
| 3000 | SvelteKit (frontend + BFF) | localhost only (127.0.0.1) |
| 8000 | FastAPI (backend API) | localhost only (127.0.0.1) |
| 443 | Nginx HTTPS | Public |
| 80 | Nginx HTTP (redirect) | Public |

> FastAPI is NEVER exposed publicly. SvelteKit acts as BFF and proxies authenticated requests via `X-Internal-Auth`.

### Container Resources

Defined in `docker-compose.yml`, optimized for Hetzner CX32:

```yaml
deploy:
  resources:
    limits:
      memory: 6g
      cpus: '3.5'
    reservations:
      memory: 2g
      cpus: '1.0'
```

`shm_size: '2gb'` is required for Playwright/Chromium.

### Environment Variables

`docker-compose.yml` sets `NODE_ENV=production` and `PYTHONUNBUFFERED=1`. All other variables are read from `.env` via `env_file`. `ARIA_ORIGIN` is **not** hardcoded in docker-compose — it comes from `.env` and is passed to SvelteKit via `supervisord.conf`.

---

## Security

### Sensitive Files

| File | Contains | Protection |
|------|----------|------------|
| `.env` | API keys, secrets | `chmod 600`, in `.gitignore` |
| `data/auth/auth.db` | Sessions, OTP codes | Directory `chmod 700` |
| `client_secret_*.json` | OAuth credentials | In `.gitignore` and `.dockerignore` |

### Secret Handling

- API keys are read with `read -rs` (suppressed echo)
- Secrets are written to `.env` via `env_set()` (uses `awk`, never appears in process list)
- `generate_secret()` uses CSPRNG (python3 secrets / openssl / urandom)
- Secret values are never printed to terminal

### Internal Secret (ARIA_INTERNAL_SECRET)

- Secures SvelteKit → FastAPI communication
- If empty: FastAPI skips auth check (development only)
- To rotate: regenerate and update `.env`, then restart

### Session Cookies

- `httpOnly: true` — Not accessible by JavaScript
- `sameSite: lax` — Basic CSRF protection
- `secure: true` in production — Requires HTTPS
- Duration: 30 days
- `NODE_ENV=production` is set in both `supervisord.conf` and `docker-compose.yml`

### OTP Codes

- 6 digits generated with `crypto.randomInt()` (CSPRNG)
- Expire in 10 minutes
- Maximum 5 attempts per code
- Constant-time comparison (prevents timing attacks)
- 60-second cooldown between sends

### Nginx Security Headers

The generated `deploy/nginx-aria.conf` includes:

| Header | Value |
|--------|-------|
| Strict-Transport-Security | `max-age=31536000; includeSubDomains` |
| Content-Security-Policy | `default-src 'self'; script-src 'self' 'unsafe-inline'; ...` |
| X-Frame-Options | `SAMEORIGIN` |
| X-Content-Type-Options | `nosniff` |
| Referrer-Policy | `strict-origin-when-cross-origin` |
| Permissions-Policy | `camera=(), microphone=(), geolocation=()` |

Rate limiting is configured for auth endpoints: `5 req/min` with burst of 5.

---

## Troubleshooting

### Error: "CSRF check failed" in production

**Cause**: `ARIA_ORIGIN` not set or doesn't match the domain.

**Fix**: Ensure `.env` has `ARIA_ORIGIN=https://yourdomain.com`. This is passed to SvelteKit via `supervisord.conf` as the `ORIGIN` environment variable.

### Error: Login doesn't work in production

**Cause**: Session cookies require `secure: true` in production, which needs HTTPS.

**Fix**: Set up SSL with certbot before attempting production login. Verify `NODE_ENV=production` is set (it's in both `docker-compose.yml` and `supervisord.conf`).

### Error: npm install fails with better-sqlite3

**Cause**: Missing C++ build tools.

**Fix**:
```bash
# Ubuntu/Debian
sudo apt install build-essential python3

# macOS
xcode-select --install

# Then retry
cd web && npm rebuild better-sqlite3
```

### Terrible performance in WSL

**Cause**: Project is on `/mnt/c/` (mounted NTFS filesystem).

**Fix**: Move to native WSL filesystem:
```bash
cp -r /mnt/c/Users/you/Desktop/Aria/ARIA ~/ARIA
cd ~/ARIA
./install/install.sh
```

### Backend not responding after start

**Diagnostics**:
```bash
# Check process
pgrep -f "core.api.server"

# Check port
ss -tlnp | grep 8000

# View logs (Docker)
docker logs aria --tail 50

# View logs (local)
cat logs/aria.log | tail -50
```

### Embedding model fails to download

**Cause**: Slow or blocked network.

**Fix**:
```bash
# Retry manually
source .venv/bin/activate
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')"

# Or skip and let it download on first use
./install/install.sh --skip-model
```

### Resend free tier doesn't send to other emails

**Cause**: Free tier only allows sending to the Resend account holder's email.

**Fix**: Verify a custom domain in Resend Dashboard to send to any email.

### Installation interrupted (Ctrl+C)

The script shows a recovery message. It is safe to re-run `./install/install.sh` — already-installed components are detected automatically. Existing `.env` values are preserved (the script asks before overwriting).

---

## Differences from Previous setup.sh

| Feature | Previous setup.sh | New install.sh |
|---------|------------------|----------------|
| Structure | Monolithic (1 file) | Modular (5 files) |
| Error handling | `set -e` (brittle) | No `set -e`, explicit `fail()` |
| Questions timing | Mixed with installs | All upfront (Phase 1) |
| Interrupt handling | None | `trap` with recovery message |
| Idempotency | Partial | Detects existing .env, venv, secrets |
| Playwright local | No | Yes (~280MB) |
| Embedding model | No | Yes, with retries (~90MB) |
| Resend verification | No | Real API call |
| Test email | No | Yes |
| API key validation | No (accepts placeholders) | Yes |
| pip upgrade | No | Yes (pip + setuptools + wheel) |
| Python 3.13 fix | No | Yes (onnxruntime first) |
| WSL detection | No | Yes, with /mnt/c/ warning |
| Nginx config | No | Yes, with HSTS + CSP + rate limit |
| SSL guidance | No | Yes |
| Firewall guidance | No | Yes |
| DNS guidance (DMARC) | No | Yes, with rua= |
| better-sqlite3 check | No | Yes (verifies .node binary) |
| Build validation | Only checks dir exists | Verifies index.js, client/, server/ |
| Health check | No | Yes (polling 120s) |
| Disk space check | No | Yes (min 2GB) |
| Venv version check | No | Yes (recreates if Python < 3.10) |
| Multiple emails | No | Yes |
| Dev mode (--dev) | No | Yes (quick start, no Resend) |
| Secret handling | sed (visible in ps) | awk (not in process list) |
| NODE_ENV production | Not set | Set in supervisord.conf + docker-compose |
| Time estimates | No | Yes |
| Platform support | Linux/macOS | Linux/macOS/WSL with detection |

### Compatibility

The new `install/install.sh` fully replaces `setup.sh`. The old `setup.sh` is now a thin wrapper (~20 lines) that prints a deprecation notice and `exec`s `install/install.sh` with all arguments forwarded. It will be removed in a future release.

---

## Approval

| Reviewer | Date | Status |
|----------|------|--------|
| DevOps/Infra | 2026-04-13 | **APPROVED** |
| DX/Onboarding | 2026-04-13 | **APPROVED** |
| Security/Auth | 2026-04-13 | **APPROVED** |

### Review Notes

**DevOps/Infra** — 2 minor warnings:
- Docker compose command invocation via word-splitting (`$ARIA_COMPOSE_CMD up -d`) is fragile but functional. Consider using `eval` or array.
- `--dry-run` output does not show the LLM key prompt, test email prompt, or agent selection — interactive Phase 1 steps are omitted from the preview.

**DX/Onboarding** — 2 minor warnings:
- Default LLM choice is `1` (DeepSeek), which requires a key. A first-time explorer with no key gets a warning. Not blocking — the flow handles it gracefully.
- Agent picker: entering `1,5` installs all (because `5` triggers "all"). Technically correct but edge-case surprise.

**Security/Auth** — 1 minor warning:
- OpenCode install via `curl -fsSL https://opencode.ai/install | sh` is a standard supply-chain risk. The guide documents the install method but does not mention the risk. Recommend adding a brief note suggesting users review the script first.

---

> Document generated automatically. Last updated: 2026-04-13.
