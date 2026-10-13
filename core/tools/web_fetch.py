"""
ARIA - Web Fetch Tool (Hardened + JS Rendering)
=================================================

Fetches and extracts content from URLs.
Features: CSS selectors, SSRF protection, custom headers,
          Playwright JS rendering (auto-detect or explicit).

Rendering strategy (inspired by OpenClaw):
1. Fast fetch with requests (no JS)
2. If content looks empty/JS-dependent, auto-retry with Playwright
3. User can force JS rendering with render_js=True
"""

import hashlib
import ipaddress
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.web_fetch")

# Simple TTL cache
_cache: Dict[str, Dict[str, Any]] = {}
DEFAULT_CACHE_TTL = 900  # 15 minutes

# Private/reserved IP ranges (SSRF protection)
_PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Signals that a page needs JS rendering
_JS_REQUIRED_SIGNALS = [
    "noscript",
    "__NEXT_DATA__",
    "window.__remixContext",
    "react-root",
    "app-root",
    "__nuxt",
    "cf-browser-verification",
    "enable JavaScript",
    "requires JavaScript",
    "javascript is disabled",
    "please turn on javascript",
]


def _is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private IP."""
    import socket
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(hostname))
        return any(ip in net for net in _PRIVATE_NETS)
    except (socket.gaierror, ValueError):
        return False


def _looks_js_dependent(html: str) -> bool:
    """Heuristic: does this HTML look like it needs JS to render content?"""
    if not html or len(html.strip()) < 200:
        return True

    html_lower = html.lower()

    # Check for JS framework signals
    signal_count = sum(1 for sig in _JS_REQUIRED_SIGNALS if sig.lower() in html_lower)
    if signal_count >= 2:
        return True

    # Very little visible text relative to HTML size (lots of scripts, no content)
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # If extracted text is tiny compared to HTML, probably JS-rendered
    if len(html) > 5000 and len(text) < 200:
        return True

    return False


class WebFetchTool(ToolBase):
    """Fetch and extract readable content from a URL."""

    name = "web_fetch"
    description = (
        "Fetch a webpage and extract its readable content. "
        "Returns the page title and text content. "
        "Supports CSS selectors to extract specific sections. "
        "Can render JavaScript-heavy pages using a headless browser (Playwright). "
        "Auto-detects when JS rendering is needed, or set render_js=true to force it."
    )
    parameters = [
        ToolParam(
            name="url",
            type="string",
            description="The URL to fetch (must start with http:// or https://)",
            required=True,
        ),
        ToolParam(
            name="max_chars",
            type="integer",
            description="Maximum characters to return (default: 50000)",
            required=False,
            default=50000,
        ),
        ToolParam(
            name="selector",
            type="string",
            description="CSS selector to extract specific content (e.g. 'article', 'div.content', '#main')",
            required=False,
        ),
        ToolParam(
            name="render_js",
            type="boolean",
            description="Force JavaScript rendering with headless browser. 'auto' detects automatically (default: false)",
            required=False,
            default=False,
        ),
        ToolParam(
            name="wait_for",
            type="string",
            description="CSS selector to wait for before extracting (only with JS rendering). E.g. 'div.content'",
            required=False,
        ),
        ToolParam(
            name="user_agent",
            type="string",
            description="Custom User-Agent header",
            required=False,
        ),
        ToolParam(
            name="headers",
            type="string",
            description="Custom headers as 'Key: Value' lines separated by \\n",
            required=False,
        ),
        ToolParam(
            name="timeout",
            type="integer",
            description="Request timeout in seconds (default: 30, max: 60)",
            required=False,
            default=30,
        ),
    ]

    def _execute(self, **kwargs) -> ToolResult:
        url = kwargs["url"]
        max_chars = kwargs.get("max_chars", 50000)
        selector = kwargs.get("selector")
        render_js = kwargs.get("render_js", False)
        wait_for = kwargs.get("wait_for")
        user_agent = kwargs.get("user_agent", DEFAULT_USER_AGENT)
        headers_str = kwargs.get("headers", "")
        timeout = min(kwargs.get("timeout", 30), 60)

        # Validate URL
        if not url.startswith(("http://", "https://")):
            return ToolResult(success=False, error="URL must start with http:// or https://")

        # SSRF protection
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "") or _is_private_ip(hostname):
            return ToolResult(success=False, error=f"Blocked: cannot fetch private/local addresses ({hostname})")

        # Check cache (selector + render_js aware)
        cache_key = _make_cache_key(url, max_chars, selector, render_js)
        cached = _get_cached(cache_key)
        if cached:
            logger.debug(f"Cache hit for {url}")
            cached["metadata"]["cached"] = True
            return ToolResult(**cached)

        # Parse custom headers
        req_headers = {"User-Agent": user_agent}
        if headers_str:
            for line in headers_str.split("\\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    req_headers[k.strip()] = v.strip()

        used_js = False

        if render_js:
            # User explicitly wants JS rendering
            content, status_code, error = _fetch_with_playwright(url, timeout, wait_for, user_agent)
            used_js = True
        else:
            # Try fast fetch first
            content, status_code, error = self._do_fetch(url, req_headers, timeout)

            # Auto-detect: if content looks JS-dependent, retry with Playwright
            if not error and content and _looks_js_dependent(content):
                logger.info(f"Page looks JS-dependent, retrying with Playwright: {url}")
                js_content, js_status, js_error = _fetch_with_playwright(url, timeout, wait_for, user_agent)
                if not js_error and js_content:
                    content = js_content
                    status_code = js_status
                    used_js = True

        if error:
            return ToolResult(
                success=False,
                error=error,
                data={"url": url, "status_code": status_code},
            )

        title = _extract_title(content)

        # Apply CSS selector if provided
        if selector:
            selected = _apply_selector(content, selector)
            if selected:
                content = selected
            else:
                content = _extract_readable(content) or content
        else:
            readable = _extract_readable(content)
            if readable:
                content = readable

        # Truncate
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars] + "\n\n[... truncated]"

        # --- Prompt injection sanitization ---
        sanitize_report = None
        try:
            from ..curiosity import ContentSanitizer
            sanitizer = ContentSanitizer()
            content, sanitize_report = sanitizer.sanitize(content, source_url=url)
            content = sanitizer.wrap_as_external_data(content, source_url=url)
        except Exception as e:
            logger.debug(f"Sanitizer unavailable: {e}")

        output_lines = []
        if title:
            output_lines.append(f"Title: {title}")
        output_lines.append(f"URL: {url}")
        output_lines.append(f"Status: {status_code}")
        if used_js:
            output_lines.append("Rendered: JavaScript (Playwright)")
        if selector:
            output_lines.append(f"Selector: {selector}")
        if sanitize_report and sanitize_report.get("injections_found", 0) > 0:
            output_lines.append(f"⚠ Sanitized: {sanitize_report['injections_found']} potential prompt injection(s) neutralized")
        output_lines.append("")
        output_lines.append(content)

        result_data = {
            "success": True,
            "output": "\n".join(output_lines),
            "data": {
                "url": url,
                "title": title,
                "status_code": status_code,
                "length": len(content),
                "truncated": truncated,
                "js_rendered": used_js,
            },
            "metadata": {"cached": False},
        }

        _set_cached(cache_key, result_data)

        return ToolResult(**result_data)

    def _do_fetch(self, url, headers, timeout):
        """Fetch URL with requests. Returns (content, status_code, error)."""
        try:
            import requests as req_lib
            resp = req_lib.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.text, resp.status_code, None
        except ImportError:
            return None, 0, "requests library not available (pip install requests)"
        except Exception as e:
            status = getattr(e, "response", None)
            code = status.status_code if status is not None else 0
            return None, code, str(e)


# =============================================================================
# Playwright JS Rendering
# =============================================================================

def _ensure_playwright_libs():
    """Auto-configure LD_LIBRARY_PATH for Playwright's Chromium dependencies.

    On systems where libnspr4/libnss3/libasound are not installed globally
    (e.g. WSL without sudo), we check common extraction paths and add them.
    """
    import ctypes.util

    # Already available system-wide?
    if ctypes.util.find_library("nspr4"):
        return

    # Check known extraction paths
    candidate_dirs = [
        "/tmp/playwright_deps/extracted/usr/lib/x86_64-linux-gnu",
        os.path.join(os.path.expanduser("~"), ".playwright-libs"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)))), "playwright_libs"),
    ]

    for d in candidate_dirs:
        nspr_path = os.path.join(d, "libnspr4.so")
        if os.path.exists(nspr_path):
            current = os.environ.get("LD_LIBRARY_PATH", "")
            if d not in current:
                os.environ["LD_LIBRARY_PATH"] = f"{d}:{current}" if current else d
                logger.debug(f"Added Playwright libs: {d}")
            return

    logger.debug("Playwright system libs not found — Chromium may fail to launch")


def _fetch_with_playwright(
    url: str,
    timeout: int = 30,
    wait_for: str = None,
    user_agent: str = None,
) -> Tuple[Optional[str], int, Optional[str]]:
    """
    Fetch a URL using Playwright headless browser for JS rendering.
    Returns (html_content, status_code, error).

    Inspired by OpenClaw's browser tool approach:
    - Launch headless Chromium
    - Navigate to URL
    - Wait for network idle or specific selector
    - Return fully rendered HTML
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.debug("Playwright not installed — JS rendering unavailable")
        return None, 0, None  # Return None error so caller can use static content

    _ensure_playwright_libs()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=user_agent or DEFAULT_USER_AGENT,
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
            )
            page = context.new_page()

            # Block heavy resources to speed up rendering
            page.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico,woff,woff2,ttf,eot}",
                       lambda route: route.abort())
            page.route("**/*", lambda route: (
                route.abort() if route.request.resource_type in ("media", "font", "image")
                else route.continue_()
            ))

            # Navigate
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
            status_code = response.status if response else 200

            # Wait for content to render
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=10000)
                except Exception:
                    logger.debug(f"wait_for selector '{wait_for}' timed out, continuing anyway")
            else:
                # Wait for network to settle
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass  # Some pages never reach network idle

            html = page.content()

            browser.close()

            return html, status_code, None

    except Exception as e:
        logger.warning(f"Playwright fetch failed: {e}")
        return None, 0, None  # Don't fail, let caller use static content


# =============================================================================
# Cache Helpers
# =============================================================================

def _make_cache_key(url: str, max_chars: int, selector: str = None, render_js: bool = False) -> str:
    raw = f"{url}:{max_chars}:{selector or ''}:{render_js}"
    return hashlib.md5(raw.encode()).hexdigest()


def _get_cached(key: str) -> Optional[dict]:
    if key in _cache:
        entry = _cache[key]
        if time.time() - entry["ts"] < DEFAULT_CACHE_TTL:
            return entry["data"]
        del _cache[key]
    return None


def _set_cached(key: str, data: dict):
    _cache[key] = {"ts": time.time(), "data": data}
    if len(_cache) > 100:
        oldest = min(_cache, key=lambda k: _cache[k]["ts"])
        del _cache[oldest]


# =============================================================================
# Content Extraction Helpers
# =============================================================================

def _extract_title(html: str) -> str:
    """Extract <title> from HTML."""
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        return title[:200]
    return ""


def _apply_selector(html: str, selector: str) -> str:
    """Extract content matching a CSS selector using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        elements = soup.select(selector)
        if elements:
            texts = [el.get_text(separator=" ", strip=True) for el in elements]
            return "\n\n".join(t for t in texts if t)
    except ImportError:
        logger.debug("BeautifulSoup not available for CSS selector")
    except Exception as e:
        logger.debug(f"Selector failed: {e}")
    return ""


def _extract_readable(html: str) -> str:
    """Try to extract readable text from HTML."""
    # Try readability
    try:
        from readability import Document
        doc = Document(html)
        summary = doc.summary()
        text = re.sub(r"<[^>]+>", "", summary)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 100:
            return text
    except ImportError:
        pass
    except Exception:
        pass

    # Fallback: strip HTML tags
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    return text if len(text) > 50 else ""
