"""
ARIA - Browser Tool
====================

Interactive browser control with persistent sessions and accessibility
tree snapshots. Inspired by OpenClaw's browser system.

Key innovation: Instead of screenshots, the LLM receives a text-based
accessibility tree with numeric refs. The agent reads refs and acts:
    snapshot → "[1] button 'Search'  [2] textbox 'Query'" → click 2 → type 2 "AI"

Architecture:
    BrowserTool → Playwright (sync_api) → Chromium headless
    Persistent session: browser stays open across actions.
    Refs regenerated after every mutation (click, type, navigate).
"""

import atexit
import base64
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.browser")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1280, "height": 720}
DEFAULT_TIMEOUT = 30000  # 30s

# Roles considered interactive (get refs in snapshots)
INTERACTIVE_ROLES = {
    "link", "button", "textbox", "checkbox", "radio", "combobox",
    "menuitem", "tab", "switch", "slider", "spinbutton", "searchbox",
    "option", "menuitemcheckbox", "menuitemradio", "treeitem",
}


# JavaScript injected into every page in stealth mode to evade bot detection
STEALTH_JS = """
// Remove webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// Override plugins to look like a real browser
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5].map(() => ({
        name: 'Chrome PDF Plugin',
        filename: 'internal-pdf-viewer',
        description: 'Portable Document Format',
    })),
});

// Override languages
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// Prevent chrome.runtime detection
window.chrome = { runtime: {}, csi: () => {}, loadTimes: () => {} };

// Override permissions query
const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : originalQuery(params);
}
"""


class BrowserTool(ToolBase):
    """Interactive browser with accessibility snapshots and persistent session."""

    name = "browser"
    description = (
        "Interactive web browser with persistent session. "
        "Actions: navigate (go to URL), snapshot (get page structure with refs), "
        "click/type/select/hover (interact using ref numbers from snapshot), "
        "screenshot (visual capture), scroll, back, forward, refresh, "
        "tab_new, tab_list, tab_switch, tab_close, "
        "cookies, evaluate (run JS), wait, close. "
        "WORKFLOW: navigate → snapshot → read refs → click/type → snapshot → repeat."
    )
    parameters = [
        ToolParam(
            name="action",
            type="string",
            description=(
                "Action to perform: navigate, snapshot, click, type, hover, "
                "select, scroll, back, forward, refresh, screenshot, "
                "tab_new, tab_list, tab_switch, tab_close, "
                "cookies, evaluate, wait, close"
            ),
            required=True,
            enum=[
                "navigate", "snapshot", "click", "type", "hover", "select",
                "scroll", "back", "forward", "refresh", "screenshot",
                "tab_new", "tab_list", "tab_switch", "tab_close",
                "cookies", "evaluate", "wait", "close",
            ],
        ),
        ToolParam(
            name="url",
            type="string",
            description="URL for navigate/tab_new",
            required=False,
        ),
        ToolParam(
            name="ref",
            type="integer",
            description="Numeric ref from snapshot for click/type/hover/select",
            required=False,
        ),
        ToolParam(
            name="text",
            type="string",
            description="Text to type, option to select, or JS code to evaluate",
            required=False,
        ),
        ToolParam(
            name="direction",
            type="string",
            description="Scroll direction: up or down (default: down)",
            required=False,
            enum=["up", "down"],
            default="down",
        ),
        ToolParam(
            name="tab_id",
            type="integer",
            description="Tab ID for tab_switch/tab_close",
            required=False,
        ),
        ToolParam(
            name="wait_for",
            type="string",
            description="CSS selector or 'networkidle' for wait action",
            required=False,
        ),
        ToolParam(
            name="timeout",
            type="integer",
            description="Timeout in seconds (default: 30)",
            required=False,
            default=30,
        ),
        ToolParam(
            name="frame",
            type="string",
            description="CSS selector of iframe to scope snapshot/actions into (e.g. 'iframe#email', 'iframe[title=\"Payment\"]')",
            required=False,
        ),
        ToolParam(
            name="stealth",
            type="boolean",
            description="Launch in stealth mode to avoid bot detection (default: true)",
            required=False,
            default=True,
        ),
        ToolParam(
            name="connect_url",
            type="string",
            description="CDP WebSocket URL to attach to existing browser (e.g. ws://localhost:9222). Use for pre-authenticated sessions.",
            required=False,
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._pages: Dict[int, Any] = {}  # tab_id → Page
        self._active_tab: int = 0
        self._next_tab_id: int = 0
        self._ref_map: Dict[int, Dict[str, Any]] = {}
        self._next_ref: int = 1
        self._initialized = False
        self._active_frame: Optional[str] = None  # CSS selector for active iframe scope
        self._stealth: bool = True

    # =========================================================================
    # Session lifecycle
    # =========================================================================

    def _ensure_browser(self, connect_url: str = None, stealth: bool = True):
        """Lazy-init persistent Playwright browser session.

        Args:
            connect_url: CDP WebSocket URL to attach to existing browser.
                         If provided, connects instead of launching new browser.
            stealth: Apply anti-detection patches to avoid bot fingerprinting.
        """
        if self._initialized and self._browser and self._browser.is_connected():
            return

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )

        self._ensure_playwright_libs()
        self._stealth = stealth
        self._playwright = sync_playwright().start()

        if connect_url:
            # Attach to existing browser via CDP
            self._browser = self._playwright.chromium.connect_over_cdp(connect_url)
            contexts = self._browser.contexts
            if contexts:
                self._context = contexts[0]
                pages = self._context.pages
                if pages:
                    self._page = pages[0]
                    self._pages[0] = self._page
                else:
                    self._page = self._context.new_page()
                    self._pages[0] = self._page
            else:
                self._context = self._browser.new_context()
                self._page = self._context.new_page()
                self._pages[0] = self._page
            logger.info(f"Attached to existing browser via CDP: {connect_url}")
        else:
            # Launch new browser
            launch_args = ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"]

            if stealth:
                # Stealth args: avoid common bot detection signals
                launch_args.extend([
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                    "--window-size=1280,720",
                ])

            self._browser = self._playwright.chromium.launch(
                headless=True,
                args=launch_args,
            )
            self._context = self._browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport=DEFAULT_VIEWPORT,
                java_script_enabled=True,
            )

            if stealth:
                # Inject stealth scripts into every page
                self._context.add_init_script(STEALTH_JS)

            self._page = self._context.new_page()
            self._pages[0] = self._page

        self._active_tab = 0
        self._next_tab_id = 1
        self._initialized = True

        atexit.register(self._cleanup)
        logger.info("Browser session started (Chromium headless)")

    def _cleanup(self):
        """Close browser and release resources."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None
        self._pages = {}
        self._playwright = None
        self._initialized = False

    def _ensure_playwright_libs(self):
        """Auto-configure LD_LIBRARY_PATH for Playwright's Chromium deps."""
        import ctypes.util
        if ctypes.util.find_library("nspr4"):
            return

        candidate_dirs = [
            "/tmp/playwright_deps/extracted/usr/lib/x86_64-linux-gnu",
            os.path.join(os.path.expanduser("~"), ".playwright-libs"),
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)))),
                "playwright_libs",
            ),
        ]

        for d in candidate_dirs:
            if os.path.exists(os.path.join(d, "libnspr4.so")):
                current = os.environ.get("LD_LIBRARY_PATH", "")
                if d not in current:
                    os.environ["LD_LIBRARY_PATH"] = f"{d}:{current}" if current else d
                return

    # =========================================================================
    # Execute dispatch
    # =========================================================================

    def _execute(self, **kwargs) -> ToolResult:
        action = kwargs["action"]

        if action == "close":
            return self._action_close(kwargs)

        # Track frame scope changes
        frame = kwargs.get("frame")
        if frame is not None:
            self._active_frame = frame if frame else None

        try:
            self._ensure_browser(
                connect_url=kwargs.get("connect_url"),
                stealth=kwargs.get("stealth", True),
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Browser init failed: {e}")

        dispatch = {
            "navigate": self._action_navigate,
            "snapshot": self._action_snapshot,
            "click": self._action_click,
            "type": self._action_type,
            "hover": self._action_hover,
            "select": self._action_select,
            "scroll": self._action_scroll,
            "back": self._action_back,
            "forward": self._action_forward,
            "refresh": self._action_refresh,
            "screenshot": self._action_screenshot,
            "tab_new": self._action_tab_new,
            "tab_list": self._action_tab_list,
            "tab_switch": self._action_tab_switch,
            "tab_close": self._action_tab_close,
            "cookies": self._action_cookies,
            "evaluate": self._action_evaluate,
            "wait": self._action_wait,
        }

        handler = dispatch.get(action)
        if not handler:
            return ToolResult(success=False, error=f"Unknown action: {action}")

        try:
            return handler(kwargs)
        except Exception as e:
            logger.error(f"Browser {action} failed: {e}")
            return ToolResult(success=False, error=f"{action} failed: {e}")

    # =========================================================================
    # Accessibility tree snapshot
    # =========================================================================

    def _get_frame_locator(self):
        """Get the active frame locator (for iframe-scoped actions).

        Returns (frame_locator, frame_name) or (None, "main") if no frame scope.
        """
        if not self._active_frame:
            return None, "main"
        try:
            fl = self._page.frame_locator(self._active_frame)
            return fl, self._active_frame
        except Exception:
            return None, "main"

    def _get_cdp(self):
        """Get or create a CDP session for the active page."""
        try:
            return self._context.new_cdp_session(self._page)
        except Exception:
            return None

    def _build_snapshot(self, include_iframes: bool = True) -> str:
        """Build accessibility tree with numeric refs using CDP.

        Uses Chrome DevTools Protocol Accessibility.getFullAXTree for a
        complete tree with backendDOMNodeId for element resolution.

        Returns formatted text like:
            heading "Welcome to Example"
            [1] textbox "Search" value=""
            [2] button "Go"
            list "Results"
              [3] link "First result"
              [4] link "Second result"
        """
        self._ref_map.clear()
        self._next_ref = 1

        cdp = self._get_cdp()
        if not cdp:
            return "[CDP session unavailable]"

        try:
            tree = cdp.send("Accessibility.getFullAXTree")
            nodes = tree.get("nodes", [])
        except Exception as e:
            return f"[Accessibility tree unavailable: {e}]"

        if not nodes:
            return "[Empty page]"

        # Build parent→children map
        children_map: Dict[str, list] = {}
        node_map: Dict[str, dict] = {}
        root_id = None

        for n in nodes:
            nid = n.get("nodeId", "")
            node_map[nid] = n
            if not root_id:
                root_id = nid
            pid = n.get("parentId")
            if pid:
                children_map.setdefault(pid, []).append(nid)

        lines = []
        if root_id:
            self._walk_cdp_tree(root_id, node_map, children_map, lines, depth=0)

        try:
            cdp.detach()
        except Exception:
            pass

        # Discover iframes and optionally traverse them
        if include_iframes:
            iframe_info = self._discover_iframes()
            if iframe_info:
                lines.append("")
                lines.append(f"--- iframes ({len(iframe_info)}) ---")
                for fi in iframe_info:
                    lines.append(f"  {fi['selector']}  src={fi['src'][:80]}")
                lines.append("Tip: use frame='<selector>' to scope actions into an iframe")

        # If frame-scoped, also show the frame's snapshot
        if self._active_frame:
            frame_snap = self._build_frame_snapshot(self._active_frame)
            if frame_snap:
                lines.append("")
                lines.append(f"--- active frame: {self._active_frame} ---")
                lines.append(frame_snap)

        return "\n".join(lines) if lines else "[Empty page]"

    def _discover_iframes(self) -> List[Dict[str, str]]:
        """List all visible iframes on the page with their selectors and src."""
        try:
            return self._page.evaluate("""() => {
                const iframes = Array.from(document.querySelectorAll('iframe'));
                return iframes.map((f, i) => ({
                    selector: f.id ? `iframe#${f.id}` :
                              f.name ? `iframe[name="${f.name}"]` :
                              f.title ? `iframe[title="${f.title}"]` :
                              `iframe:nth-of-type(${i + 1})`,
                    src: f.src || '',
                    id: f.id || '',
                    name: f.name || '',
                    title: f.title || '',
                    visible: f.offsetWidth > 0 && f.offsetHeight > 0,
                })).filter(f => f.visible || f.src);
            }""")
        except Exception:
            return []

    def _build_frame_snapshot(self, frame_selector: str) -> str:
        """Build an accessibility snapshot for content inside a specific iframe.

        Uses Playwright's frame_locator to access the iframe, then CDP on the
        frame's content to get the accessibility tree.
        """
        try:
            # Get the frame object via page.frames
            frames = self._page.frames
            target_frame = None

            for frame in frames:
                if frame == self._page.main_frame:
                    continue
                # Match by URL or name
                frame_url = frame.url
                frame_name = frame.name

                # Try to match the selector to this frame
                try:
                    el = self._page.query_selector(frame_selector)
                    if el:
                        content_frame = el.content_frame()
                        if content_frame:
                            target_frame = content_frame
                            break
                except Exception:
                    continue

            if not target_frame:
                return f"[Frame not found: {frame_selector}]"

            # Use locator-based approach within the frame
            # Build a simple text representation of interactive elements
            inner_lines = []
            try:
                inner_html = target_frame.evaluate("""() => {
                    const els = document.querySelectorAll(
                        'input, button, a, select, textarea, [role="button"], [role="link"], [role="textbox"], [role="checkbox"], [role="radio"], [contenteditable="true"]'
                    );
                    return Array.from(els).map((el, i) => {
                        const tag = el.tagName.toLowerCase();
                        const type = el.type || '';
                        const role = el.getAttribute('role') || tag;
                        const name = el.getAttribute('aria-label') || el.placeholder || el.textContent?.trim()?.slice(0, 60) || el.name || '';
                        const value = el.value || '';
                        const visible = el.offsetWidth > 0 && el.offsetHeight > 0;
                        return { tag, type, role, name, value, visible };
                    }).filter(e => e.visible);
                }""")
            except Exception as e:
                return f"[Cannot access frame content: {e}]"

            if not inner_html:
                return "[Frame has no interactive elements]"

            for i, el in enumerate(inner_html):
                ref = self._next_ref
                self._next_ref += 1

                role = el.get("role", el.get("tag", ""))
                name = el.get("name", "")
                value = el.get("value", "")

                # Normalize role for locator resolution
                role_map = {
                    "input": "textbox", "select": "combobox",
                    "textarea": "textbox", "a": "link",
                }
                resolved_role = role_map.get(role, role)
                if el.get("type") == "checkbox":
                    resolved_role = "checkbox"
                elif el.get("type") == "radio":
                    resolved_role = "radio"
                elif el.get("type") == "submit" or el.get("type") == "button":
                    resolved_role = "button"

                self._ref_map[ref] = {
                    "role": resolved_role,
                    "name": name,
                    "value": value,
                    "backendDOMNodeId": None,
                    "in_frame": frame_selector,
                }

                parts = [f"  [{ref}] {resolved_role}"]
                if name:
                    parts.append(f'"{name[:80]}"')
                if value:
                    parts.append(f'value="{value[:50]}"')
                inner_lines.append(" ".join(parts))

            return "\n".join(inner_lines) if inner_lines else "[Frame empty]"

        except Exception as e:
            return f"[Frame snapshot error: {e}]"

    def _walk_cdp_tree(self, node_id: str, node_map: dict, children_map: dict,
                       lines: list, depth: int):
        """Recursively walk CDP accessibility tree, assigning refs."""
        node = node_map.get(node_id, {})

        if node.get("ignored", False):
            for child_id in children_map.get(node_id, []):
                self._walk_cdp_tree(child_id, node_map, children_map, lines, depth)
            return

        role = node.get("role", {}).get("value", "")
        name = node.get("name", {}).get("value", "")
        value = ""

        # Extract value from properties
        for prop in node.get("properties", []):
            if prop.get("name") == "value":
                value = prop.get("value", {}).get("value", "")

        # Skip noise nodes
        if role in ("none", "generic", "LineBreak", "InlineTextBox", "StaticText",
                     "RootWebArea", "ignored") and not name:
            for child_id in children_map.get(node_id, []):
                self._walk_cdp_tree(child_id, node_map, children_map, lines, depth)
            return

        # Skip StaticText nodes (redundant with parent name)
        if role == "StaticText":
            return

        indent = "  " * min(depth, 8)  # Cap indent
        is_interactive = role.lower() in INTERACTIVE_ROLES
        backend_id = node.get("backendDOMNodeId")

        if is_interactive and name:
            ref = self._next_ref
            self._next_ref += 1

            self._ref_map[ref] = {
                "role": role,
                "name": name,
                "value": value,
                "backendDOMNodeId": backend_id,
            }

            parts = [f"{indent}[{ref}] {role}"]
            if name:
                parts.append(f'"{name[:80]}"')
            if value:
                parts.append(f'value="{value[:50]}"')
            lines.append(" ".join(parts))
        elif role == "RootWebArea":
            if name:
                lines.append(f'{indent}page "{name[:80]}"')
            for child_id in children_map.get(node_id, []):
                self._walk_cdp_tree(child_id, node_map, children_map, lines, depth)
            return
        else:
            if name and role not in ("", "generic", "none", "paragraph",
                                     "Section", "group", "LayoutTable",
                                     "LayoutTableRow", "LayoutTableCell"):
                display = name[:120] + "..." if len(name) > 120 else name
                lines.append(f"{indent}{role} \"{display}\"")

        # Recurse
        next_depth = depth + (1 if (name and is_interactive) or role in ("list", "navigation", "form", "dialog", "menu") else 0)
        for child_id in children_map.get(node_id, []):
            self._walk_cdp_tree(child_id, node_map, children_map, lines, next_depth)

    def _resolve_ref(self, ref: int):
        """Resolve a numeric ref to a Playwright locator.

        Strategy: get_by_role(role, name) → get_by_placeholder → get_by_text → error.
        If the ref is inside an iframe, uses frame_locator for scoped resolution.
        """
        if ref not in self._ref_map:
            raise ValueError(f"Ref {ref} not found. Run snapshot first to get current refs.")

        info = self._ref_map[ref]
        role = info["role"].lower()
        name = info["name"]
        frame_selector = info.get("in_frame")

        # Determine the base scope: page or frame_locator
        if frame_selector:
            base = self._page.frame_locator(frame_selector)
        else:
            base = self._page

        # Primary: get_by_role
        try:
            locator = base.get_by_role(role, name=name, exact=False)
            if locator.count() > 1:
                exact = base.get_by_role(role, name=name, exact=True)
                if exact.count() >= 1:
                    return exact.first
                return locator.first
            if locator.count() == 1:
                return locator
        except Exception:
            pass

        # Fallback: get_by_placeholder
        if name:
            try:
                fb = base.get_by_placeholder(name, exact=False)
                if fb.count() > 0:
                    return fb.first
            except Exception:
                pass
            try:
                fb = base.get_by_text(name, exact=False)
                if fb.count() > 0:
                    return fb.first
            except Exception:
                pass

        raise ValueError(
            f"Element not found for ref {ref} (role={role}, name='{name}'). "
            f"Page may have changed — run snapshot again."
        )

    def _page_info(self) -> str:
        """Get current page URL and title."""
        try:
            title = self._page.title()
            url = self._page.url
            return f"URL: {url}\nTitle: {title}"
        except Exception:
            return "URL: unknown"

    # =========================================================================
    # Actions
    # =========================================================================

    def _action_navigate(self, kwargs) -> ToolResult:
        url = kwargs.get("url")
        if not url:
            return ToolResult(success=False, error="'url' is required for navigate")

        timeout = kwargs.get("timeout", 30) * 1000
        response = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        status = response.status if response else 0

        # Wait briefly for dynamic content
        try:
            self._page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        # Auto-snapshot
        snapshot = self._build_snapshot()
        info = self._page_info()

        return ToolResult(
            success=True,
            output=f"Navigated (status {status})\n{info}\n\n{snapshot}",
            data={"status": status, "url": self._page.url, "title": self._page.title()},
        )

    def _action_snapshot(self, kwargs) -> ToolResult:
        snapshot = self._build_snapshot()
        info = self._page_info()
        frame_note = f"\nActive frame: {self._active_frame}" if self._active_frame else ""

        return ToolResult(
            success=True,
            output=f"{info}{frame_note}\n\n{snapshot}",
            data={
                "url": self._page.url,
                "refs_count": len(self._ref_map),
                "active_frame": self._active_frame,
            },
        )

    def _action_click(self, kwargs) -> ToolResult:
        ref = kwargs.get("ref")
        if ref is None:
            return ToolResult(success=False, error="'ref' is required for click")

        locator = self._resolve_ref(ref)
        locator.click(timeout=DEFAULT_TIMEOUT)

        # Wait for potential navigation/DOM changes
        try:
            self._page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass

        snapshot = self._build_snapshot()
        info = self._page_info()

        return ToolResult(
            success=True,
            output=f"Clicked ref {ref}\n{info}\n\n{snapshot}",
            data={"ref": ref, "url": self._page.url},
        )

    def _action_type(self, kwargs) -> ToolResult:
        ref = kwargs.get("ref")
        text = kwargs.get("text", "")
        if ref is None:
            return ToolResult(success=False, error="'ref' is required for type")
        if not text:
            return ToolResult(success=False, error="'text' is required for type")

        locator = self._resolve_ref(ref)

        # Try fill first (works for input/textarea/select)
        try:
            locator.fill(text, timeout=5000)
        except Exception:
            # Fallback: click then type with keyboard (works for combobox, contenteditable, etc.)
            try:
                locator.click(timeout=5000)
                # Select all existing text and replace
                self._page.keyboard.press("Control+a")
                self._page.keyboard.type(text, delay=30)
            except Exception as e:
                return ToolResult(success=False, error=f"Could not type into ref {ref}: {e}")

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Typed '{text}' into ref {ref}\n{self._page_info()}\n\n{snapshot}",
            data={"ref": ref, "text": text},
        )

    def _action_hover(self, kwargs) -> ToolResult:
        ref = kwargs.get("ref")
        if ref is None:
            return ToolResult(success=False, error="'ref' is required for hover")

        locator = self._resolve_ref(ref)
        locator.hover(timeout=DEFAULT_TIMEOUT)

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Hovered ref {ref}\n{self._page_info()}\n\n{snapshot}",
            data={"ref": ref},
        )

    def _action_select(self, kwargs) -> ToolResult:
        ref = kwargs.get("ref")
        text = kwargs.get("text", "")
        if ref is None:
            return ToolResult(success=False, error="'ref' is required for select")
        if not text:
            return ToolResult(success=False, error="'text' (option label) is required for select")

        locator = self._resolve_ref(ref)
        locator.select_option(label=text, timeout=DEFAULT_TIMEOUT)

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Selected '{text}' in ref {ref}\n{self._page_info()}\n\n{snapshot}",
            data={"ref": ref, "text": text},
        )

    def _action_scroll(self, kwargs) -> ToolResult:
        direction = kwargs.get("direction", "down")
        delta = 500 if direction == "down" else -500
        self._page.mouse.wheel(0, delta)

        # Brief wait for lazy content
        try:
            self._page.wait_for_timeout(500)
        except Exception:
            pass

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Scrolled {direction}\n{self._page_info()}\n\n{snapshot}",
        )

    def _action_back(self, kwargs) -> ToolResult:
        self._page.go_back(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Went back\n{self._page_info()}\n\n{snapshot}",
        )

    def _action_forward(self, kwargs) -> ToolResult:
        self._page.go_forward(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Went forward\n{self._page_info()}\n\n{snapshot}",
        )

    def _action_refresh(self, kwargs) -> ToolResult:
        self._page.reload(wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Refreshed\n{self._page_info()}\n\n{snapshot}",
        )

    def _action_screenshot(self, kwargs) -> ToolResult:
        png_bytes = self._page.screenshot(full_page=False)
        b64 = base64.b64encode(png_bytes).decode("utf-8")

        return ToolResult(
            success=True,
            output=f"Screenshot captured ({len(png_bytes)} bytes)\n{self._page_info()}",
            data={
                "screenshot_base64": b64,
                "size_bytes": len(png_bytes),
                "url": self._page.url,
            },
        )

    # =========================================================================
    # Tab management
    # =========================================================================

    def _action_tab_new(self, kwargs) -> ToolResult:
        url = kwargs.get("url", "about:blank")
        page = self._context.new_page()

        tab_id = self._next_tab_id
        self._next_tab_id += 1
        self._pages[tab_id] = page
        self._page = page
        self._active_tab = tab_id

        if url and url != "about:blank":
            page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"New tab {tab_id} opened\n{self._page_info()}\n\n{snapshot}",
            data={"tab_id": tab_id, "url": page.url},
        )

    def _action_tab_list(self, kwargs) -> ToolResult:
        lines = []
        for tid, page in self._pages.items():
            try:
                url = page.url
                title = page.title()[:60]
            except Exception:
                url = "closed"
                title = ""
            marker = " ←" if tid == self._active_tab else ""
            lines.append(f"  [{tid}] {title} — {url}{marker}")

        return ToolResult(
            success=True,
            output=f"Tabs ({len(self._pages)}):\n" + "\n".join(lines),
            data={"count": len(self._pages), "active": self._active_tab},
        )

    def _action_tab_switch(self, kwargs) -> ToolResult:
        tab_id = kwargs.get("tab_id")
        if tab_id is None:
            return ToolResult(success=False, error="'tab_id' is required")

        if tab_id not in self._pages:
            return ToolResult(success=False, error=f"Tab {tab_id} not found")

        self._page = self._pages[tab_id]
        self._active_tab = tab_id
        self._page.bring_to_front()

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Switched to tab {tab_id}\n{self._page_info()}\n\n{snapshot}",
            data={"tab_id": tab_id},
        )

    def _action_tab_close(self, kwargs) -> ToolResult:
        tab_id = kwargs.get("tab_id")
        if tab_id is None:
            return ToolResult(success=False, error="'tab_id' is required")

        if tab_id not in self._pages:
            return ToolResult(success=False, error=f"Tab {tab_id} not found")

        if len(self._pages) <= 1:
            return ToolResult(success=False, error="Cannot close the last tab")

        self._pages[tab_id].close()
        del self._pages[tab_id]

        # Switch to another tab if we closed the active one
        if self._active_tab == tab_id:
            self._active_tab = next(iter(self._pages))
            self._page = self._pages[self._active_tab]

        return ToolResult(
            success=True,
            output=f"Closed tab {tab_id}. Active: {self._active_tab}",
            data={"closed": tab_id, "active": self._active_tab},
        )

    # =========================================================================
    # Cookies, evaluate, wait, close
    # =========================================================================

    def _action_cookies(self, kwargs) -> ToolResult:
        cookies = self._context.cookies()
        if not cookies:
            return ToolResult(success=True, output="No cookies.", data={"cookies": []})

        lines = [f"Cookies ({len(cookies)}):"]
        for c in cookies[:20]:  # Limit display
            lines.append(f"  {c['name']}={c['value'][:40]} (domain={c.get('domain','')})")

        return ToolResult(
            success=True,
            output="\n".join(lines),
            data={"cookies": cookies, "count": len(cookies)},
        )

    def _action_evaluate(self, kwargs) -> ToolResult:
        js = kwargs.get("text")
        if not js:
            return ToolResult(success=False, error="'text' (JS code) is required for evaluate")

        result = self._page.evaluate(js)
        output = str(result)[:2000] if result is not None else "undefined"

        return ToolResult(
            success=True,
            output=f"JS result: {output}",
            data={"result": result},
        )

    def _action_wait(self, kwargs) -> ToolResult:
        wait_for = kwargs.get("wait_for")
        if not wait_for:
            return ToolResult(success=False, error="'wait_for' is required (CSS selector or 'networkidle')")

        timeout = kwargs.get("timeout", 30) * 1000

        if wait_for == "networkidle":
            self._page.wait_for_load_state("networkidle", timeout=timeout)
        else:
            self._page.wait_for_selector(wait_for, timeout=timeout)

        snapshot = self._build_snapshot()
        return ToolResult(
            success=True,
            output=f"Wait complete ({wait_for})\n{self._page_info()}\n\n{snapshot}",
        )

    def _action_close(self, kwargs) -> ToolResult:
        self._cleanup()
        return ToolResult(
            success=True,
            output="Browser session closed.",
        )
