#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# ARIA — Backend Installation Module
# ═══════════════════════════════════════════════════════════════════
# Sourced by install.sh — do not execute directly.

# ── 1. Check System Prerequisites ──────────────────────────────────
backend_check_prerequisites() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Checking system prerequisites..."

    # Python (minimum 3.10)
    if has_cmd python3; then
        local py_ver py_major py_minor
        py_ver=$(python3 --version 2>&1 | awk '{print $2}')
        py_major=$(echo "$py_ver" | cut -d. -f1)
        py_minor=$(echo "$py_ver" | cut -d. -f2)
        if [ "$py_major" -lt 3 ] || ([ "$py_major" -eq 3 ] && [ "$py_minor" -lt 10 ]); then
            fail "Python >= 3.10 required (found $py_ver)"
        fi
        ok "Python $py_ver"
    else
        fail "Python 3 is required. Install from https://python.org"
    fi

    # pip
    if has_cmd pip3 || has_cmd pip; then
        ok "pip available"
    else
        warn "pip not found — will be installed with venv"
    fi

    # git
    if has_cmd git; then
        ok "git $(git --version | awk '{print $3}')"
    else
        case "$ARIA_PKG_MGR" in
            apt) fail "git required: sudo apt install git" ;;
            dnf) fail "git required: sudo dnf install git" ;;
            brew) fail "git required: brew install git" ;;
            *) fail "git is required. Install it for your platform." ;;
        esac
    fi

    # ffmpeg (for audio processing)
    if has_cmd ffmpeg; then
        ok "ffmpeg available"
    else
        warn "ffmpeg not found — audio perception won't work"
        case "$ARIA_PKG_MGR" in
            apt)  info "Install with: sudo apt install ffmpeg" ;;
            dnf)  info "Install with: sudo dnf install ffmpeg" ;;
            brew) info "Install with: brew install ffmpeg" ;;
        esac
    fi

    # curl
    if has_cmd curl; then
        ok "curl available"
    else
        warn "curl not found — some verifications will be skipped"
    fi

    # Disk space (minimum 2GB)
    if check_disk_space "$PROJECT_ROOT" 2048; then
        ok "Sufficient disk space"
    fi
}

# ── 2. Setup Python Virtual Environment ────────────────────────────
backend_setup_venv() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Setting up Python virtual environment..."

    if [ -d .venv ]; then
        # Verify existing venv Python version is compatible
        if [ -f .venv/bin/python3 ]; then
            local venv_py_ver venv_minor
            venv_py_ver=$(.venv/bin/python3 --version 2>&1 | awk '{print $2}')
            venv_minor=$(echo "$venv_py_ver" | cut -d. -f2)
            if [ "$venv_minor" -lt 10 ] 2>/dev/null; then
                warn "Existing venv uses Python $venv_py_ver (< 3.10), recreating..."
                rm -rf .venv
                python3 -m venv .venv
                ok "Venv recreated with $(python3 --version)"
            else
                ok "Existing venv valid (Python $venv_py_ver)"
            fi
        fi
    else
        python3 -m venv .venv
        ok "Venv created → .venv/"
    fi

    # Activate
    # shellcheck disable=SC1091
    source .venv/bin/activate
    ok "Venv activated"

    # Upgrade pip/setuptools/wheel
    pip install --quiet --upgrade pip setuptools wheel 2>&1 | tail -1 || true
    ok "pip/setuptools/wheel upgraded"
}

# ── 3. Install Python Dependencies ─────────────────────────────────
backend_install_deps() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Installing Python dependencies..."

    if [ ! -f requirements.txt ]; then
        fail "requirements.txt not found"
    fi

    # Python 3.13 needs onnxruntime installed before chromadb
    local py_minor
    py_minor=$(python3 -c "import sys; print(sys.version_info.minor)")
    if [ "$py_minor" -ge 13 ] 2>/dev/null; then
        info "Python 3.13+ detected — installing onnxruntime first..."
        pip install --quiet "onnxruntime>=1.20.0" 2>&1 | tail -1 || true
    fi

    if pip install --quiet -r requirements.txt 2>&1 | tail -3; then
        ok "Python dependencies installed"
    else
        warn "Some packages may have failed. Check manually with: pip install -r requirements.txt"
    fi
}

# ── 4. Install Playwright + Chromium ───────────────────────────────
backend_setup_playwright() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Installing Playwright and Chromium (~280MB)..."

    # Install chromium browser
    if python3 -m playwright install chromium 2>&1 | tail -3; then
        ok "Chromium installed via Playwright"
    else
        warn "Failed to install Chromium — web_fetch with JS won't work"
        info "Try manually: playwright install chromium"
        return 0
    fi

    # Install system dependencies (Linux only, needs sudo)
    if [[ "$ARIA_OS" == "linux" || "$ARIA_OS" == "wsl" ]]; then
        info "Installing system dependencies for Chromium..."
        if has_cmd sudo; then
            if python3 -m playwright install-deps chromium 2>&1 | tail -3; then
                ok "System dependencies installed"
            else
                warn "Could not install Playwright system deps"
                info "Run manually: sudo npx playwright install-deps chromium"
            fi
        else
            warn "sudo not available — install Playwright dependencies manually"
            info "Packages needed: libnss3 libnspr4 libatk1.0-0 libgbm1 libasound2..."
        fi
    fi

    # Verify
    if python3 -c "from playwright.sync_api import sync_playwright; print('OK')" 2>/dev/null; then
        ok "Playwright verified"
    else
        warn "Playwright not functional — check installation"
    fi
}

# ── 5. Pre-download Embedding Model ───────────────────────────────
backend_download_model() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Downloading embedding model (~90MB)..."

    info "Downloading paraphrase-multilingual-MiniLM-L12-v2..."

    local max_retries=3
    local attempt=0
    while [ $attempt -lt $max_retries ]; do
        if python3 -c "
from sentence_transformers import SentenceTransformer
m = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
dim = len(m.encode('test'))
assert dim == 384, f'Unexpected dimension: {dim}'
print(f'Model loaded (dim={dim})')
" 2>&1 | tail -2; then
            ok "Embedding model ready"
            return 0
        fi
        attempt=$((attempt + 1))
        if [ $attempt -lt $max_retries ]; then
            warn "Attempt $attempt/$max_retries failed, retrying..."
        fi
    done

    warn "Could not download model — it will download on first use"
    info "To retry later:"
    info "  python3 -c \"from sentence_transformers import SentenceTransformer; SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')\""
}

# ── 6. Create Data Directories ────────────────────────────────────
backend_create_dirs() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Creating data directories..."

    mkdir -p data/auth data/mirror data/conversations data/backups data/reflections
    ok "data/ directories created"

    # Restrictive permissions on auth directory
    chmod 700 data/auth 2>/dev/null || true
    ok "data/auth/ permissions set to 700"
}

# ── 7. Validate Environment Variables ─────────────────────────────
backend_validate_env() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Validating environment variables..."

    if [ ! -f .env ]; then
        warn ".env does not exist — will be created in configuration step"
        return 0
    fi

    # Check at least one LLM key is not a placeholder
    local has_llm=false
    local placeholders=("sk-your-deepseek-key" "sk-proj-your-openai-key" "sk-ant-your-anthropic-key" "your-google-key" "sk-or-your-openrouter-key")
    local key_vars=("DEEPSEEK_API_KEY" "OPENAI_API_KEY" "ANTHROPIC_API_KEY" "GOOGLE_API_KEY" "OPENROUTER_API_KEY")

    for i in "${!key_vars[@]}"; do
        local val
        val=$(read_env_var "${key_vars[$i]}")
        if [ -n "$val" ] && [ "$val" != "${placeholders[$i]}" ]; then
            has_llm=true
            ok "${key_vars[$i]} configured"
        fi
    done

    if [ "$has_llm" = false ]; then
        warn "No LLM API keys configured — ARIA needs at least one"
        info "Edit .env and set DEEPSEEK_API_KEY, OPENAI_API_KEY, or ANTHROPIC_API_KEY"
    fi

    # Verify ARIA_INTERNAL_SECRET
    local secret
    secret=$(read_env_var "ARIA_INTERNAL_SECRET")
    if [ -z "$secret" ]; then
        info "ARIA_INTERNAL_SECRET empty — OK for local development"
    else
        ok "ARIA_INTERNAL_SECRET configured"
    fi

    # Verify .env permissions
    local perms
    perms=$(stat -c '%a' .env 2>/dev/null || stat -f '%Lp' .env 2>/dev/null || echo "unknown")
    if [ "$perms" != "600" ]; then
        chmod 600 .env 2>/dev/null
        ok ".env permissions fixed to 600"
    else
        ok ".env permissions correct (600)"
    fi
}

# ── 8. Docker Setup ───────────────────────────────────────────────
backend_setup_docker() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Setting up Docker..."

    # Verify Docker
    if ! has_cmd docker; then
        fail "Docker is required for --docker mode"
    fi
    ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"

    # Verify docker compose
    local compose_cmd=""
    if docker compose version &>/dev/null; then
        compose_cmd="docker compose"
    elif has_cmd docker-compose; then
        compose_cmd="docker-compose"
    else
        fail "docker compose not found"
    fi
    ok "$compose_cmd available"

    # Verify required files
    [ -f Dockerfile ] || fail "Dockerfile not found"
    [ -f docker-compose.yml ] || fail "docker-compose.yml not found"
    [ -f deploy/supervisord.conf ] || fail "deploy/supervisord.conf not found"
    ok "Docker files present"

    # Build image
    info "Building Docker image (first build: ~10-20 min, subsequent: ~1-2 min)..."
    if $compose_cmd build --progress=plain 2>&1 | tail -5; then
        ok "Docker image built"
    else
        fail "Docker build failed — check the output above"
    fi

    # Export compose command for later use
    export ARIA_COMPOSE_CMD="$compose_cmd"
}

# ── 9. Health Check ───────────────────────────────────────────────
backend_health_check() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Checking backend health..."

    local max_wait=120
    local interval=5
    local elapsed=0

    info "Waiting for FastAPI to respond (max ${max_wait}s)..."

    while [ $elapsed -lt $max_wait ]; do
        if curl -s http://localhost:8000/api/status 2>/dev/null | grep -q "status"; then
            ok "Backend responding at http://localhost:8000"
            return 0
        fi
        sleep $interval
        elapsed=$((elapsed + interval))
        echo -ne "  ${D}${elapsed}s...${N}\r"
    done

    warn "Backend not responding after ${max_wait}s"

    # Diagnostics
    if pgrep -f "core.api.server" >/dev/null 2>&1; then
        info "Server process is running"
    else
        warn "Server process is NOT running"
    fi

    if has_cmd ss; then
        if ss -tlnp 2>/dev/null | grep -q ":8000"; then
            info "Port 8000 is in use"
        else
            warn "Port 8000 is not in use"
        fi
    fi
}
