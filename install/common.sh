#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# ARIA — Shared Utilities for Installation Scripts
# ═══════════════════════════════════════════════════════════════════

# ── Colors ──────────────────────────────────────────────────────────
G='\033[92m'; Y='\033[93m'; R='\033[91m'; C='\033[96m'
B='\033[1m'; D='\033[2m'; N='\033[0m'

step()  { echo -e "\n${C}${B}[$1]${N} $2"; }
ok()    { echo -e "  ${G}✓${N} $1"; }
warn()  { echo -e "  ${Y}!${N} $1"; }
fail()  { echo -e "  ${R}✗${N} $1"; exit 1; }
info()  { echo -e "  ${D}$1${N}"; }
ask()   { echo -en "  ${D}$1${N} "; }
banner(){ echo -e "\n${C}═══════════════════════════════════════${N}"; echo -e "${C}  $1${N}"; echo -e "${C}═══════════════════════════════════════${N}"; }

# ── Cross-platform sed -i ──────────────────────────────────────────
sedi() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "$@"
    else
        sed -i "$@"
    fi
}

# ── Safe .env writer (avoids leaking secrets to process list) ──────
# Usage: env_set KEY VALUE [FILE]
env_set() {
    local key="$1" val="$2" file="${3:-.env}"
    # Use awk so the value never appears in a sed command line
    awk -v k="$key" -v v="$val" 'BEGIN{FS=OFS="="} $1==k{$2=v; found=1} {print} END{if(!found) print k"="v}' "$file" > "${file}.tmp" \
        && mv "${file}.tmp" "$file"
}

# ── Platform Detection ─────────────────────────────────────────────
# Sets: ARIA_OS (linux|macos|wsl), ARIA_PKG_MGR (apt|dnf|brew|pacman),
#       ARIA_IS_WSL (true|false), ARIA_ARCH (x86_64|arm64)
detect_platform() {
    ARIA_IS_WSL=false
    ARIA_ARCH=$(uname -m)

    case "$(uname -s)" in
        Linux)
            ARIA_OS="linux"
            if grep -qi "microsoft" /proc/version 2>/dev/null; then
                ARIA_IS_WSL=true
                ARIA_OS="wsl"
            fi
            if command -v apt-get &>/dev/null; then
                ARIA_PKG_MGR="apt"
            elif command -v dnf &>/dev/null; then
                ARIA_PKG_MGR="dnf"
            elif command -v pacman &>/dev/null; then
                ARIA_PKG_MGR="pacman"
            else
                ARIA_PKG_MGR="unknown"
            fi
            ;;
        Darwin)
            ARIA_OS="macos"
            ARIA_PKG_MGR="brew"
            [[ "$ARIA_ARCH" == "arm64" ]] || ARIA_ARCH="x86_64"
            ;;
        *)
            ARIA_OS="unknown"
            ARIA_PKG_MGR="unknown"
            ;;
    esac

    export ARIA_OS ARIA_PKG_MGR ARIA_IS_WSL ARIA_ARCH
}

# ── Disk Space Check ───────────────────────────────────────────────
# Usage: check_disk_space <path> <min_mb>
check_disk_space() {
    local path="$1" min_mb="$2"
    local available_mb
    available_mb=$(df -m "$path" 2>/dev/null | awk 'NR==2{print $4}')

    if [ -z "$available_mb" ]; then
        return 0  # can't determine, skip
    fi
    if [ "$available_mb" -lt "$min_mb" ] 2>/dev/null; then
        warn "Low disk space: ${available_mb}MB available, ${min_mb}MB required"
        return 1
    fi
    return 0
}

# ── WSL /mnt/c/ Performance Warning ───────────────────────────────
check_wsl_path() {
    if [[ "$ARIA_IS_WSL" == "true" ]] && [[ "$PROJECT_ROOT" == /mnt/* ]]; then
        echo ""
        warn "PERFORMANCE: Project is on a Windows filesystem (/mnt/c/)."
        warn "npm/pip operations will be 5-10x slower."
        info "For better performance, move the project to ~/ :"
        info "  cp -r $PROJECT_ROOT ~/ARIA"
        info "  cd ~/ARIA && ./install/install.sh"
        echo ""
        ask "Continue anyway? [Y/n]:"
        read -r WSL_CONTINUE
        if [[ "$WSL_CONTINUE" =~ ^[nN] ]]; then
            echo -e "  ${D}Move the project and run again.${N}"
            exit 0
        fi
    fi
}

# ── Validate Email Format ──────────────────────────────────────────
validate_email() {
    local email="$1"
    [[ "$email" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]]
}

# ── Generate Secure Token ─────────────────────────────────────────
generate_secret() {
    if command -v python3 &>/dev/null; then
        python3 -c "import secrets; print(secrets.token_hex(32))"
    elif command -v openssl &>/dev/null; then
        openssl rand -hex 32
    else
        head -c 32 /dev/urandom | xxd -p | tr -d '\n'
        echo ""
    fi
}

# ── Check if command exists ────────────────────────────────────────
has_cmd() {
    command -v "$1" &>/dev/null
}

# ── Read .env variable ─────────────────────────────────────────────
read_env_var() {
    local var_name="$1" env_file="${2:-.env}"
    if [ -f "$env_file" ]; then
        grep "^${var_name}=" "$env_file" 2>/dev/null | head -1 | cut -d'=' -f2- | sed 's/^["'\''"]//;s/["'\''"]$//'
    fi
}

# ── Network Connectivity Check ────────────────────────────────────
# Usage: check_network
# Returns 0 if internet is reachable, 1 if not.
# Sets ARIA_NETWORK_OK=true/false for downstream checks.
check_network() {
    ARIA_NETWORK_OK=false
    local targets=("https://pypi.org" "https://registry.npmjs.org" "https://huggingface.co")

    for url in "${targets[@]}"; do
        if curl -sf --max-time 5 -o /dev/null "$url" 2>/dev/null; then
            ARIA_NETWORK_OK=true
            export ARIA_NETWORK_OK
            return 0
        fi
    done

    export ARIA_NETWORK_OK
    return 1
}

# ── Cleanup trap ───────────────────────────────────────────────────
cleanup_on_interrupt() {
    echo ""
    echo -e "${Y}!${N} Installation interrupted."
    echo -e "${D}  It is safe to re-run: ./install/install.sh${N}"
    echo -e "${D}  Already-installed components will be detected automatically.${N}"
    exit 130
}
