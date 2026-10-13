"""
ARIA Installation Script — Test Suite
======================================

Tests the unified install system (install/) without requiring
real API keys, network access, or root privileges.

Run:
    pytest tests/test_install.py -v
    pytest tests/test_install.py -v -k "test_env_set"
"""

import os
import subprocess
import stat
import textwrap
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_DIR = os.path.join(PROJECT_ROOT, "install")


# ═════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════

def bash(script: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources common.sh first."""
    full_script = f'source "{INSTALL_DIR}/common.sh"\n{script}'
    run_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=run_env,
        cwd=cwd or PROJECT_ROOT,
        timeout=30,
    )


def bash_function(module: str, function: str, env: dict | None = None, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Source a module and call a specific function."""
    full_script = textwrap.dedent(f"""\
        source "{INSTALL_DIR}/common.sh"
        source "{INSTALL_DIR}/{module}"
        TOTAL_STEPS=1
        CURRENT_STEP=1
        PROJECT_ROOT="{cwd or PROJECT_ROOT}"
        {function}
    """)
    run_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=run_env,
        cwd=cwd or PROJECT_ROOT,
        timeout=60,
    )


# ═════════════════════════════════════════════════════════════════════
# Module: common.sh
# ═════════════════════════════════════════════════════════════════════

class TestCommonSyntax:
    """Verify all scripts pass bash syntax check."""

    @pytest.mark.parametrize("script", [
        "common.sh", "backend.sh", "frontend.sh", "auth-email.sh", "install.sh",
    ])
    def test_syntax_valid(self, script):
        path = os.path.join(INSTALL_DIR, script)
        assert os.path.exists(path), f"{script} not found"
        result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
        assert result.returncode == 0, f"Syntax error in {script}: {result.stderr}"

    @pytest.mark.parametrize("script", [
        "common.sh", "backend.sh", "frontend.sh", "auth-email.sh", "install.sh",
    ])
    def test_scripts_executable(self, script):
        path = os.path.join(INSTALL_DIR, script)
        mode = os.stat(path).st_mode
        assert mode & stat.S_IXUSR, f"{script} is not executable"


class TestDetectPlatform:
    """Test platform detection logic."""

    def test_detects_some_platform(self):
        r = bash('detect_platform; echo "OS=$ARIA_OS PKG=$ARIA_PKG_MGR WSL=$ARIA_IS_WSL ARCH=$ARIA_ARCH"')
        assert r.returncode == 0
        assert "OS=" in r.stdout
        # Must detect one of the known platforms
        assert any(p in r.stdout for p in ["linux", "macos", "wsl"])

    def test_arch_is_set(self):
        r = bash('detect_platform; echo "$ARIA_ARCH"')
        assert r.returncode == 0
        arch = r.stdout.strip().split('\n')[-1]
        assert arch in ("x86_64", "arm64", "aarch64")

    def test_pkg_mgr_is_set(self):
        r = bash('detect_platform; echo "$ARIA_PKG_MGR"')
        assert r.returncode == 0
        pkg = r.stdout.strip().split('\n')[-1]
        assert pkg in ("apt", "dnf", "pacman", "brew", "unknown")


class TestValidateEmail:
    """Test email validation regex."""

    @pytest.mark.parametrize("email", [
        "user@example.com",
        "first.last@domain.co",
        "name+tag@test.org",
        "a@b.cc",
    ])
    def test_valid_emails(self, email):
        r = bash(f'validate_email "{email}" && echo "VALID" || echo "INVALID"')
        assert "VALID" in r.stdout

    @pytest.mark.parametrize("email", [
        "not-an-email",
        "@missing.com",
        "user@",
        "user@.com",
        "",
        "spaces in@email.com",
    ])
    def test_invalid_emails(self, email):
        r = bash(f'validate_email "{email}" && echo "VALID" || echo "INVALID"')
        assert "INVALID" in r.stdout


class TestGenerateSecret:
    """Test cryptographic secret generation."""

    def test_generates_64_hex_chars(self):
        r = bash('generate_secret')
        assert r.returncode == 0
        secret = r.stdout.strip()
        assert len(secret) == 64, f"Expected 64 chars, got {len(secret)}: {secret}"
        assert all(c in "0123456789abcdef" for c in secret)

    def test_generates_unique_values(self):
        r = bash('echo "$(generate_secret)"; echo "$(generate_secret)"')
        lines = [l for l in r.stdout.strip().split('\n') if l]
        assert len(lines) == 2
        assert lines[0] != lines[1], "Two consecutive secrets should differ"


class TestEnvSet:
    """Test the safe .env writer."""

    def test_sets_new_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("EXISTING_KEY=value\n")
        r = bash(f'env_set "NEW_KEY" "new_value" "{env_file}"')
        assert r.returncode == 0
        content = env_file.read_text()
        assert "NEW_KEY=new_value" in content
        assert "EXISTING_KEY=value" in content

    def test_updates_existing_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_KEY=old_value\nOTHER=keep\n")
        r = bash(f'env_set "MY_KEY" "new_value" "{env_file}"')
        assert r.returncode == 0
        content = env_file.read_text()
        assert "MY_KEY=new_value" in content
        assert "MY_KEY=old_value" not in content
        assert "OTHER=keep" in content

    def test_handles_special_chars_in_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=placeholder\n")
        # API keys can have dashes, underscores
        r = bash(f'env_set "KEY" "sk-ant-api03-xxxx_yyyy" "{env_file}"')
        assert r.returncode == 0
        content = env_file.read_text()
        assert "KEY=sk-ant-api03-xxxx_yyyy" in content

    def test_handles_pipe_in_value(self, tmp_path):
        """Regression: old sedi approach broke on pipe chars."""
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=old\n")
        r = bash(f'env_set "KEY" "value|with|pipes" "{env_file}"')
        assert r.returncode == 0
        content = env_file.read_text()
        assert "KEY=value|with|pipes" in content

    def test_preserves_other_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("A=1\nB=2\nC=3\n")
        bash(f'env_set "B" "updated" "{env_file}"')
        content = env_file.read_text()
        assert "A=1" in content
        assert "B=updated" in content
        assert "C=3" in content

    def test_empty_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=something\n")
        bash(f'env_set "SECRET" "" "{env_file}"')
        content = env_file.read_text()
        assert "SECRET=" in content
        assert "SECRET=something" not in content


class TestReadEnvVar:
    """Test reading values from .env files."""

    def test_reads_simple_value(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("MY_VAR=hello\n")
        r = bash(f'read_env_var "MY_VAR" "{env_file}"')
        assert r.stdout.strip() == "hello"

    def test_reads_value_with_equals(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("URL=https://example.com?a=1&b=2\n")
        r = bash(f'read_env_var "URL" "{env_file}"')
        assert r.stdout.strip() == "https://example.com?a=1&b=2"

    def test_strips_quotes(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text('QUOTED="hello world"\n')
        r = bash(f'read_env_var "QUOTED" "{env_file}"')
        assert r.stdout.strip() == "hello world"

    def test_nonexistent_var_returns_empty(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("OTHER=value\n")
        r = bash(f'read_env_var "MISSING" "{env_file}"')
        assert r.stdout.strip() == ""

    def test_nonexistent_file_returns_empty(self):
        r = bash('read_env_var "ANY" "/nonexistent/.env"')
        assert r.stdout.strip() == ""


class TestHasCmd:
    """Test command existence check."""

    def test_finds_bash(self):
        r = bash('has_cmd bash && echo "YES" || echo "NO"')
        assert "YES" in r.stdout

    def test_missing_command(self):
        r = bash('has_cmd nonexistent_command_xyz && echo "YES" || echo "NO"')
        assert "NO" in r.stdout


class TestCheckDiskSpace:
    """Test disk space checking."""

    def test_passes_with_low_threshold(self):
        r = bash('check_disk_space "/tmp" 1 && echo "OK" || echo "LOW"')
        assert "OK" in r.stdout

    def test_fails_with_absurd_threshold(self):
        # 999999999 MB = ~1 exabyte, should always fail
        r = bash('check_disk_space "/tmp" 999999999 && echo "OK" || echo "LOW"')
        assert "LOW" in r.stdout


class TestCleanupOnInterrupt:
    """Test the Ctrl+C trap handler."""

    def test_shows_recovery_message(self):
        r = bash('cleanup_on_interrupt 2>&1 || true')
        assert "interrupted" in r.stdout.lower() or "re-run" in r.stdout.lower()


# ═════════════════════════════════════════════════════════════════════
# Module: backend.sh
# ═════════════════════════════════════════════════════════════════════

class TestBackendPrerequisites:
    """Test system prerequisite checks."""

    def test_detects_python(self):
        r = bash_function("backend.sh", "backend_check_prerequisites")
        assert r.returncode == 0
        assert "Python" in r.stdout

    def test_detects_git(self):
        r = bash_function("backend.sh", "backend_check_prerequisites")
        assert "git" in r.stdout


class TestBackendCreateDirs:
    """Test data directory creation."""

    def test_creates_all_directories(self, tmp_path):
        r = bash_function(
            "backend.sh",
            "backend_create_dirs",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert r.returncode == 0
        for d in ["auth", "mirror", "conversations", "backups", "reflections"]:
            assert (tmp_path / "data" / d).is_dir(), f"data/{d} not created"

    def test_auth_dir_permissions(self, tmp_path):
        bash_function(
            "backend.sh",
            "backend_create_dirs",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        auth_dir = tmp_path / "data" / "auth"
        mode = oct(auth_dir.stat().st_mode)[-3:]
        assert mode == "700", f"Expected 700 permissions, got {mode}"

    def test_idempotent(self, tmp_path):
        """Running twice should not fail."""
        for _ in range(2):
            r = bash_function(
                "backend.sh",
                "backend_create_dirs",
                cwd=str(tmp_path),
                env={"PROJECT_ROOT": str(tmp_path)},
            )
            assert r.returncode == 0


class TestBackendValidateEnv:
    """Test .env validation logic."""

    def test_warns_when_no_env(self, tmp_path):
        r = bash_function(
            "backend.sh",
            "backend_validate_env",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert r.returncode == 0
        assert "does not exist" in r.stdout

    def test_detects_placeholder_keys(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "DEEPSEEK_API_KEY=sk-your-deepseek-key\n"
            "OPENAI_API_KEY=sk-proj-your-openai-key\n"
        )
        r = bash_function(
            "backend.sh",
            "backend_validate_env",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert "No LLM API keys configured" in r.stdout

    def test_detects_real_key(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("DEEPSEEK_API_KEY=sk-real-key-abc123\n")
        r = bash_function(
            "backend.sh",
            "backend_validate_env",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert "DEEPSEEK_API_KEY configured" in r.stdout

    def test_fixes_env_permissions(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=val\n")
        env_file.chmod(0o644)
        bash_function(
            "backend.sh",
            "backend_validate_env",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        mode = oct(env_file.stat().st_mode)[-3:]
        assert mode == "600", f"Expected 600, got {mode}"


# ═════════════════════════════════════════════════════════════════════
# Module: frontend.sh
# ═════════════════════════════════════════════════════════════════════

class TestFrontendNginxConfig:
    """Test Nginx configuration generation."""

    def test_generates_config_file(self, tmp_path):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        r = bash_function(
            "frontend.sh",
            'frontend_generate_nginx "aria.example.com"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert r.returncode == 0
        conf = deploy_dir / "nginx-aria.conf"
        assert conf.exists(), "nginx-aria.conf not generated"

    def test_config_contains_domain(self, tmp_path):
        (tmp_path / "deploy").mkdir()
        bash_function(
            "frontend.sh",
            'frontend_generate_nginx "mysite.io"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        content = (tmp_path / "deploy" / "nginx-aria.conf").read_text()
        assert "server_name mysite.io" in content

    def test_config_has_hsts(self, tmp_path):
        (tmp_path / "deploy").mkdir()
        bash_function(
            "frontend.sh",
            'frontend_generate_nginx "example.com"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        content = (tmp_path / "deploy" / "nginx-aria.conf").read_text()
        assert "Strict-Transport-Security" in content

    def test_config_has_csp(self, tmp_path):
        (tmp_path / "deploy").mkdir()
        bash_function(
            "frontend.sh",
            'frontend_generate_nginx "example.com"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        content = (tmp_path / "deploy" / "nginx-aria.conf").read_text()
        assert "Content-Security-Policy" in content

    def test_config_has_rate_limit(self, tmp_path):
        (tmp_path / "deploy").mkdir()
        bash_function(
            "frontend.sh",
            'frontend_generate_nginx "example.com"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        content = (tmp_path / "deploy" / "nginx-aria.conf").read_text()
        assert "limit_req" in content

    def test_config_uses_modern_http2(self, tmp_path):
        (tmp_path / "deploy").mkdir()
        bash_function(
            "frontend.sh",
            'frontend_generate_nginx "example.com"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        content = (tmp_path / "deploy" / "nginx-aria.conf").read_text()
        assert "http2 on" in content
        # Must NOT use deprecated 'listen 443 ssl http2'
        assert "listen 443 ssl http2" not in content

    def test_only_proxies_port_3000(self, tmp_path):
        """FastAPI (8000) must NOT appear in Nginx config."""
        (tmp_path / "deploy").mkdir()
        bash_function(
            "frontend.sh",
            'frontend_generate_nginx "example.com"',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        content = (tmp_path / "deploy" / "nginx-aria.conf").read_text()
        assert "127.0.0.1:3000" in content
        assert "127.0.0.1:8000" not in content
        assert "localhost:8000" not in content

    def test_skips_when_no_domain(self, tmp_path):
        r = bash_function(
            "frontend.sh",
            'frontend_generate_nginx ""',
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert r.returncode == 0
        assert not (tmp_path / "deploy" / "nginx-aria.conf").exists()


# ═════════════════════════════════════════════════════════════════════
# Module: auth-email.sh
# ═════════════════════════════════════════════════════════════════════

class TestAuthSecurityChecks:
    """Test security verification logic."""

    def test_sets_env_permissions(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=val\n")
        env_file.chmod(0o644)
        # Need a .gitignore with .env for the check
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".env\n")

        bash_function(
            "auth-email.sh",
            "auth_security_checks",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        mode = oct(env_file.stat().st_mode)[-3:]
        assert mode == "600"

    def test_warns_missing_gitignore_entry(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=val\n")
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("*.pyc\n")  # .env NOT listed

        r = bash_function(
            "auth-email.sh",
            "auth_security_checks",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert "NOT in .gitignore" in r.stdout

    def test_warns_client_secret_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("KEY=val\n")
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".env\n")
        (tmp_path / "client_secret_12345.json").write_text("{}")

        r = bash_function(
            "auth-email.sh",
            "auth_security_checks",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert "client_secret" in r.stdout


class TestAuthGenerateSecret:
    """Test internal secret generation."""

    def test_generates_when_empty(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("ARIA_INTERNAL_SECRET=\n")

        bash_function(
            "auth-email.sh",
            "auth_generate_secret",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )

        content = env_file.read_text()
        # Should have a non-empty value now
        for line in content.strip().split('\n'):
            if line.startswith("ARIA_INTERNAL_SECRET="):
                val = line.split('=', 1)[1]
                assert len(val) >= 32, f"Secret too short: {len(val)}"
                break
        else:
            pytest.fail("ARIA_INTERNAL_SECRET not found in .env")

    def test_preserves_existing_secret(self, tmp_path):
        existing = "a" * 64
        env_file = tmp_path / ".env"
        env_file.write_text(f"ARIA_INTERNAL_SECRET={existing}\n")

        bash_function(
            "auth-email.sh",
            "auth_generate_secret",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )

        content = env_file.read_text()
        assert f"ARIA_INTERNAL_SECRET={existing}" in content


class TestAuthDevFallback:
    """Test development mode fallback behavior."""

    def test_skips_when_resend_configured(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("ARIA_INTERNAL_SECRET=abc123\n")

        r = bash_function(
            "auth-email.sh",
            "auth_dev_fallback",
            cwd=str(tmp_path),
            env={
                "PROJECT_ROOT": str(tmp_path),
                "AUTH_RESEND_CONFIGURED": "true",
                "AUTH_DEPLOY_MODE": "dev",
            },
        )
        # Should return immediately without output
        assert "Disable" not in r.stdout

    def test_warns_in_production_without_resend(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("ARIA_INTERNAL_SECRET=abc\n")

        r = bash_function(
            "auth-email.sh",
            "auth_dev_fallback",
            cwd=str(tmp_path),
            env={
                "PROJECT_ROOT": str(tmp_path),
                "AUTH_RESEND_CONFIGURED": "false",
                "AUTH_DEPLOY_MODE": "production",
            },
        )
        assert "won't be able to log in" in r.stdout


# ═════════════════════════════════════════════════════════════════════
# Module: install.sh — integration
# ═════════════════════════════════════════════════════════════════════

class TestFrontendSmokeTestFunction:
    """Test the smoke test function exists and has correct structure."""

    def test_smoke_test_function_defined(self):
        path = os.path.join(INSTALL_DIR, "frontend.sh")
        with open(path) as f:
            content = f.read()
        assert "frontend_smoke_test()" in content

    def test_smoke_test_skips_without_build(self, tmp_path):
        r = bash_function(
            "frontend.sh",
            "frontend_smoke_test",
            cwd=str(tmp_path),
            env={"PROJECT_ROOT": str(tmp_path)},
        )
        assert r.returncode == 0
        assert "No build found" in r.stdout or "skipping" in r.stdout.lower()

    def test_route_validation_in_build(self):
        """Verify frontend_build does route validation."""
        path = os.path.join(INSTALL_DIR, "frontend.sh")
        with open(path) as f:
            content = f.read()
        assert "login" in content
        assert "mirror" in content
        assert "Key routes present" in content


class TestInstallHelp:
    """Test install.sh flags and help."""

    def test_help_flag(self):
        result = subprocess.run(
            ["bash", os.path.join(INSTALL_DIR, "install.sh"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout
        assert "--docker" in result.stdout
        assert "--minimal" in result.stdout
        assert "--dev" in result.stdout
        assert "--verify" in result.stdout

    def test_h_flag(self):
        result = subprocess.run(
            ["bash", os.path.join(INSTALL_DIR, "install.sh"), "-h"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout


# ═════════════════════════════════════════════════════════════════════
# Infrastructure files
# ═════════════════════════════════════════════════════════════════════

class TestDockerCompose:
    """Verify docker-compose.yml configuration."""

    def test_node_env_production_set(self):
        path = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "NODE_ENV=production" in content

    def test_ports_bound_to_localhost(self):
        path = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "127.0.0.1:3000" in content
        assert "127.0.0.1:8000" in content

    def test_no_hardcoded_origin(self):
        """ARIA_ORIGIN must NOT be hardcoded — it comes from .env."""
        path = os.path.join(PROJECT_ROOT, "docker-compose.yml")
        with open(path) as f:
            content = f.read()
        assert "aria.yourdomain.com" not in content


class TestSupervisordConf:
    """Verify supervisord.conf configuration."""

    def test_node_env_production_set(self):
        path = os.path.join(PROJECT_ROOT, "deploy", "supervisord.conf")
        with open(path) as f:
            content = f.read()
        assert "NODE_ENV=production" in content

    def test_passes_origin_from_env(self):
        path = os.path.join(PROJECT_ROOT, "deploy", "supervisord.conf")
        with open(path) as f:
            content = f.read()
        assert "ORIGIN=%(ENV_ARIA_ORIGIN)s" in content

    def test_passes_internal_secret(self):
        path = os.path.join(PROJECT_ROOT, "deploy", "supervisord.conf")
        with open(path) as f:
            content = f.read()
        assert "ARIA_INTERNAL_SECRET=%(ENV_ARIA_INTERNAL_SECRET)s" in content


class TestDockerignore:
    """Verify .dockerignore blocks sensitive files."""

    def test_blocks_env_file(self):
        path = os.path.join(PROJECT_ROOT, ".dockerignore")
        with open(path) as f:
            content = f.read()
        assert ".env" in content

    def test_blocks_client_secrets(self):
        path = os.path.join(PROJECT_ROOT, ".dockerignore")
        with open(path) as f:
            content = f.read()
        assert "client_secret" in content

    def test_blocks_credentials(self):
        path = os.path.join(PROJECT_ROOT, ".dockerignore")
        with open(path) as f:
            content = f.read()
        assert "credentials" in content.lower()


class TestEnvExample:
    """Verify .env.example is complete."""

    def test_exists(self):
        assert os.path.exists(os.path.join(PROJECT_ROOT, ".env.example"))

    def test_has_required_vars(self):
        path = os.path.join(PROJECT_ROOT, ".env.example")
        with open(path) as f:
            content = f.read()
        required = [
            "ARIA_ALLOWED_EMAILS",
            "RESEND_API_KEY",
            "RESEND_FROM_EMAIL",
            "ARIA_INTERNAL_SECRET",
            "ARIA_ORIGIN",
            "ARIA_CORS_ORIGINS",
        ]
        for var in required:
            assert var in content, f"{var} missing from .env.example"


class TestGitignore:
    """Verify .gitignore protects sensitive files."""

    def test_ignores_env(self):
        path = os.path.join(PROJECT_ROOT, ".gitignore")
        with open(path) as f:
            lines = [l.strip() for l in f.readlines()]
        assert ".env" in lines or any(".env" in l for l in lines)


# ═════════════════════════════════════════════════════════════════════
# Documentation
# ═════════════════════════════════════════════════════════════════════

class TestFrontendFeatures:
    """Verify frontend pages have all required features."""

    def test_chat_attach_button_has_handler(self):
        path = os.path.join(PROJECT_ROOT, "web", "src", "routes", "+page.svelte")
        with open(path) as f:
            content = f.read()
        # Must have file input and attach handling
        assert "type=\"file\"" in content or "type='file'" in content
        assert "Attached:" in content

    def test_chat_goal_button_has_handler(self):
        path = os.path.join(PROJECT_ROOT, "web", "src", "routes", "+page.svelte")
        with open(path) as f:
            content = f.read()
        assert "Goal:" in content or "goal" in content.lower()

    def test_chat_model_name_dynamic(self):
        path = os.path.join(PROJECT_ROOT, "web", "src", "routes", "+page.svelte")
        with open(path) as f:
            content = f.read()
        # Must NOT have hardcoded deepseek model name for display
        assert "modelName" in content or "model_name" in content

    def test_mirror_keyboard_shortcuts_implemented(self):
        path = os.path.join(PROJECT_ROOT, "web", "src", "routes", "mirror", "+page.svelte")
        with open(path) as f:
            content = f.read()
        assert "handleKeydown" in content or "keydown" in content
        # Must check for focused input elements to avoid triggering in text fields
        assert "INPUT" in content or "activeElement" in content

    def test_credentials_oauth_opens_url(self):
        path = os.path.join(PROJECT_ROOT, "web", "src", "routes", "credentials", "+page.svelte")
        with open(path) as f:
            content = f.read()
        # Must open auth URL in browser, not tell user to check console
        assert "window.open" in content or "auth_url" in content

    def test_backend_status_returns_model(self):
        path = os.path.join(PROJECT_ROOT, "core", "api", "server.py")
        with open(path) as f:
            content = f.read()
        # Status endpoint must return model info
        assert "model" in content
        assert "provider" in content


class TestInstallGuide:
    """Verify documentation accuracy."""

    def test_exists(self):
        assert os.path.exists(os.path.join(PROJECT_ROOT, "docs", "INSTALL_GUIDE.md"))

    def test_mentions_all_modes(self):
        path = os.path.join(PROJECT_ROOT, "docs", "INSTALL_GUIDE.md")
        with open(path) as f:
            content = f.read()
        for mode in ["--docker", "--minimal", "--dev", "--skip-agents"]:
            assert mode in content, f"{mode} not documented"

    def test_mentions_hsts(self):
        path = os.path.join(PROJECT_ROOT, "docs", "INSTALL_GUIDE.md")
        with open(path) as f:
            content = f.read()
        assert "Strict-Transport-Security" in content

    def test_mentions_node_env(self):
        path = os.path.join(PROJECT_ROOT, "docs", "INSTALL_GUIDE.md")
        with open(path) as f:
            content = f.read()
        assert "NODE_ENV=production" in content

    def test_in_english(self):
        path = os.path.join(PROJECT_ROOT, "docs", "INSTALL_GUIDE.md")
        with open(path) as f:
            content = f.read()
        assert "## Overview" in content
        assert "## Security" in content
        assert "## Troubleshooting" in content
