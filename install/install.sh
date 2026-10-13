#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# ARIA — Unified Installation Script
#
# Usage:
#   ./install/install.sh                   Full install (interactive)
#   ./install/install.sh --docker          Docker-only deployment
#   ./install/install.sh --minimal         Backend only (no GUI)
#   ./install/install.sh --dev             Quick dev setup (skip agents/Resend)
#   ./install/install.sh --skip-agents     Skip coding agent installation
#   ./install/install.sh --skip-playwright Skip Playwright/Chromium
#   ./install/install.sh --skip-model      Skip embedding model download
#   ./install/install.sh --dry-run         Show plan without executing
#   ./install/install.sh --help            Show this help
# ═══════════════════════════════════════════════════════════════════
set -uo pipefail
# NOTE: We do NOT use `set -e`. Functions return 0 even for non-critical
# warnings so callers don't need || true everywhere. Critical failures
# use fail() which calls exit 1 directly.

# ── Resolve paths ──────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"
export PROJECT_ROOT

# ── Source modules ─────────────────────────────────────────────────
source "$SCRIPT_DIR/common.sh"
source "$SCRIPT_DIR/backend.sh"
source "$SCRIPT_DIR/frontend.sh"
source "$SCRIPT_DIR/auth-email.sh"

# ── Trap for clean interruption ────────────────────────────────────
trap cleanup_on_interrupt INT TERM

# ── Parse flags ────────────────────────────────────────────────────
MODE="full"             # full | docker | minimal | dev
SKIP_AGENTS=false
SKIP_PLAYWRIGHT=false
SKIP_MODEL=false
VERIFY_FRONTEND=false
DRY_RUN=false

for arg in "$@"; do
    case "$arg" in
        --docker)          MODE="docker" ;;
        --minimal)         MODE="minimal" ;;
        --dev)             MODE="dev"; SKIP_AGENTS=true ;;
        --skip-agents)     SKIP_AGENTS=true ;;
        --skip-playwright) SKIP_PLAYWRIGHT=true ;;
        --skip-model)      SKIP_MODEL=true ;;
        --verify)          VERIFY_FRONTEND=true ;;
        --dry-run)         DRY_RUN=true ;;
        --help|-h)
            echo "ARIA — Unified Installation Script"
            echo ""
            echo "Usage: ./install/install.sh [options]"
            echo ""
            echo "Modes:"
            echo "  (no flag)         Full install (backend + frontend + auth)"
            echo "  --docker          Docker only (validate .env, build image, start)"
            echo "  --minimal         Backend only (Python, no Node.js/GUI)"
            echo "  --dev             Quick dev setup (no agents, skips Resend)"
            echo ""
            echo "Options:"
            echo "  --skip-agents     Don't install coding agents"
            echo "  --skip-playwright Don't install Playwright/Chromium"
            echo "  --skip-model      Don't download embedding model"
            echo "  --verify          Run frontend smoke test after build"
            echo "  --dry-run         Show what would be done without executing"
            echo "  --help            Show this help"
            exit 0
            ;;
        *)
            warn "Unknown flag: $arg"
            ;;
    esac
done

# ── Detect platform ───────────────────────────────────────────────
detect_platform

# ── Banner ─────────────────────────────────────────────────────────
echo ""
echo -e "${B}  ◆ ARIA — Unified Setup${N}"
echo -e "${D}  Personal AI assistant with self-modification${N}"
echo ""
echo -e "  ${D}Platform:${N}   $ARIA_OS ($ARIA_ARCH)"
echo -e "  ${D}Mode:${N}       $MODE"
echo -e "  ${D}Directory:${N}  $PROJECT_ROOT"
echo ""

# Estimated time
case "$MODE" in
    full)    info "Estimated time: ~15-20 minutes (first install)" ;;
    docker)  info "Estimated time: ~10-20 minutes (first build)" ;;
    minimal) info "Estimated time: ~5-10 minutes" ;;
    dev)     info "Estimated time: ~10-15 minutes" ;;
esac
echo ""

# ── Dry-run mode ──────────────────────────────────────────────────
if $DRY_RUN; then
    echo -e "${C}${B}[DRY RUN]${N} The following steps would be executed:\n"

    echo -e "  ${G}1.${N} Check prerequisites (Python >= 3.10, git, pip, curl, ffmpeg)"
    echo -e "  ${G}2.${N} Create .env from .env.example (if not present)"
    echo -e "  ${G}3.${N} Collect access emails (interactive)"
    if [ "$MODE" != "dev" ]; then
        echo -e "  ${G}4.${N} Configure Resend API key (interactive)"
        echo -e "  ${G}5.${N} Configure domain / deployment mode (interactive)"
    else
        echo -e "  ${D}4.${N} ${D}Skip Resend (dev mode)${N}"
        echo -e "  ${D}5.${N} ${D}Skip domain (dev mode → localhost)${N}"
    fi
    echo -e "  ${G}6.${N} Generate ARIA_INTERNAL_SECRET"
    echo -e "  ${G}7.${N} Prompt for LLM API key"

    if [ "$MODE" != "docker" ]; then
        echo -e "  ${G}8.${N}  Create Python venv → .venv/"
        echo -e "  ${G}9.${N}  Install Python dependencies (requirements.txt)"
        $SKIP_PLAYWRIGHT || echo -e "  ${G}10.${N} Install Playwright + Chromium (~280MB download)"
        $SKIP_MODEL      || echo -e "  ${G}11.${N} Download embedding model (~90MB download)"
        echo -e "  ${G}12.${N} Create data directories (data/auth, data/mirror, ...)"
    fi

    if [ "$MODE" = "full" ] || [ "$MODE" = "dev" ]; then
        echo -e "  ${G}13.${N} Validate Node.js >= 18 and npm"
        echo -e "  ${G}14.${N} Check C++ build tools (gcc, g++, make)"
        echo -e "  ${G}15.${N} npm install in web/"
        echo -e "  ${G}16.${N} Build SvelteKit frontend"
        $VERIFY_FRONTEND && echo -e "  ${G}17.${N} Run frontend smoke test"
    fi

    if ! $SKIP_AGENTS && [ "$MODE" = "full" ]; then
        echo -e "  ${G}18.${N} Install coding agents (claude, codex, aider, opencode)"
    fi

    echo -e "  ${G}19.${N} Validate .env + security checks"

    if [ "$MODE" = "docker" ]; then
        echo -e "  ${G}20.${N} Build Docker image"
        echo -e "  ${G}21.${N} Start containers + health check"
    fi

    echo ""
    echo -e "  ${D}Platform:${N}   $ARIA_OS ($ARIA_ARCH)"
    echo -e "  ${D}Mode:${N}       $MODE"
    echo -e "  ${D}Directory:${N}  $PROJECT_ROOT"
    echo ""
    echo -e "  ${D}Run without --dry-run to execute.${N}"
    echo ""
    exit 0
fi

# ── WSL performance check ─────────────────────────────────────────
check_wsl_path

# ── Verify .env.example exists ─────────────────────────────────────
if [ ! -f .env.example ]; then
    fail ".env.example not found. Is this the complete ARIA repository?"
fi

# ═══════════════════════════════════════════════════════════════════
# DOCKER MODE
# ═══════════════════════════════════════════════════════════════════
if [ "$MODE" = "docker" ]; then
    TOTAL_STEPS=8
    CURRENT_STEP=1
    export TOTAL_STEPS CURRENT_STEP

    # Step 1: Prerequisites
    backend_check_prerequisites
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # Step 2: Create .env if needed
    if [ ! -f .env ]; then
        cp .env.example .env
        chmod 600 .env
        ok ".env created from template"
    fi

    # Step 3: Auth & email config
    auth_collect_emails
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # Step 4: Resend
    auth_setup_resend
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # Step 5: Internal secret
    auth_generate_secret
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # Step 6: Domain
    auth_configure_domain
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # Network check before Docker build
    if has_cmd curl; then
        info "Checking internet connectivity..."
        if check_network; then
            ok "Internet reachable"
        else
            warn "No internet connection — Docker build may fail downloading dependencies."
        fi
    fi

    # Step 7: Docker build
    backend_setup_docker
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # Step 8: Start + health check
    step "$CURRENT_STEP/$TOTAL_STEPS" "Starting ARIA..."
    if $ARIA_COMPOSE_CMD up -d; then
        ok "ARIA is running"
    else
        fail "Failed to start ARIA. Check: $ARIA_COMPOSE_CMD logs"
    fi

    backend_health_check

    # Production extras (these use their own step counters for display)
    if [ "$AUTH_DEPLOY_MODE" = "production" ] && [ -n "$AUTH_DOMAIN" ]; then
        frontend_generate_nginx "$AUTH_DOMAIN"
        frontend_ssl_guidance "$AUTH_DOMAIN" "$AUTH_PRIMARY_EMAIL"
        auth_firewall_guidance
    fi

    auth_security_checks

    echo ""
    banner "ARIA Docker — Setup Complete"
    echo ""
    info "ARIA is running at http://localhost:3000"
    if [ -n "${AUTH_DOMAIN:-}" ]; then
        info "Domain: https://$AUTH_DOMAIN"
    fi
    info "Access email: ${AUTH_PRIMARY_EMAIL:-configure in .env}"
    echo ""
    exit 0
fi

# ═══════════════════════════════════════════════════════════════════
# FULL / MINIMAL / DEV MODE
# ═══════════════════════════════════════════════════════════════════

# ── Phase 1: Interactive configuration (BEFORE long installs) ─────
# Ask all questions upfront so the rest can run unattended.

# Create .env from template if needed
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
    ok ".env created from template"
fi

# Calculate total steps
TOTAL_STEPS=7  # base: prereqs, config, venv, deps, dirs, validate, summary
if [ "$MODE" = "full" ] || [ "$MODE" = "dev" ]; then
    TOTAL_STEPS=$((TOTAL_STEPS + 4))  # node-check, build-tools, npm, svelte-build
fi
$SKIP_PLAYWRIGHT || TOTAL_STEPS=$((TOTAL_STEPS + 1))
$SKIP_MODEL      || TOTAL_STEPS=$((TOTAL_STEPS + 1))
$SKIP_AGENTS     || { [ "$MODE" = "full" ] && TOTAL_STEPS=$((TOTAL_STEPS + 1)); }

CURRENT_STEP=1
export TOTAL_STEPS CURRENT_STEP

# ── Step 1: All interactive questions ─────────────────────────────
step "$CURRENT_STEP/$TOTAL_STEPS" "Configuration..."
echo ""

# Email collection
auth_collect_emails

# Resend (skip in dev mode)
if [ "$MODE" = "dev" ]; then
    info "Dev mode: skipping Resend configuration"
    export AUTH_RESEND_CONFIGURED=false
else
    auth_setup_resend
fi

# Internal secret
auth_generate_secret

# Domain
if [ "$MODE" = "dev" ]; then
    info "Dev mode: using localhost"
    export AUTH_DOMAIN=""
    export AUTH_DEPLOY_MODE="dev"
else
    auth_configure_domain
fi

# LLM API Key
echo ""
info "ARIA needs at least one LLM API key."
info "  1) DeepSeek    (affordable, recommended)"
info "  2) OpenAI      (GPT-4o)"
info "  3) Anthropic   (Claude)"
info "  4) Google      (Gemini)"
info "  5) Skip        (configure later in .env)"
echo ""
ask "Provider [1]:"
read -r llm_choice
llm_choice="${llm_choice:-1}"

case "$llm_choice" in
    1)
        ask "DeepSeek API key:"
        read -rs llm_key; echo ""
        if [ -n "$llm_key" ]; then
            env_set "DEEPSEEK_API_KEY" "$llm_key"
            ok "DeepSeek configured"
        else
            info "Empty key — skipping"
        fi
        ;;
    2)
        ask "OpenAI API key:"
        read -rs llm_key; echo ""
        if [ -n "$llm_key" ]; then
            env_set "OPENAI_API_KEY" "$llm_key"
            ok "OpenAI configured"
        else
            info "Empty key — skipping"
        fi
        ;;
    3)
        ask "Anthropic API key:"
        read -rs llm_key; echo ""
        if [ -n "$llm_key" ]; then
            env_set "ANTHROPIC_API_KEY" "$llm_key"
            ok "Anthropic configured"
        else
            info "Empty key — skipping"
        fi
        ;;
    4)
        ask "Google API key:"
        read -rs llm_key; echo ""
        if [ -n "$llm_key" ]; then
            env_set "GOOGLE_API_KEY" "$llm_key"
            ok "Google configured"
        else
            info "Empty key — skipping"
        fi
        ;;
    *)
        warn "Skipped — configure a key in .env before using ARIA"
        ;;
esac

# Dev fallback if no Resend
auth_dev_fallback

# Ask about test email now (interactive phase) — send later (automated phase)
SEND_TEST_EMAIL=false
if [ "${AUTH_RESEND_CONFIGURED:-false}" = "true" ]; then
    echo ""
    ask "Send a test email to ${AUTH_PRIMARY_EMAIL} after setup? [Y/n]:"
    read -r send_test
    if [[ ! "$send_test" =~ ^[nN] ]]; then
        SEND_TEST_EMAIL=true
    fi
fi
export SEND_TEST_EMAIL

# Ask which coding agents to install (interactive phase) — install later (automated phase)
INSTALL_CLAUDE=false
INSTALL_CODEX=false
INSTALL_AIDER=false
INSTALL_OPENCODE=false

if ! $SKIP_AGENTS && [ "$MODE" = "full" ]; then
    echo ""
    info "Coding agents for the self-modification system:"
    echo -e "  ${D}1) Claude Code  — Anthropic  (requires OAuth login after setup)${N}"
    echo -e "  ${D}2) Codex        — OpenAI     (uses OPENAI_API_KEY from .env)${N}"
    echo -e "  ${D}3) Aider        — Multi-LLM  (uses LLM key from .env)${N}"
    echo -e "  ${D}4) OpenCode     — Open-source (uses LLM key from .env)${N}"
    echo -e "  ${D}5) All of the above${N}"
    echo -e "  ${D}6) None (skip)${N}"
    echo ""
    ask "Which agents to install? (e.g. 1,3 or 5 for all) [5]:"
    read -r agent_choice
    agent_choice="${agent_choice:-5}"

    if [[ "$agent_choice" == *"6"* ]]; then
        SKIP_AGENTS=true
        info "Skipping agent installation"
    else
        if [[ "$agent_choice" == *"5"* ]]; then
            INSTALL_CLAUDE=true; INSTALL_CODEX=true; INSTALL_AIDER=true; INSTALL_OPENCODE=true
        else
            [[ "$agent_choice" == *"1"* ]] && INSTALL_CLAUDE=true
            [[ "$agent_choice" == *"2"* ]] && INSTALL_CODEX=true
            [[ "$agent_choice" == *"3"* ]] && INSTALL_AIDER=true
            [[ "$agent_choice" == *"4"* ]] && INSTALL_OPENCODE=true
        fi
    fi
fi
export INSTALL_CLAUDE INSTALL_CODEX INSTALL_AIDER INSTALL_OPENCODE

echo ""
ok "Configuration complete. Starting automated installation..."
info "You can step away — the rest runs unattended."
echo ""

CURRENT_STEP=$((CURRENT_STEP + 1))

# ── Phase 2: Automated installation (no more prompts) ────────────

# Network check (before any downloads)
if has_cmd curl; then
    info "Checking internet connectivity..."
    if check_network; then
        ok "Internet reachable"
    else
        warn "No internet connection detected."
        warn "pip install, npm install, and model downloads will likely fail."
        info "Check your connection and re-run the installer."
    fi
else
    info "curl not available — skipping connectivity check"
fi

# 2. Prerequisites
backend_check_prerequisites
CURRENT_STEP=$((CURRENT_STEP + 1))

# 3. Python venv
backend_setup_venv
CURRENT_STEP=$((CURRENT_STEP + 1))

# 4. Python dependencies
backend_install_deps
CURRENT_STEP=$((CURRENT_STEP + 1))

# 5. Playwright (optional)
if ! $SKIP_PLAYWRIGHT; then
    backend_setup_playwright
    CURRENT_STEP=$((CURRENT_STEP + 1))
fi

# 6. Embedding model (optional)
if ! $SKIP_MODEL; then
    backend_download_model
    CURRENT_STEP=$((CURRENT_STEP + 1))
fi

# 7. Data directories
backend_create_dirs
CURRENT_STEP=$((CURRENT_STEP + 1))

# ── Frontend (full and dev modes) ─────────────────────────────────

if [ "$MODE" = "full" ] || [ "$MODE" = "dev" ]; then
    # 8. Node.js check
    frontend_validate_node
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # 9. Build tools
    frontend_check_build_tools
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # 10. npm install
    frontend_npm_install
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # 11. SvelteKit build
    frontend_build
    CURRENT_STEP=$((CURRENT_STEP + 1))

    # 12. Smoke test (optional)
    if $VERIFY_FRONTEND; then
        frontend_smoke_test
        CURRENT_STEP=$((CURRENT_STEP + 1))
    fi
fi

# ── Coding Agents (optional, full mode only) ──────────────────────

if ! $SKIP_AGENTS && [ "$MODE" = "full" ]; then
    step "$CURRENT_STEP/$TOTAL_STEPS" "Installing selected coding agents..."
    echo ""

    # Claude Code
    if $INSTALL_CLAUDE; then
        if has_cmd claude; then
            ok "Claude Code already installed"
        else
            info "Installing Claude Code..."
            npm install -g @anthropic-ai/claude-code 2>&1 | tail -1 && ok "Claude Code installed" || warn "Failed — npm install -g @anthropic-ai/claude-code"
        fi
    fi

    # Codex
    if $INSTALL_CODEX; then
        if has_cmd codex; then
            ok "Codex CLI already installed"
        else
            info "Installing Codex CLI..."
            npm install -g @openai/codex 2>&1 | tail -1 && ok "Codex installed" || warn "Failed — npm install -g @openai/codex"
        fi
    fi

    # Aider
    if $INSTALL_AIDER; then
        if has_cmd aider; then
            ok "Aider already installed"
        else
            info "Installing Aider..."
            pip install --quiet aider-chat 2>&1 | tail -1 && ok "Aider installed" || warn "Failed — pip install aider-chat"
        fi
    fi

    # OpenCode
    if $INSTALL_OPENCODE; then
        if has_cmd opencode; then
            ok "OpenCode already installed"
        else
            info "Installing OpenCode..."
            curl -fsSL https://opencode.ai/install | sh 2>&1 | tail -1 && ok "OpenCode installed" || warn "Failed — curl -fsSL https://opencode.ai/install | sh"
        fi
    fi

    echo ""
    info "Agent status:"
    for agent in claude codex aider opencode; do
        if has_cmd "$agent"; then
            echo -e "    ${G}✓${N} $agent"
        else
            echo -e "    ${D}· $agent (not installed)${N}"
        fi
    done

    # Post-install auth guidance
    echo ""
    if has_cmd claude; then
        info "Claude Code requires a one-time login."
        echo -e "  ${D}Run ${N}${B}claude${N}${D} after setup to authenticate via browser (OAuth).${N}"
        echo -e "  ${D}Or set ${N}${B}ANTHROPIC_API_KEY${N}${D} in your shell environment.${N}"
    fi
    if has_cmd codex; then
        echo -e "  ${D}Codex uses your ${N}${B}OPENAI_API_KEY${N}${D} from .env — no extra login needed.${N}"
    fi
    if has_cmd aider; then
        echo -e "  ${D}Aider uses your LLM key from .env — no extra login needed.${N}"
    fi
    if has_cmd opencode; then
        echo -e "  ${D}OpenCode uses your LLM key from .env — no extra login needed.${N}"
    fi

    CURRENT_STEP=$((CURRENT_STEP + 1))
fi

# ── Validate & Security ──────────────────────────────────────────

backend_validate_env
auth_security_checks

# Send test email (decision was made in interactive phase)
if $SEND_TEST_EMAIL; then
    auth_send_test_email
fi

# Production extras
if [ "${AUTH_DEPLOY_MODE:-dev}" = "production" ] && [ -n "${AUTH_DOMAIN:-}" ]; then
    frontend_generate_nginx "$AUTH_DOMAIN"
    frontend_ssl_guidance "$AUTH_DOMAIN" "$AUTH_PRIMARY_EMAIL"
    auth_dns_guidance
    auth_firewall_guidance
fi

# Frontend env config
if [ "$MODE" = "full" ] || [ "$MODE" = "dev" ]; then
    frontend_configure_env "${AUTH_DOMAIN:-}" "${AUTH_DEPLOY_MODE:-dev}"
fi

# ═══════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════

echo ""
banner "ARIA — Setup Complete"
echo ""

if [ "$MODE" = "minimal" ]; then
    info "To start ARIA (terminal):"
    info "  source .venv/bin/activate"
    info "  python aria.py"
    echo ""
    info "To start the API server:"
    info "  source .venv/bin/activate"
    info "  python -m core.api.server --port 8000"
else
    echo -e "  ${G}Option A — Development (two terminals):${N}"
    info "  Terminal 1: source .venv/bin/activate && python -m core.api.server --port 8000"
    info "  Terminal 2: cd web && npm run dev"
    info "  Open: http://localhost:5173"
    echo ""
    echo -e "  ${G}Option B — Docker (production):${N}"
    info "  docker compose up -d"
    info "  Open: http://localhost:3000"
    if [ -n "${AUTH_DOMAIN:-}" ]; then
        info "  Domain: https://$AUTH_DOMAIN"
    fi
    echo ""
    echo -e "  ${B}First login:${N}"
    info "  1. Open the URL above"
    info "  2. Enter your email: ${AUTH_PRIMARY_EMAIL:-<configure in .env>}"
    info "  3. Check your inbox for the 6-digit code"
    info "  4. Enter the code → you're in"
fi

echo ""
info "Config:  .env"
info "Docs:    docs/INSTALL_GUIDE.md"
info "Arch:    docs/ARCHITECTURE.md"
echo ""
echo -e "  ◆ ${B}ARIA is ready.${N}"
echo ""
