#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# ARIA — Frontend Installation Module
# ═══════════════════════════════════════════════════════════════════
# Sourced by install.sh — do not execute directly.

# ── 1. Validate Node.js ───────────────────────────────────────────
frontend_validate_node() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Checking Node.js..."

    if ! has_cmd node; then
        fail "Node.js >= 18 is required. Install from https://nodejs.org"
    fi

    local node_ver node_major
    node_ver=$(node --version | tr -d 'v')
    node_major=$(echo "$node_ver" | cut -d. -f1)

    if [ "$node_major" -lt 18 ]; then
        fail "Node.js >= 18 required (found $node_ver)"
    fi

    if [ "$node_major" -lt 22 ]; then
        warn "Node.js $node_ver — v22 LTS recommended for Vite 8 and TypeScript 6"
    else
        ok "Node.js v$node_ver"
    fi

    # npm
    if has_cmd npm; then
        local npm_ver npm_major
        npm_ver=$(npm --version)
        npm_major=$(echo "$npm_ver" | cut -d. -f1)
        if [ "$npm_major" -lt 9 ]; then
            warn "npm $npm_ver — npm >= 9 recommended"
        else
            ok "npm $npm_ver"
        fi
    else
        fail "npm is required (comes with Node.js)"
    fi
}

# ── 2. Check Build Tools for Native Modules ──────────────────────
frontend_check_build_tools() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Checking build tools..."

    local tools_ok=true

    case "$ARIA_OS" in
        linux|wsl)
            for tool in gcc g++ make; do
                if has_cmd "$tool"; then
                    ok "$tool available"
                else
                    tools_ok=false
                    warn "$tool not found"
                fi
            done
            if [ "$tools_ok" = false ]; then
                info "better-sqlite3 requires C++ build tools"
                case "$ARIA_PKG_MGR" in
                    apt)    info "Install: sudo apt install build-essential python3" ;;
                    dnf)    info "Install: sudo dnf groupinstall 'Development Tools'" ;;
                    pacman) info "Install: sudo pacman -S base-devel" ;;
                esac
            fi
            ;;
        macos)
            if xcode-select --print-path &>/dev/null; then
                ok "Xcode CLI tools installed"
            else
                warn "Xcode CLI tools not found"
                info "Install: xcode-select --install"
                tools_ok=false
            fi
            ;;
    esac

    if [ "$tools_ok" = true ]; then
        ok "Build tools ready"
    fi
}

# ── 3. Install Node Dependencies ─────────────────────────────────
frontend_npm_install() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Installing Node.js dependencies..."

    if [ ! -f web/package.json ]; then
        fail "web/package.json not found — is the repo complete?"
    fi

    cd web

    # Use npm ci if lock file exists (cleaner, faster)
    if [ -f package-lock.json ]; then
        info "Running npm ci..."
        if npm ci 2>&1 | tail -5; then
            ok "Dependencies installed (npm ci)"
        else
            warn "npm ci failed — trying npm install..."
            npm install 2>&1 | tail -5 || {
                cd "$PROJECT_ROOT"
                fail "npm install failed. Check errors above."
            }
            ok "Dependencies installed (npm install)"
        fi
    else
        npm install 2>&1 | tail -5 || {
            cd "$PROJECT_ROOT"
            fail "npm install failed"
        }
        ok "Dependencies installed"
    fi

    # Verify better-sqlite3 native module compiled
    if [ -f node_modules/better-sqlite3/build/Release/better_sqlite3.node ]; then
        ok "better-sqlite3 native module compiled"
    else
        warn "better-sqlite3 may not be compiled correctly"
        info "If auth errors occur, run: cd web && npm rebuild better-sqlite3"
    fi

    cd "$PROJECT_ROOT"
}

# ── 4. Build SvelteKit ───────────────────────────────────────────
frontend_build() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Building SvelteKit frontend..."

    cd web

    # Sync SvelteKit types
    info "Syncing SvelteKit types..."
    npx svelte-kit sync 2>&1 | tail -1 || true

    # Build
    info "Running production build..."
    if npm run build 2>&1 | tail -5; then
        ok "Build completed"
    else
        cd "$PROJECT_ROOT"
        warn "Build failed — run 'cd web && npm run check' to diagnose"
        return 0
    fi

    # Validate build output
    local build_ok=true
    [ -f build/index.js ]  || { warn "build/index.js not found"; build_ok=false; }
    [ -d build/client ]    || { warn "build/client/ not found"; build_ok=false; }
    [ -d build/server ]    || { warn "build/server/ not found"; build_ok=false; }

    if [ "$build_ok" = true ]; then
        local build_size
        build_size=$(du -sh build/ | awk '{print $1}')
        ok "Build validated ($build_size) → web/build/"
    fi

    # Deep validation: check that key routes built correctly
    local routes_dir="build/server/entries/pages"
    if [ -d "$routes_dir" ]; then
        local route_warnings=0

        if ! ls "$routes_dir"/*login* &>/dev/null 2>&1 && \
           ! ls "$routes_dir"/_page*login* &>/dev/null 2>&1 && \
           ! find "$routes_dir" -path "*login*" -print -quit 2>/dev/null | grep -q .; then
            warn "Login page route not found in build output"
            route_warnings=$((route_warnings + 1))
        fi

        if ! find "$routes_dir" -path "*mirror*" -print -quit 2>/dev/null | grep -q .; then
            warn "Mirror page route not found in build output"
            route_warnings=$((route_warnings + 1))
        fi

        # Chat/home is typically the root _page entry
        if ! find "$routes_dir" -maxdepth 1 -name "_page*" -print -quit 2>/dev/null | grep -q .; then
            warn "Home/chat page route not found in build output"
            route_warnings=$((route_warnings + 1))
        fi

        if [ "$route_warnings" -eq 0 ]; then
            ok "Key routes present (login, mirror, home)"
        else
            info "Some routes may not have built correctly ($route_warnings warning(s))"
            info "Run 'cd web && npm run build' manually to diagnose"
        fi
    else
        info "Skipping route validation (no server entries directory)"
    fi

    cd "$PROJECT_ROOT"
}

# ── 5. Generate Nginx Configuration ──────────────────────────────
frontend_generate_nginx() {
    local domain="$1"

    if [ -z "$domain" ]; then
        info "No domain configured — skipping Nginx config"
        return 0
    fi

    step "$CURRENT_STEP/$TOTAL_STEPS" "Generating Nginx configuration..."

    local nginx_conf="deploy/nginx-aria.conf"
    mkdir -p deploy

    cat > "$nginx_conf" << NGINX_EOF
# ═══════════════════════════════════════════════════════════════════
# ARIA — Nginx Reverse Proxy Configuration
# Generated by install.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ)
# ═══════════════════════════════════════════════════════════════════
#
# Install:
#   sudo cp $nginx_conf /etc/nginx/sites-available/aria
#   sudo ln -sf /etc/nginx/sites-available/aria /etc/nginx/sites-enabled/
#   sudo nginx -t && sudo systemctl reload nginx
#
# Then run: sudo certbot --nginx -d $domain

# Redirect HTTP → HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name $domain;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name $domain;

    # SSL — certbot will fill these in
    # ssl_certificate     /etc/letsencrypt/live/$domain/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/$domain/privkey.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; font-src 'self'; frame-ancestors 'self';" always;

    # Request limits
    client_max_body_size 10m;

    # Rate limiting for auth endpoints
    location /api/auth/ {
        limit_req zone=auth burst=5 nodelay;
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # SvelteKit (only public-facing upstream)
    # FastAPI is NOT exposed — SvelteKit proxies to it internally
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;

        # WebSocket support (for SSE streaming)
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";

        # SSE streaming — long timeout for AI responses
        proxy_read_timeout 300s;
        proxy_buffering off;
    }

    # Immutable assets (aggressive caching)
    location /_app/immutable/ {
        proxy_pass http://127.0.0.1:3000;
        expires 1y;
        add_header Cache-Control "public, immutable" always;
        add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
        access_log off;
    }
}

# Rate limit zone (place in http {} block or /etc/nginx/conf.d/rate-limit.conf)
# limit_req_zone \$binary_remote_addr zone=auth:10m rate=5r/m;
NGINX_EOF

    ok "Nginx config generated → $nginx_conf"
    info "Install with:"
    info "  sudo cp $nginx_conf /etc/nginx/sites-available/aria"
    info "  sudo ln -sf /etc/nginx/sites-available/aria /etc/nginx/sites-enabled/"
    info "  sudo nginx -t && sudo systemctl reload nginx"
    echo ""
    warn "NOTE: Add this line to /etc/nginx/nginx.conf inside the http {} block:"
    info "  limit_req_zone \$binary_remote_addr zone=auth:10m rate=5r/m;"
}

# ── 6. SSL Setup Guidance ────────────────────────────────────────
frontend_ssl_guidance() {
    local domain="$1"
    local email="$2"

    if [ -z "$domain" ]; then
        return 0
    fi

    step "$CURRENT_STEP/$TOTAL_STEPS" "SSL/TLS setup..."

    if has_cmd certbot; then
        ok "certbot available"
        info "Run to obtain SSL certificate:"
        info "  sudo certbot --nginx -d $domain --email $email --agree-tos"
    else
        warn "certbot not installed"
        case "$ARIA_PKG_MGR" in
            apt)  info "Install: sudo apt install certbot python3-certbot-nginx" ;;
            dnf)  info "Install: sudo dnf install certbot python3-certbot-nginx" ;;
            brew) info "Install: brew install certbot" ;;
        esac
        info "Then: sudo certbot --nginx -d $domain"
    fi

    echo ""
    info "IMPORTANT: Ports 80 and 443 must be open."
    info "With UFW: sudo ufw allow 80/tcp && sudo ufw allow 443/tcp"
}

# ── 7. Configure Environment for Frontend ────────────────────────
frontend_configure_env() {
    local domain="$1"
    local mode="$2"  # "dev" or "production"

    step "$CURRENT_STEP/$TOTAL_STEPS" "Configuring frontend environment..."

    if [ "$mode" = "production" ] && [ -n "$domain" ]; then
        env_set "ARIA_ORIGIN" "https://$domain"
        env_set "ARIA_CORS_ORIGINS" "https://$domain"
        ok "ORIGIN set → https://$domain"
        ok "CORS set → https://$domain"

        info "NOTE: In production, SvelteKit requires HTTPS for session cookies."
        info "Without SSL, login won't work (cookies have secure=true in production)."
    else
        info "Development mode: ORIGIN inferred automatically"
        info "SSL not required for localhost"
    fi
}

# ── 8. Smoke Test (optional — call with --verify) ───────────────
frontend_smoke_test() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Running frontend smoke test..."

    cd web

    if [ ! -f build/index.js ]; then
        warn "No build found — skipping smoke test"
        cd "$PROJECT_ROOT"
        return 0
    fi

    # Pick a random port between 4500-4999
    local port=$((4500 + RANDOM % 500))
    local pid=""

    info "Starting SvelteKit on port $port..."

    # Start the built server in the background
    PORT=$port ORIGIN="http://localhost:$port" node build/index.js &>/dev/null &
    pid=$!

    # Wait for the server to be ready (up to 10 seconds)
    local attempts=0
    local ready=false
    while [ $attempts -lt 20 ]; do
        if curl -sf -o /dev/null "http://localhost:$port/" 2>/dev/null; then
            ready=true
            break
        fi
        sleep 0.5
        attempts=$((attempts + 1))
    done

    if [ "$ready" = true ]; then
        # Verify we get a 200 response
        local status_code
        status_code=$(curl -sf -o /dev/null -w "%{http_code}" "http://localhost:$port/" 2>/dev/null || echo "000")

        if [ "$status_code" = "200" ] || [ "$status_code" = "302" ]; then
            ok "Smoke test passed (HTTP $status_code on port $port)"
        else
            warn "Smoke test: unexpected status $status_code"
        fi
    else
        warn "Smoke test: server did not start within 10 seconds"
    fi

    # Clean up: kill the temporary server
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null || true
    fi

    cd "$PROJECT_ROOT"
}
