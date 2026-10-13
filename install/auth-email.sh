#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# ARIA — Auth & Email Configuration Module
# ═══════════════════════════════════════════════════════════════════
# Sourced by install.sh — do not execute directly.

# ── 1. Collect User Emails ────────────────────────────────────────
auth_collect_emails() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Configuring access emails..."

    # Check if already configured
    local existing_emails
    existing_emails=$(read_env_var "ARIA_ALLOWED_EMAILS")
    if [ -n "$existing_emails" ] && [ "$existing_emails" != "you@example.com" ]; then
        ok "Allowed emails already configured: $existing_emails"
        ask "Change them? [y/N]:"
        read -r change_emails
        if [[ ! "$change_emails" =~ ^[yY] ]]; then
            export AUTH_PRIMARY_EMAIL=$(echo "$existing_emails" | cut -d',' -f1)
            export AUTH_ALL_EMAILS="$existing_emails"
            return 0
        fi
    fi

    echo ""
    info "ARIA uses email authentication: you receive a 6-digit code"
    info "to sign in to the web interface."
    echo ""

    # Primary email
    local primary_email=""
    while true; do
        ask "Your email (to receive access codes):"
        read -r primary_email
        primary_email=$(echo "$primary_email" | tr '[:upper:]' '[:lower:]' | xargs)

        if [ -z "$primary_email" ]; then
            warn "Email is required for web access"
            continue
        fi

        if validate_email "$primary_email"; then
            break
        else
            warn "Invalid email format. Try again."
        fi
    done

    ok "Primary email: $primary_email"
    export AUTH_PRIMARY_EMAIL="$primary_email"

    # Additional emails
    local all_emails="$primary_email"
    echo ""
    ask "Add more authorized emails? [y/N]:"
    read -r add_more

    if [[ "$add_more" =~ ^[yY] ]]; then
        echo ""
        info "Enter one email per line. Type 'q' to finish."
        while true; do
            ask "Additional email (or 'q'):"
            read -r extra_email
            [ "$extra_email" = "q" ] && break

            extra_email=$(echo "$extra_email" | tr '[:upper:]' '[:lower:]' | xargs)
            if validate_email "$extra_email"; then
                all_emails="$all_emails,$extra_email"
                ok "Added: $extra_email"
            else
                warn "Invalid format, skipped"
            fi
        done
    fi

    # Write to .env
    env_set "ARIA_ALLOWED_EMAILS" "$all_emails"
    ok "Emails configured in .env"
    export AUTH_ALL_EMAILS="$all_emails"
}

# ── 2. Configure Resend ──────────────────────────────────────────
auth_setup_resend() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Configuring email service (Resend)..."

    # Check if already configured
    local existing_key
    existing_key=$(read_env_var "RESEND_API_KEY")
    if [ -n "$existing_key" ] && [ "$existing_key" != "re_xxxxxxxxxxxx" ]; then
        ok "Resend API key already configured (${existing_key:0:6}...)"
        ask "Change it? [y/N]:"
        read -r change_key
        if [[ ! "$change_key" =~ ^[yY] ]]; then
            export AUTH_RESEND_CONFIGURED=true
            return 0
        fi
    fi

    echo ""
    info "Resend sends OTP codes via email."
    info "Create a free account at: https://resend.com"
    info "The free tier allows sending to your own email."
    echo ""

    ask "Resend API key (starts with 're_', or Enter to skip):"
    read -rs resend_key
    echo ""

    if [ -z "$resend_key" ]; then
        warn "Resend skipped — GUI login won't work"
        info "You can still use ARIA in terminal: python aria.py"
        info "Or configure RESEND_API_KEY in .env later."
        export AUTH_RESEND_CONFIGURED=false
        return 0
    fi

    # Validate format
    if [[ ! "$resend_key" =~ ^re_ ]] || [ ${#resend_key} -lt 20 ]; then
        warn "Key doesn't look valid (should start with 're_' and be 20+ chars)"
        ask "Use anyway? [y/N]:"
        read -r use_anyway
        if [[ ! "$use_anyway" =~ ^[yY] ]]; then
            export AUTH_RESEND_CONFIGURED=false
            return 0
        fi
    fi

    # Verify API key with a real call
    if has_cmd curl; then
        info "Verifying API key..."
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: Bearer $resend_key" \
            "https://api.resend.com/domains" 2>/dev/null)

        if [ "$http_code" = "200" ]; then
            ok "API key verified"
        elif [ "$http_code" = "401" ] || [ "$http_code" = "403" ]; then
            warn "API key invalid (HTTP $http_code)"
            ask "Continue anyway? [y/N]:"
            read -r continue_anyway
            if [[ ! "$continue_anyway" =~ ^[yY] ]]; then
                export AUTH_RESEND_CONFIGURED=false
                return 0
            fi
        else
            info "Could not verify (HTTP $http_code) — continuing"
        fi
    fi

    # Write key (using env_set to avoid exposing in process list)
    env_set "RESEND_API_KEY" "$resend_key"

    # Configure FROM email
    echo ""
    info "Resend free tier only allows sending from onboarding@resend.dev"
    info "If you have a verified domain in Resend, you can use your own sender."
    echo ""
    ask "Sender email [ARIA <onboarding@resend.dev>]:"
    read -r from_email
    from_email="${from_email:-ARIA <onboarding@resend.dev>}"
    env_set "RESEND_FROM_EMAIL" "$from_email"
    ok "Sender: $from_email"

    export AUTH_RESEND_CONFIGURED=true
}

# ── 3. Generate Internal Secret ──────────────────────────────────
auth_generate_secret() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Generating internal secret..."

    local current_secret
    current_secret=$(read_env_var "ARIA_INTERNAL_SECRET")

    if [ -n "$current_secret" ] && [ ${#current_secret} -ge 32 ]; then
        ok "ARIA_INTERNAL_SECRET already configured"
        return 0
    fi

    local secret
    secret=$(generate_secret)
    env_set "ARIA_INTERNAL_SECRET" "$secret"
    ok "Internal secret generated"
    info "This secret secures the SvelteKit → FastAPI communication"
    info "To rotate: python3 -c \"import secrets; print(secrets.token_hex(32))\""
}

# ── 4. Configure Domain ──────────────────────────────────────────
auth_configure_domain() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Configuring domain..."

    echo ""
    info "Deployment environment:"
    info "  1) Local / development (localhost)"
    info "  2) Production with custom domain"
    echo ""
    ask "Select [1]:"
    read -r deploy_mode
    deploy_mode="${deploy_mode:-1}"

    if [ "$deploy_mode" = "2" ]; then
        ask "ARIA domain (e.g. aria.mydomain.com):"
        read -r domain
        domain=$(echo "$domain" | tr -d ' ' | sed 's|https\?://||')

        if [ -z "$domain" ]; then
            warn "No domain provided — configuring for localhost"
            export AUTH_DOMAIN=""
            export AUTH_DEPLOY_MODE="dev"
            return 0
        fi

        env_set "ARIA_ORIGIN" "https://$domain"
        env_set "ARIA_CORS_ORIGINS" "https://$domain"
        ok "Domain configured: $domain"

        # DNS check (optional)
        if has_cmd dig; then
            if dig +short "$domain" 2>/dev/null | head -1 | grep -qE '^[0-9]'; then
                ok "DNS resolves for $domain"
            else
                warn "$domain does not resolve — configure DNS before obtaining SSL"
            fi
        fi

        export AUTH_DOMAIN="$domain"
        export AUTH_DEPLOY_MODE="production"
    else
        info "Development mode: localhost without SSL"
        export AUTH_DOMAIN=""
        export AUTH_DEPLOY_MODE="dev"
    fi
}

# ── 5. DNS Guidance (for custom domain) ──────────────────────────
auth_dns_guidance() {
    if [ -z "$AUTH_DOMAIN" ]; then
        return 0
    fi

    local from_email
    from_email=$(read_env_var "RESEND_FROM_EMAIL")

    # Only show DNS guidance if using a custom domain sender
    if [[ "$from_email" == *"onboarding@resend.dev"* ]]; then
        return 0
    fi

    step "$CURRENT_STEP/$TOTAL_STEPS" "DNS configuration guide..."

    echo ""
    info "To send emails from your domain, add these DNS records:"
    echo ""
    info "  1. SPF (TXT):   @ → v=spf1 include:amazonses.com ~all"
    info "  2. DKIM (CNAME): See Resend Dashboard → Domains → DNS records"
    info "  3. DMARC (TXT):  _dmarc → v=DMARC1; p=quarantine; rua=mailto:dmarc@$AUTH_DOMAIN;"
    echo ""
    info "Verify at: https://resend.com/domains"
    info "Without these records, emails may go to spam."
}

# ── 6. Security Checks ──────────────────────────────────────────
auth_security_checks() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Security checks..."

    # .env permissions
    chmod 600 .env 2>/dev/null
    ok ".env permissions → 600"

    # .gitignore check
    if [ -f .gitignore ]; then
        if grep -q "^\.env$" .gitignore 2>/dev/null; then
            ok ".env is in .gitignore"
        else
            warn ".env is NOT in .gitignore — risk of exposing secrets"
            info "Add '.env' to .gitignore"
        fi
    fi

    # Check for exposed secrets
    if ls client_secret_*.json &>/dev/null 2>&1; then
        warn "client_secret_*.json file found in project root"
        info "Make sure it is in .gitignore and .dockerignore"
    fi

    # data/auth permissions
    if [ -d data/auth ]; then
        chmod 700 data/auth 2>/dev/null
        ok "data/auth/ → permissions 700"
    fi
}

# ── 7. Send Test Email (non-interactive — call after decision is made) ──
auth_send_test_email() {
    step "$CURRENT_STEP/$TOTAL_STEPS" "Sending test email..."

    local api_key from_email
    api_key=$(read_env_var "RESEND_API_KEY")
    from_email=$(read_env_var "RESEND_FROM_EMAIL")
    from_email="${from_email:-ARIA <onboarding@resend.dev>}"

    local response http_code
    response=$(curl -s -w "\n%{http_code}" \
        -X POST "https://api.resend.com/emails" \
        -H "Authorization: Bearer $api_key" \
        -H "Content-Type: application/json" \
        -d "{
            \"from\": \"$from_email\",
            \"to\": [\"$AUTH_PRIMARY_EMAIL\"],
            \"subject\": \"ARIA — Setup successful\",
            \"text\": \"If you receive this email, ARIA is correctly configured to send access codes. This is NOT a real access code.\"
        }" 2>/dev/null)

    http_code=$(echo "$response" | tail -1)
    if [ "$http_code" = "200" ]; then
        ok "Test email sent to $AUTH_PRIMARY_EMAIL"
        info "Check your inbox (and spam) to confirm."
    else
        warn "Error sending email (HTTP $http_code)"
        info "Check RESEND_API_KEY and RESEND_FROM_EMAIL in .env"
        info "With free tier, you can only send to the Resend account holder's email."
    fi
}

# ── 8. Dev Mode Fallback (no Resend) ────────────────────────────
auth_dev_fallback() {
    if [ "$AUTH_RESEND_CONFIGURED" = "true" ]; then
        return 0
    fi

    if [ "$AUTH_DEPLOY_MODE" = "production" ]; then
        warn "Production without Resend: users won't be able to log in"
        info "Configure RESEND_API_KEY in .env to enable login"
        return 0
    fi

    echo ""
    info "Development mode without Resend:"
    info "  • You can start the backend directly: python aria.py"
    info "  • To use the GUI without email, configure RESEND_API_KEY later"
    info "  • Empty ARIA_INTERNAL_SECRET = auth disabled on FastAPI side"
    echo ""

    # Clear the secret for dev mode
    ask "Disable FastAPI auth for development? [Y/n]:"
    read -r disable_auth
    if [[ ! "$disable_auth" =~ ^[nN] ]]; then
        env_set "ARIA_INTERNAL_SECRET" ""
        ok "FastAPI auth disabled (development mode)"
        warn "WARNING: FastAPI will accept unauthenticated requests."
        info "Only use this on localhost. Never in production."
    fi
}

# ── 9. Firewall Guidance (production) ────────────────────────────
auth_firewall_guidance() {
    if [ "$AUTH_DEPLOY_MODE" != "production" ]; then
        return 0
    fi

    step "$CURRENT_STEP/$TOTAL_STEPS" "Firewall guide..."

    echo ""
    info "RECOMMENDED FIREWALL RULES:"
    echo ""
    info "  With UFW (Ubuntu/Debian):"
    info "    sudo ufw default deny incoming"
    info "    sudo ufw default allow outgoing"
    info "    sudo ufw allow 22/tcp    # SSH"
    info "    sudo ufw allow 80/tcp    # HTTP (redirects to HTTPS)"
    info "    sudo ufw allow 443/tcp   # HTTPS"
    info "    sudo ufw enable"
    echo ""
    info "  IMPORTANT: Ports 3000 and 8000 must NOT be exposed."
    info "  Nginx acts as reverse proxy (443 → localhost:3000)."
    info "  docker-compose.yml already binds to 127.0.0.1 (correct)."
}
