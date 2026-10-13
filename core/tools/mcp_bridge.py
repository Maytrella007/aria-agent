"""
ARIA - MCP Client Bridge
==========================

Client bridge for Model Context Protocol (MCP) servers.
Implements JSON-RPC 2.0 over stdio without external dependencies.

Allows ARIA to connect to any MCP-compatible server and use its tools
as if they were native ARIA tools.

Usage:
    # Automatic via config.yaml:
    mcp:
      enabled: true
      servers:
        filesystem:
          command: "npx"
          args: ["@modelcontextprotocol/server-filesystem", "/tmp"]

    # Programmatic:
    client = MCPClient("npx", ["@modelcontextprotocol/server-filesystem", "/tmp"])
    client.initialize()
    tools = client.list_tools()
    result = client.call_tool("read_file", {"path": "/tmp/test.txt"})
    client.shutdown()
"""

import json
import logging
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from .tool_base import ToolBase, ToolParam, ToolResult

logger = logging.getLogger("aria.tools.mcp")

# MCP protocol version we support
MCP_PROTOCOL_VERSION = "2024-11-05"

# Max message size (10 MB) to prevent OOM from malicious Content-Length
MAX_MESSAGE_SIZE = 10 * 1024 * 1024


# =============================================================================
# MCP CLIENT — JSON-RPC 2.0 over stdio
# =============================================================================

class MCPClient:
    """
    JSON-RPC 2.0 client that communicates with an MCP server over stdio.

    Handles:
    - Subprocess lifecycle (spawn, shutdown, kill)
    - Message framing (Content-Length and newline-delimited auto-detection)
    - Request/response matching by ID
    - Thread-safe writes and ID generation
    - Reconnection with exponential backoff
    """

    def __init__(
        self,
        command: str,
        args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        timeout: float = 30.0,
        reconnect_attempts: int = 3,
    ):
        self.command = command
        self.args = args or []
        self.env = env
        self.cwd = cwd
        self.timeout = timeout
        self.reconnect_attempts = reconnect_attempts

        self._process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()  # Protects _request_id, _pending, and stdin writes
        self._pending: Dict[int, Tuple[threading.Event, dict]] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._uses_content_length = False
        self._server_capabilities: Dict[str, Any] = {}
        self._server_info: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start(self):
        """Start the MCP server subprocess and reader thread."""
        merged_env = os.environ.copy()
        if self.env:
            merged_env.update(self.env)

        try:
            self._process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=merged_env,
                cwd=self.cwd,
                bufsize=0,
            )
        except FileNotFoundError:
            raise MCPError(f"MCP server command not found: {self.command}")
        except Exception as e:
            raise MCPError(f"Failed to start MCP server: {e}")

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="mcp-reader"
        )
        self._reader_thread.start()

    def initialize(self) -> Dict[str, Any]:
        """
        Perform MCP handshake: initialize + initialized notification.

        Returns server capabilities dict.
        """
        if not self._process:
            self.start()

        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "ARIA",
                "version": "0.6.0",
            },
        })

        # Validate protocol version
        server_version = result.get("protocolVersion", "")
        if server_version and server_version != MCP_PROTOCOL_VERSION:
            logger.warning(
                f"MCP protocol version mismatch: client={MCP_PROTOCOL_VERSION}, "
                f"server={server_version}"
            )

        self._server_capabilities = result.get("capabilities", {})
        self._server_info = result.get("serverInfo", {})

        # Send initialized notification (no response expected)
        self._notify("notifications/initialized", {})

        logger.info(
            f"MCP server initialized: {self._server_info.get('name', 'unknown')} "
            f"v{self._server_info.get('version', '?')}"
        )
        return result

    def shutdown(self):
        """Gracefully shutdown the MCP server (shutdown request + SIGTERM)."""
        self._running = False

        if self._process and self._process.poll() is None:
            # Send shutdown notification per MCP spec (best-effort)
            try:
                self._notify("notifications/cancelled", {"reason": "shutdown"})
            except Exception:
                pass

            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2)
            except Exception:
                pass

        # Wake up any pending requests
        with self._lock:
            for req_id, (event, _) in list(self._pending.items()):
                event.set()
            self._pending.clear()

        self._process = None
        logger.info("MCP client shut down")

    @property
    def is_alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    @property
    def server_info(self) -> Dict[str, Any]:
        """Public accessor for server info."""
        return self._server_info

    # -------------------------------------------------------------------------
    # MCP Operations
    # -------------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """Call tools/list with pagination support. Returns all tool descriptors."""
        all_tools = []
        cursor = None

        while True:
            params = {}
            if cursor:
                params["cursor"] = cursor

            result = self._request("tools/list", params)
            all_tools.extend(result.get("tools", []))

            cursor = result.get("nextCursor")
            if not cursor:
                break

        return all_tools

    def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Call a tool on the MCP server.

        Returns dict with 'content' (list of content blocks) and optional 'isError'.
        """
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        )
        return result

    # -------------------------------------------------------------------------
    # JSON-RPC Transport
    # -------------------------------------------------------------------------

    def _next_id(self) -> int:
        """Generate next request ID. Must be called with self._lock held."""
        self._request_id += 1
        return self._request_id

    def _request(self, method: str, params: dict, timeout: Optional[float] = None) -> dict:
        """Send a JSON-RPC request and wait for the response."""
        if not self.is_alive:
            # Try reconnect
            if not self._try_reconnect():
                raise MCPError(f"MCP server not running, reconnect failed")

        event = threading.Event()

        with self._lock:
            req_id = self._next_id()
            self._pending[req_id] = (event, {})

        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        self._send(message)

        effective_timeout = timeout or self.timeout
        if not event.wait(timeout=effective_timeout):
            with self._lock:
                self._pending.pop(req_id, None)
            raise MCPTimeoutError(f"MCP request timed out after {effective_timeout}s: {method}")

        with self._lock:
            _, response = self._pending.pop(req_id, (None, {}))

        if "error" in response:
            err = response["error"]
            code = err.get("code", -1)
            msg = err.get("message", "Unknown error")
            raise MCPError(f"MCP error {code}: {msg}")

        return response.get("result", {})

    def _notify(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._send(message)

    def _send(self, message: dict):
        """Write a JSON-RPC message to the server's stdin (thread-safe)."""
        if not self._process or not self._process.stdin:
            raise MCPError("MCP server stdin not available")

        data = json.dumps(message)
        encoded = data.encode("utf-8")

        with self._lock:
            try:
                if self._uses_content_length:
                    header = f"Content-Length: {len(encoded)}\r\n\r\n"
                    self._process.stdin.write(header.encode("utf-8"))
                    self._process.stdin.write(encoded)
                else:
                    self._process.stdin.write(encoded + b"\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as e:
                raise MCPError(f"Failed to write to MCP server: {e}")

    # -------------------------------------------------------------------------
    # Reader Thread
    # -------------------------------------------------------------------------

    def _reader_loop(self):
        """Background thread: reads stdout and dispatches responses."""
        try:
            # Peek at first bytes to detect framing
            first_bytes = self._process.stdout.peek(20) if hasattr(self._process.stdout, 'peek') else b""
            if first_bytes.startswith(b"Content-Length:"):
                self._uses_content_length = True
                logger.debug("MCP server uses Content-Length framing")

            while self._running and self.is_alive:
                try:
                    if self._uses_content_length:
                        message = self._read_content_length()
                    else:
                        message = self._read_newline_delimited()

                    if message is None:
                        continue

                    self._dispatch(message)
                except json.JSONDecodeError as e:
                    logger.warning(f"MCP: invalid JSON: {e}")
                except Exception as e:
                    if self._running:
                        logger.warning(f"MCP reader error: {e}")
                    break
        except Exception as e:
            if self._running:
                logger.error(f"MCP reader thread crashed: {e}")

    def _read_newline_delimited(self) -> Optional[dict]:
        """Read a newline-delimited JSON message."""
        line = self._process.stdout.readline()
        if not line:
            if self._running:
                raise MCPError("MCP server stdout closed")
            return None

        line = line.decode("utf-8").strip()
        if not line:
            return None

        # Auto-detect switch to Content-Length framing
        if line.startswith("Content-Length:"):
            self._uses_content_length = True
            length = int(line.split(":")[1].strip())
            if length <= 0 or length > MAX_MESSAGE_SIZE:
                raise MCPError(f"Invalid Content-Length: {length}")
            # Read blank line separator
            self._process.stdout.readline()
            data = self._read_exact(length)
            return json.loads(data)

        return json.loads(line)

    def _read_content_length(self) -> Optional[dict]:
        """Read a Content-Length framed message (LSP-style)."""
        # Read headers
        content_length = None
        while True:
            header_line = self._process.stdout.readline()
            if not header_line:
                if self._running:
                    raise MCPError("MCP server stdout closed")
                return None

            header = header_line.decode("utf-8").strip()
            if not header:
                break  # End of headers

            if header.lower().startswith("content-length:"):
                content_length = int(header.split(":")[1].strip())

        if content_length is None or content_length <= 0:
            return None

        if content_length > MAX_MESSAGE_SIZE:
            raise MCPError(f"Content-Length {content_length} exceeds max {MAX_MESSAGE_SIZE}")

        data = self._read_exact(content_length)
        return json.loads(data)

    def _read_exact(self, n: int) -> str:
        """Read exactly n bytes from stdout."""
        chunks = []
        remaining = n
        while remaining > 0:
            chunk = self._process.stdout.read(remaining)
            if not chunk:
                raise MCPError("MCP server stdout closed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks).decode("utf-8")

    def _dispatch(self, message: dict):
        """Route an incoming JSON-RPC message to the appropriate handler."""
        # Validate JSON-RPC 2.0
        if message.get("jsonrpc") != "2.0":
            logger.warning(f"MCP: non-JSON-RPC 2.0 message received, ignoring")
            return

        # Response (has id, no method)
        if "id" in message and "method" not in message:
            req_id = message["id"]
            with self._lock:
                if req_id in self._pending:
                    event, _ = self._pending[req_id]
                    self._pending[req_id] = (event, message)
                    event.set()
                else:
                    logger.warning(f"MCP: unexpected response id={req_id}")

        # Notification (has method, no id)
        elif "method" in message and "id" not in message:
            method = message.get("method", "")
            logger.debug(f"MCP notification: {method}")
            # Handle tools/list_changed by flagging for re-discovery
            if method == "notifications/tools/list_changed":
                logger.info("MCP server signaled tools changed (re-discovery needed)")

        # Request from server (has method + id) — respond with method-not-found
        elif "method" in message and "id" in message:
            logger.debug(f"MCP server request: {message.get('method')}")
            error_response = {
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {
                    "code": -32601,
                    "message": f"Method not supported: {message.get('method')}",
                },
            }
            try:
                self._send(error_response)
            except Exception:
                pass

    # -------------------------------------------------------------------------
    # Reconnection
    # -------------------------------------------------------------------------

    def _try_reconnect(self) -> bool:
        """Attempt to reconnect with exponential backoff."""
        for attempt in range(1, self.reconnect_attempts + 1):
            delay = min(2 ** (attempt - 1), 10)
            logger.info(f"MCP reconnect attempt {attempt}/{self.reconnect_attempts} in {delay}s...")
            time.sleep(delay)

            try:
                self.shutdown()
                self.start()
                self.initialize()
                logger.info("MCP reconnected successfully")
                return True
            except Exception as e:
                logger.warning(f"MCP reconnect attempt {attempt} failed: {e}")

        return False


# =============================================================================
# MCP TOOL PROXY — Wraps an MCP tool as a native ARIA ToolBase
# =============================================================================

class MCPToolProxy(ToolBase):
    """
    Proxy that exposes an MCP server tool as a native ARIA ToolBase.

    Converts JSON Schema parameters to ToolParam and delegates
    execution to the MCPClient.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        server_name: str,
        tool_descriptor: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None,
    ):
        self._mcp_client = mcp_client
        self._server_name = server_name
        self._tool_descriptor = tool_descriptor
        self._original_name = tool_descriptor["name"]

        # Set ToolBase attributes
        self.name = f"mcp_{server_name}_{self._original_name}"
        self.description = f"[MCP:{server_name}] {tool_descriptor.get('description', 'No description')}"
        self.parameters = self._convert_schema(tool_descriptor.get("inputSchema", {}))

        super().__init__(context=context)

    def _execute(self, **kwargs) -> ToolResult:
        """Execute the MCP tool via the client."""
        try:
            result = self._mcp_client.call_tool(self._original_name, kwargs)

            # Extract text from content blocks
            content_blocks = result.get("content", [])
            is_error = result.get("isError", False)

            text_parts = []
            data = {}

            for block in content_blocks:
                block_type = block.get("type", "text")
                if block_type == "text":
                    text_parts.append(block.get("text", ""))
                elif block_type == "image":
                    text_parts.append(f"[Image: {block.get('mimeType', 'unknown')}]")
                    data.setdefault("images", []).append(block)
                elif block_type == "resource":
                    res = block.get("resource", {})
                    res_text = res.get("text", "")
                    uri = res.get("uri", "unknown")
                    text_parts.append(f"[Resource: {uri}]")
                    if res_text:
                        text_parts.append(res_text)
                    data.setdefault("resources", []).append(block)
                else:
                    text_parts.append(str(block))

            output = "\n".join(text_parts)

            if is_error:
                return ToolResult(
                    success=False,
                    error=output,
                    data=data,
                )

            return ToolResult(
                success=True,
                output=output,
                data=data,
            )

        except MCPTimeoutError as e:
            return ToolResult(success=False, error=f"MCP timeout: {e}")
        except MCPError as e:
            return ToolResult(success=False, error=f"MCP error: {e}")
        except Exception as e:
            logger.debug(f"MCPToolProxy unexpected error: {e}", exc_info=True)
            return ToolResult(success=False, error=f"MCP tool execution failed")

    @staticmethod
    def _convert_schema(input_schema: Dict[str, Any]) -> List[ToolParam]:
        """Convert JSON Schema properties to a list of ToolParam."""
        params = []
        properties = input_schema.get("properties", {})
        required_fields = set(input_schema.get("required", []))

        for prop_name, prop_def in properties.items():
            # Map JSON Schema types to ToolParam types
            json_type = prop_def.get("type", "string")
            if isinstance(json_type, list):
                # Union types like ["string", "null"] — use the first non-null
                json_type = next((t for t in json_type if t != "null"), "string")

            type_map = {
                "string": "string",
                "number": "number",
                "integer": "integer",
                "boolean": "boolean",
                "array": "array",
                "object": "string",  # Serialize objects as JSON strings
            }
            param_type = type_map.get(json_type, "string")

            # Warn about unsupported schema features
            if any(k in prop_def for k in ("$ref", "allOf", "oneOf", "anyOf")):
                logger.warning(
                    f"MCP schema for '{prop_name}' uses $ref/combinators — "
                    f"falling back to string type"
                )

            params.append(ToolParam(
                name=prop_name,
                type=param_type,
                description=prop_def.get("description", ""),
                required=prop_name in required_fields,
                default=prop_def.get("default"),
                enum=prop_def.get("enum"),
            ))

        return params


# =============================================================================
# MCP BRIDGE MANAGER — Orchestrates multiple MCP servers
# =============================================================================

class MCPBridgeManager:
    """
    Manages the lifecycle of multiple MCP server connections.

    Reads configuration, starts servers, discovers tools, and registers
    them with the ARIA tool registry. Non-fatal: a failing server
    does not block others.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._clients: Dict[str, MCPClient] = {}
        self._proxies: List[MCPToolProxy] = []

    def start_all(self, registry) -> int:
        """
        Start all configured MCP servers, discover tools, register them.

        Args:
            registry: ARIA ToolRegistry to register discovered tools.

        Returns:
            Number of tools registered.
        """
        servers = self._config.get("servers", {})
        if not servers:
            logger.info("No MCP servers configured")
            return 0

        timeout = self._config.get("timeout_seconds", 30)
        reconnect = self._config.get("reconnect_attempts", 3)
        total_tools = 0

        for server_name, server_config in servers.items():
            try:
                total_tools += self._start_server(
                    server_name, server_config, registry, timeout, reconnect
                )
            except Exception as e:
                logger.warning(f"MCP server '{server_name}' failed to start: {e}")
                # Non-fatal: continue with other servers

        logger.info(f"MCP bridge: {len(self._clients)} servers, {total_tools} tools registered")
        return total_tools

    def _start_server(
        self,
        name: str,
        config: Dict[str, Any],
        registry,
        timeout: float,
        reconnect: int,
    ) -> int:
        """Start a single MCP server and register its tools."""
        command = config.get("command")
        if not command:
            raise MCPError(f"MCP server '{name}' has no command")

        args = config.get("args", [])
        env = config.get("env")
        cwd = config.get("cwd")

        # Resolve env vars
        if env:
            env = {k: os.path.expandvars(v) for k, v in env.items()}

        client = MCPClient(
            command=command,
            args=args,
            env=env,
            cwd=cwd,
            timeout=timeout,
            reconnect_attempts=reconnect,
        )

        client.initialize()

        # Discover and register tools — if this fails, shut down the client
        try:
            tool_descriptors = client.list_tools()
            logger.info(f"MCP server '{name}': {len(tool_descriptors)} tools discovered")

            for descriptor in tool_descriptors:
                proxy = MCPToolProxy(
                    mcp_client=client,
                    server_name=name,
                    tool_descriptor=descriptor,
                )
                registry.register(proxy)
                self._proxies.append(proxy)

            self._clients[name] = client
            return len(tool_descriptors)
        except Exception:
            client.shutdown()
            raise

    def shutdown_all(self):
        """Shutdown all MCP server connections."""
        for name, client in self._clients.items():
            try:
                client.shutdown()
                logger.info(f"MCP server '{name}' shut down")
            except Exception as e:
                logger.warning(f"Error shutting down MCP server '{name}': {e}")

        self._clients.clear()
        self._proxies.clear()

    @property
    def server_count(self) -> int:
        return len(self._clients)

    @property
    def tool_count(self) -> int:
        return len(self._proxies)

    def status(self) -> Dict[str, Any]:
        """Return status summary of all MCP connections."""
        return {
            "servers": {
                name: {
                    "alive": client.is_alive,
                    "info": client.server_info,
                }
                for name, client in self._clients.items()
            },
            "total_tools": len(self._proxies),
        }


# =============================================================================
# EXCEPTIONS
# =============================================================================

class MCPError(Exception):
    """General MCP error."""
    pass


class MCPTimeoutError(MCPError):
    """MCP request timed out."""
    pass
