"""
ARIA - Security Configuration System
=====================================
Configurable security modes that balance freedom with protection.

William designed ARIA with freedom in mind.
But freedom comes with responsibility.
This module lets ARIA (and users) choose their level of protection.
"""

import os
import threading
from enum import Enum
from typing import Tuple, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

# Import language system for translations
try:
    from .language import get_text, get_current_language, TRANSLATIONS
    LANGUAGE_AVAILABLE = True
except ImportError:
    LANGUAGE_AVAILABLE = False
    def get_text(key, **kwargs):
        # Fallback to English defaults
        defaults = {
            "security_aria_title": "ARIA - SECURITY CONFIGURATION",
            "security_intro": "ARIA was designed with total freedom.\nPlease choose security level:",
            "security_free_name": "FREE (No Restrictions)",
            "security_protected_name": "PROTECTED (Recommended)",
            "security_paranoid_name": "PARANOID (Maximum Security)",
            "security_free_desc": "No restrictions (DANGEROUS)",
            "security_protected_desc": "Protected (RECOMMENDED)",
            "security_paranoid_desc": "Maximum security",
            "security_choose_prompt": "Which mode? [1/2/3] (default: 2)",
            "confirm_free_mode": "Type 'I ACCEPT THE RISK' to confirm",
            "invalid_confirmation": "Invalid confirmation. Using PROTECTED mode.",
            "invalid_option": "Invalid option. Please choose 1, 2 or 3.",
            "interrupted_using_protected": "Interrupted. Using PROTECTED mode.",
            "security_mode_activated": "✓ {mode} mode activated for this session",
            "confirmed_by": "Confirmed by",
            "session": "Session",
            "risk_level": "Risk level",
            "recommended_for": "Recommended for",
            "warnings": "Warnings",
            "security_not_configured": "⚠️ Security not configured",
            "dangerous_action": "⚠️ Potentially dangerous action: {action}",
            "continue_question": "Continue? [y/N]",
            "security_free_warning": "⚠️ WARNING: FREE mode selected",
            "security_warning_free": "⚠️ DANGER: All commands allowed without restrictions",
        }
        text = defaults.get(key, f"[{key}]")
        if kwargs:
            try:
                text = text.format(**kwargs)
            except KeyError:
                pass
        return text


class SecurityMode(Enum):
    """Security modes for ARIA"""
    FREE = "free"           # No restrictions - original design
    PROTECTED = "protected" # Block dangerous patterns, allow bypass
    PARANOID = "paranoid"   # Whitelist only, no bypass


@dataclass
class SecurityConfig:
    """Current security configuration"""
    mode: SecurityMode
    confirmed_by: str
    confirmed_at: str
    session_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "confirmed_by": self.confirmed_by,
            "confirmed_at": self.confirmed_at,
            "session_id": self.session_id
        }


# Global security state (set at startup)
_current_config: Optional[SecurityConfig] = None

# Thread lock for log file operations
_log_lock = threading.Lock()


# ============================================
# DANGEROUS PATTERNS (used in protected/paranoid modes)
# ============================================

DANGEROUS_COMMAND_PATTERNS = [
    # Destructive file operations
    "rm -rf /", "rm -rf /*", "rm -rf ~", "rm -rf $HOME",
    "del /s /q c:\\", "format c:", "rmdir /s /q",
    # System damage
    "mkfs", "dd if=", "> /dev/sd", "> /dev/null",
    ":(){ :|:& };:", "fork bomb",
    # Permission abuse
    "chmod -R 777 /", "chmod 777 /",
    # Dangerous downloads
    "curl | bash", "curl | sh", "wget | bash", "wget | sh",
    "curl -s | bash", "wget -q | sh",
    # System control
    "shutdown", "reboot", "init 0", "init 6",
    "systemctl poweroff", "systemctl reboot",
    # Credential access
    "cat /etc/shadow",
    # Network attacks
    "nc -l", "ncat -l",
]

PRIVATE_IP_RANGES = [
    "127.", "10.", "172.16.", "172.17.", "172.18.", "172.19.",
    "172.20.", "172.21.", "172.22.", "172.23.", "172.24.", "172.25.",
    "172.26.", "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.", "169.254.", "0.", "localhost", "::1",
    "metadata.google", "169.254.169.254",
]

# Commands allowed in paranoid mode
PARANOID_WHITELIST = [
    "ls", "pwd", "echo", "cat", "head", "tail", "grep", "find",
    "python", "python3", "pip list", "pip show",
    "git status", "git log", "git diff", "git branch",
    "date", "whoami", "hostname", "uname",
]


# ============================================
# SECURITY CHECK FUNCTIONS
# ============================================

def get_current_mode() -> SecurityMode:
    """Get the current security mode"""
    if _current_config is None:
        return SecurityMode.PROTECTED  # Default if not configured
    return _current_config.mode


def is_dangerous_command(command: str) -> Tuple[bool, str]:
    """Check if a command is dangerous"""
    mode = get_current_mode()

    # In FREE mode, nothing is blocked
    if mode == SecurityMode.FREE:
        return False, ""

    command_lower = command.lower().strip()

    # In PARANOID mode, only whitelist is allowed
    if mode == SecurityMode.PARANOID:
        # Check for null bytes (can truncate strings in C-based parsers)
        if '\x00' in command:
            return True, "Command contains null bytes"

        # Check for shell metacharacters that could bypass whitelist
        SHELL_METACHARACTERS = [';', '|', '&', '$', '`', '(', ')', '{', '}', '<', '>', '\n']
        has_metachar = any(c in command for c in SHELL_METACHARACTERS)
        if has_metachar:
            return True, "Command contains shell metacharacters"

        # Check for Unicode homoglyphs of dangerous characters
        # Maps visually similar Unicode chars to the ASCII chars they mimic
        HOMOGLYPH_MAP = {
            '\uff1b': ';',  # fullwidth semicolon
            '\uff5c': '|',  # fullwidth vertical line
            '\uff06': '&',  # fullwidth ampersand
            '\uff04': '$',  # fullwidth dollar sign
            '\uff40': '`',  # fullwidth grave accent
            '\uff08': '(',  # fullwidth left paren
            '\uff09': ')',  # fullwidth right paren
            '\uff1c': '<',  # fullwidth less-than
            '\uff1e': '>',  # fullwidth greater-than
            '\u2044': '/',  # fraction slash
            '\u2215': '/',  # division slash
            '\uff0f': '/',  # fullwidth solidus
        }
        for homoglyph in HOMOGLYPH_MAP:
            if homoglyph in command:
                return True, f"Command contains Unicode homoglyph for '{HOMOGLYPH_MAP[homoglyph]}'"
        is_allowed = any(command_lower.startswith(allowed) for allowed in PARANOID_WHITELIST)
        if not is_allowed:
            return True, f"Command not in whitelist (paranoid mode)"

    # In PROTECTED mode, check dangerous patterns
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if pattern.lower() in command_lower:
            return True, f"Dangerous pattern detected: {pattern}"

    # Check for command substitution with destructive commands
    if "$(" in command or "`" in command:
        if "rm " in command_lower or "del " in command_lower:
            return True, "Command substitution with destructive command"

    return False, ""


def is_private_url(url: str) -> Tuple[bool, str]:
    """Check if URL is private/internal"""
    mode = get_current_mode()

    # In FREE mode, nothing is blocked
    if mode == SecurityMode.FREE:
        return False, ""

    url_lower = url.lower()

    for private_range in PRIVATE_IP_RANGES:
        if private_range in url_lower:
            return True, f"Private/internal URL blocked: {private_range}"

    return False, ""


def validate_package_name(package: str) -> Tuple[bool, str]:
    """Validate package name for installation"""
    import re

    mode = get_current_mode()

    # In FREE mode, no validation
    if mode == SecurityMode.FREE:
        return True, package

    # In PARANOID mode, block all package installations
    if mode == SecurityMode.PARANOID:
        return False, "Package installation disabled in paranoid mode"

    # In PROTECTED mode, validate the name
    if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9._\-\[\],<>=!~]*$', package):
        return False, f"Invalid package name format: {package}"

    dangerous_chars = [';', '|', '&', '$', '`', '(', ')', '{', '}', '\n', '\r']
    for char in dangerous_chars:
        if char in package and char not in ['<', '>', '[', ']', ',']:
            return False, f"Invalid character in package name: {char}"

    return True, package


# ============================================
# STARTUP CONFIGURATION
# ============================================

def get_mode_description(mode: SecurityMode) -> Dict[str, Any]:
    """Get detailed description of a security mode - now with translations"""

    # Get translated mode names
    mode_names = {
        SecurityMode.FREE: f"🔓 {get_text('security_free_name')}",
        SecurityMode.PROTECTED: f"🛡️ {get_text('security_protected_name')}",
        SecurityMode.PARANOID: f"🔒 {get_text('security_paranoid_name')}",
    }

    # Risk levels with translations
    risk_levels = {
        SecurityMode.FREE: "🔴 CRITICAL",
        SecurityMode.PROTECTED: "🟡 MODERATE",
        SecurityMode.PARANOID: "🟢 MINIMAL",
    }

    # Recommendations with translations
    recommendations = {
        SecurityMode.FREE: "Personal dev, isolated sandbox, VMs",
        SecurityMode.PROTECTED: "General use, real data development",
        SecurityMode.PARANOID: "Production, public servers, demos",
    }

    # Warnings for each mode
    warnings = {
        SecurityMode.FREE: [
            get_text('security_warning_free'),
            "⚠️ Can access ANY URL (including cloud metadata)",
            "⚠️ Can install ANY package",
            "⚠️ Prompt injection can destroy system",
            "⚠️ NO protection against destructive commands",
        ],
        SecurityMode.PROTECTED: [
            "⚡ Dangerous commands (rm -rf /, format, etc.) BLOCKED",
            "⚡ Private/localhost URLs BLOCKED (SSRF protection)",
            "⚡ Package names VALIDATED",
            "✓ Bypass available for legitimate cases",
            "✓ Everything logged",
        ],
        SecurityMode.PARANOID: [
            "🔒 ONLY whitelisted commands allowed",
            "🔒 Package installation DISABLED",
            "🔒 Network access VERY restricted",
            "🔒 NO bypass available",
            "🔒 Very limited functionality",
        ],
    }

    descriptions = {
        SecurityMode.FREE: {
            "name": mode_names[SecurityMode.FREE],
            "color": "\033[91m",  # Red
            "description": get_text('security_free_desc').split('\n')[0],
            "warnings": warnings[SecurityMode.FREE],
            "recommended_for": recommendations[SecurityMode.FREE],
            "risk_level": risk_levels[SecurityMode.FREE]
        },
        SecurityMode.PROTECTED: {
            "name": mode_names[SecurityMode.PROTECTED],
            "color": "\033[93m",  # Yellow
            "description": get_text('security_protected_desc').split('\n')[0],
            "warnings": warnings[SecurityMode.PROTECTED],
            "recommended_for": recommendations[SecurityMode.PROTECTED],
            "risk_level": risk_levels[SecurityMode.PROTECTED]
        },
        SecurityMode.PARANOID: {
            "name": mode_names[SecurityMode.PARANOID],
            "color": "\033[92m",  # Green
            "description": get_text('security_paranoid_desc').split('\n')[0],
            "warnings": warnings[SecurityMode.PARANOID],
            "recommended_for": recommendations[SecurityMode.PARANOID],
            "risk_level": risk_levels[SecurityMode.PARANOID]
        }
    }

    return descriptions.get(mode, descriptions[SecurityMode.PROTECTED])


def display_security_banner(mode: SecurityMode) -> None:
    """Display the security mode banner"""
    info = get_mode_description(mode)
    reset = "\033[0m"
    bold = "\033[1m"

    print("\n" + "=" * 70)
    print(f"{bold}              {get_text('security_aria_title')}{reset}")
    print("=" * 70)
    print(f"\n{info['color']}{bold}{info['name']}{reset}")
    print(f"\n{info['description']}")
    print(f"\n{get_text('risk_level')}: {info['risk_level']}")
    print(f"\n{get_text('recommended_for')}: {info['recommended_for']}")
    print("\n" + "-" * 70)
    print(f"{bold}{get_text('warnings')}:{reset}")
    for warning in info['warnings']:
        print(f"  {warning}")
    print("-" * 70)


def prompt_security_mode() -> SecurityMode:
    """Interactive prompt to select security mode at startup"""

    print("\n" + "=" * 70)
    print(f"\033[1m          {get_text('security_aria_title')}\033[0m")
    print("=" * 70)

    print(f"\n{get_text('security_intro')}\n")

    # Display options with colors
    print(f"\033[91m[1] 🔓 {get_text('security_free_name')}\033[0m")
    print(f"    {get_text('security_free_desc')}\n")

    print(f"\033[93m[2] 🛡️ {get_text('security_protected_name')}\033[0m")
    print(f"    {get_text('security_protected_desc')}\n")

    print(f"\033[92m[3] 🔒 {get_text('security_paranoid_name')}\033[0m")
    print(f"    {get_text('security_paranoid_desc')}\n")

    print("-" * 70)

    # Get valid confirmations for FREE mode based on language
    valid_confirmations = ["I ACCEPT THE RISK", "YES", "CONFIRM"]
    if LANGUAGE_AVAILABLE:
        try:
            lang_code = get_current_language().value
            confirmations = TRANSLATIONS.get("free_mode_confirmations", {}).get(lang_code, [])
            if confirmations:
                valid_confirmations = [c.upper() for c in confirmations]
        except Exception:
            pass

    while True:
        try:
            choice = input(f"\n{get_text('security_choose_prompt')}: ").strip()

            if choice == "" or choice == "2":
                mode = SecurityMode.PROTECTED
            elif choice == "1":
                # Double confirmation for FREE mode
                print(f"\n\033[91m{get_text('security_free_warning')}\033[0m")
                confirm = input(f"\n{get_text('confirm_free_mode')}: ")
                if confirm.strip().upper() in valid_confirmations:
                    mode = SecurityMode.FREE
                else:
                    print(get_text('invalid_confirmation'))
                    mode = SecurityMode.PROTECTED
            elif choice == "3":
                mode = SecurityMode.PARANOID
            else:
                print(get_text('invalid_option'))
                continue

            break

        except KeyboardInterrupt:
            print(f"\n\n{get_text('interrupted_using_protected')}")
            mode = SecurityMode.PROTECTED
            break
        except EOFError:
            print(f"\n{get_text('interrupted_using_protected')}")
            mode = SecurityMode.PROTECTED
            break

    return mode


def configure_security(mode: SecurityMode = None, user: str = "unknown") -> SecurityConfig:
    """Configure security for the current session"""
    global _current_config

    # If no mode specified, prompt interactively
    if mode is None:
        mode = prompt_security_mode()

    # Create configuration
    _current_config = SecurityConfig(
        mode=mode,
        confirmed_by=user,
        confirmed_at=datetime.now().isoformat(),
        session_id=datetime.now().strftime("%Y%m%d_%H%M%S")
    )

    # Display the banner
    display_security_banner(mode)

    # Confirmation with translations
    print(f"\n\033[1m{get_text('security_mode_activated', mode=mode.value.upper())}\033[0m")
    print(f"  {get_text('confirmed_by')}: {user}")
    print(f"  {get_text('session')}: {_current_config.session_id}")
    print("=" * 70 + "\n")

    # Log the configuration
    _log_security_config(_current_config)

    return _current_config


def _log_security_config(config: SecurityConfig) -> None:
    """Log the security configuration"""
    log_dir = "data/logs"
    os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, "security.log")
    with _log_lock:
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"[{config.confirmed_at}] Session {config.session_id}: "
                    f"Mode={config.mode.value}, User={config.confirmed_by}\n")


def get_security_status() -> str:
    """Get current security status as string"""
    if _current_config is None:
        return get_text('security_not_configured')

    mode = _current_config.mode
    info = get_mode_description(mode)

    return f"{info['name']} | {get_text('session')}: {_current_config.session_id}"


# ============================================
# QUICK ACCESS FUNCTIONS
# ============================================

def is_free_mode() -> bool:
    """Check if running in FREE mode"""
    return get_current_mode() == SecurityMode.FREE


def is_protected_mode() -> bool:
    """Check if running in PROTECTED mode"""
    return get_current_mode() == SecurityMode.PROTECTED


def is_paranoid_mode() -> bool:
    """Check if running in PARANOID mode"""
    return get_current_mode() == SecurityMode.PARANOID


def require_confirmation(action: str) -> bool:
    """Ask for confirmation before dangerous action (in protected mode)"""
    if is_free_mode():
        return True  # No confirmation needed

    if is_paranoid_mode():
        return False  # Not allowed at all

    # Protected mode - ask for confirmation
    print(f"\n{get_text('dangerous_action', action=action)}")
    response = input(f"{get_text('continue_question')}: ").strip().lower()
    # Accept various forms of "yes" in different languages
    return response in ['s', 'si', 'sí', 'y', 'yes', 'o', 'oui', 'да', 'd', 'j', 'ja', 'sim']
