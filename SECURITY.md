# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in ARIA, please report it responsibly:

1. **Do not** open a public issue
2. Email: wwilamo1@protonmail.com
3. Include: description, steps to reproduce, potential impact

We will respond within 72 hours and work with you on a fix before public disclosure.

## Security Model

ARIA has three runtime security modes (configured at startup):

| Mode | Description |
|------|-------------|
| **Free** | No restrictions. Use only in isolated/sandbox environments. |
| **Protected** | Blocks known dangerous patterns. Recommended for normal use. |
| **Paranoid** | Whitelist-only commands. Maximum restriction. |

## What We Protect Against

- Shell injection (no `shell=True`, argument sanitization)
- SSRF (private IP blocking in web fetch)
- Prompt injection (74 detection patterns for external data)
- Path traversal (file and compress tools)
- Code injection (AST-validated calculator)
- SQL injection (mutation prevention on query actions)

## Dependencies

We pin minimum versions in `requirements.txt`. Run `pip audit` periodically to check for known vulnerabilities in dependencies.
