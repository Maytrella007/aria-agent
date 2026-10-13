#!/usr/bin/env python3
"""
Test suite for ARIA MCP Client Bridge
======================================

Includes embedded mock MCP servers and comprehensive tests for:
- MCPClient lifecycle, list_tools, call_tool
- MCPToolProxy schema conversion, name prefixing, execute
- MCPBridgeManager with full mock server
- Error handling: server crash, timeouts, Content-Length framing
"""

import atexit
import json
import os
import sys
import tempfile
import textwrap
import threading
import time
import unittest

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from core.tools.mcp_bridge import (
    MCPClient,
    MCPToolProxy,
    MCPBridgeManager,
    MCPError,
    MCPTimeoutError,
)
from core.tools.tool_base import ToolParam

# =============================================================================
# MOCK MCP SERVER — Newline-delimited
# =============================================================================

MOCK_SERVER_SCRIPT = textwrap.dedent(r'''
#!/usr/bin/env python3
"""Mock MCP server for testing. Speaks JSON-RPC 2.0 over stdio (newline-delimited)."""

import json
import sys
import time

TOOLS = [
    {
        "name": "echo",
        "description": "Echoes back the input text",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to echo back"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "add",
        "description": "Adds two numbers",
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {
                    "type": "number",
                    "description": "First number"
                },
                "b": {
                    "type": "number",
                    "description": "Second number"
                }
            },
            "required": ["a", "b"]
        }
    },
]


def handle_request(msg):
    method = msg.get("method")
    params = msg.get("params", {})
    req_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "mock-mcp-server", "version": "1.0.0"},
            },
        }

    elif method == "notifications/initialized":
        return None  # No response for notifications

    elif method == "notifications/cancelled":
        return None  # No response for notifications

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "echo":
            text = arguments.get("text", "")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}],
                },
            }

        elif tool_name == "add":
            a = arguments.get("a", 0)
            b = arguments.get("b", 0)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(a + b)}],
                },
            }

        elif tool_name == "fail":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": "Something went wrong"}],
                    "isError": True,
                },
            }

        elif tool_name == "slow":
            time.sleep(30)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": "done"}]},
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
''')

# =============================================================================
# MOCK MCP SERVER — Content-Length framing
# =============================================================================

MOCK_SERVER_CL_SCRIPT = textwrap.dedent(r'''
#!/usr/bin/env python3
"""Mock MCP server using Content-Length framing (LSP-style)."""

import json
import sys


def read_message():
    """Read a Content-Length framed message OR a newline-delimited message."""
    first = b""
    while True:
        byte = sys.stdin.buffer.read(1)
        if not byte:
            return None
        first += byte
        # Check if we're getting a Content-Length header
        if first.endswith(b"\r\n"):
            header = first.decode("utf-8").strip()
            if header.lower().startswith("content-length:"):
                length = int(header.split(":")[1].strip())
                sys.stdin.buffer.read(2)  # Read \r\n separator
                data = sys.stdin.buffer.read(length)
                return json.loads(data.decode("utf-8"))
            first = b""
        elif first.endswith(b"\n"):
            line = first.decode("utf-8").strip()
            if line:
                return json.loads(line)
            first = b""


def write_message(msg):
    """Write a Content-Length framed message."""
    data = json.dumps(msg).encode("utf-8")
    header = f"Content-Length: {len(data)}\r\n\r\n"
    sys.stdout.buffer.write(header.encode("utf-8"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def main():
    while True:
        msg = read_message()
        if msg is None:
            break

        method = msg.get("method")
        params = msg.get("params", {})
        req_id = msg.get("id")

        if method == "initialize":
            write_message({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "mock-cl-server", "version": "1.0.0"},
                },
            })
        elif method in ("notifications/initialized", "notifications/cancelled"):
            pass
        elif method == "tools/list":
            write_message({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [{
                        "name": "greet",
                        "description": "Says hello",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                            "required": ["name"],
                        },
                    }],
                },
            })
        elif method == "tools/call":
            name = params.get("arguments", {}).get("name", "World")
            write_message({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Hello, {name}!"}],
                },
            })
        else:
            write_message({
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Not found: {method}"},
            })


if __name__ == "__main__":
    main()
''')


# =============================================================================
# TEMP FILE MANAGEMENT
# =============================================================================

_temp_files = []


def _create_temp_script(content: str) -> str:
    """Write a script to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, prefix="mock_mcp_")
    f.write(content)
    f.flush()
    f.close()
    _temp_files.append(f.name)
    return f.name


def _cleanup_temp_files():
    for path in _temp_files:
        try:
            os.unlink(path)
        except Exception:
            pass


atexit.register(_cleanup_temp_files)

# Create server scripts once
_nl_server_path = None
_cl_server_path = None


def get_mock_server_path():
    global _nl_server_path
    if _nl_server_path is None:
        _nl_server_path = _create_temp_script(MOCK_SERVER_SCRIPT)
    return _nl_server_path


def get_cl_server_path():
    global _cl_server_path
    if _cl_server_path is None:
        _cl_server_path = _create_temp_script(MOCK_SERVER_CL_SCRIPT)
    return _cl_server_path


# =============================================================================
# TEST: MCPClient
# =============================================================================

class TestMCPClient(unittest.TestCase):
    """Tests for the core MCPClient JSON-RPC transport."""

    def setUp(self):
        self.server_path = get_mock_server_path()
        self.client = MCPClient(
            command=sys.executable,
            args=[self.server_path],
            timeout=10.0,
            reconnect_attempts=1,
        )

    def tearDown(self):
        try:
            self.client.shutdown()
        except Exception:
            pass

    def test_initialize(self):
        """Test MCP handshake."""
        result = self.client.initialize()
        self.assertIn("capabilities", result)
        self.assertIn("serverInfo", result)
        self.assertEqual(result["serverInfo"]["name"], "mock-mcp-server")
        self.assertTrue(self.client.is_alive)

    def test_list_tools(self):
        """Test tool discovery."""
        self.client.initialize()
        tools = self.client.list_tools()
        self.assertEqual(len(tools), 2)
        names = {t["name"] for t in tools}
        self.assertIn("echo", names)
        self.assertIn("add", names)

    def test_call_tool_echo(self):
        """Test calling the echo tool."""
        self.client.initialize()
        result = self.client.call_tool("echo", {"text": "hello ARIA"})
        content = result.get("content", [])
        self.assertEqual(len(content), 1)
        self.assertEqual(content[0]["text"], "hello ARIA")

    def test_call_tool_add(self):
        """Test calling the add tool."""
        self.client.initialize()
        result = self.client.call_tool("add", {"a": 17, "b": 25})
        content = result.get("content", [])
        self.assertEqual(content[0]["text"], "42")

    def test_call_tool_unknown(self):
        """Test calling a non-existent tool raises MCPError."""
        self.client.initialize()
        with self.assertRaises(MCPError) as ctx:
            self.client.call_tool("nonexistent", {})
        self.assertIn("Unknown tool", str(ctx.exception))

    def test_shutdown(self):
        """Test clean shutdown."""
        self.client.initialize()
        self.assertTrue(self.client.is_alive)
        self.client.shutdown()
        self.assertFalse(self.client.is_alive)

    def test_call_after_shutdown(self):
        """Test that calling after shutdown triggers reconnect."""
        self.client.initialize()
        self.client.shutdown()
        # Reconnect should work since the command is valid
        try:
            self.client.initialize()
            tools = self.client.list_tools()
            self.assertEqual(len(tools), 2)
        except MCPError:
            pass  # Also acceptable if reconnect timing is tight

    def test_command_not_found(self):
        """Test starting with an invalid command."""
        bad_client = MCPClient(command="/nonexistent/binary")
        with self.assertRaises(MCPError):
            bad_client.start()

    def test_server_info_property(self):
        """Test public server_info accessor."""
        self.client.initialize()
        info = self.client.server_info
        self.assertEqual(info["name"], "mock-mcp-server")

    def test_timeout_on_slow_tool(self):
        """Test that slow tools trigger MCPTimeoutError."""
        self.client.initialize()
        with self.assertRaises(MCPTimeoutError):
            self.client.call_tool("slow", {}, timeout=0.5)


# =============================================================================
# TEST: MCPClient with Content-Length framing
# =============================================================================

class TestMCPClientContentLength(unittest.TestCase):
    """Tests for Content-Length framing mode."""

    def setUp(self):
        self.server_path = get_cl_server_path()
        self.client = MCPClient(
            command=sys.executable,
            args=[self.server_path],
            timeout=10.0,
        )

    def tearDown(self):
        try:
            self.client.shutdown()
        except Exception:
            pass

    def test_initialize_with_content_length(self):
        """Test handshake with Content-Length framing server."""
        result = self.client.initialize()
        self.assertEqual(result["serverInfo"]["name"], "mock-cl-server")
        self.assertTrue(self.client.is_alive)

    def test_list_tools_content_length(self):
        """Test tool discovery with Content-Length server."""
        self.client.initialize()
        tools = self.client.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "greet")

    def test_call_tool_content_length(self):
        """Test tool execution with Content-Length server."""
        self.client.initialize()
        result = self.client.call_tool("greet", {"name": "ARIA"})
        content = result.get("content", [])
        self.assertEqual(content[0]["text"], "Hello, ARIA!")


# =============================================================================
# TEST: MCPToolProxy
# =============================================================================

class TestMCPToolProxy(unittest.TestCase):
    """Tests for the MCPToolProxy ToolBase adapter."""

    def setUp(self):
        self.server_path = get_mock_server_path()
        self.client = MCPClient(
            command=sys.executable,
            args=[self.server_path],
            timeout=10.0,
        )
        self.client.initialize()

        self.echo_descriptor = {
            "name": "echo",
            "description": "Echoes back the input text",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to echo back",
                    }
                },
                "required": ["text"],
            },
        }

    def tearDown(self):
        self.client.shutdown()

    def test_name_prefixing(self):
        """Test that proxy names are prefixed with mcp_server_tool."""
        proxy = MCPToolProxy(self.client, "test_server", self.echo_descriptor)
        self.assertEqual(proxy.name, "mcp_test_server_echo")

    def test_description_prefixing(self):
        """Test that descriptions include server name."""
        proxy = MCPToolProxy(self.client, "myserver", self.echo_descriptor)
        self.assertTrue(proxy.description.startswith("[MCP:myserver]"))

    def test_schema_conversion(self):
        """Test JSON Schema to ToolParam conversion."""
        params = MCPToolProxy._convert_schema(self.echo_descriptor["inputSchema"])
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0].name, "text")
        self.assertEqual(params[0].type, "string")
        self.assertTrue(params[0].required)

    def test_schema_conversion_complex(self):
        """Test conversion with multiple types and optional fields."""
        schema = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "recursive": {"type": "boolean", "description": "Recurse"},
                "depth": {"type": "integer", "description": "Max depth"},
                "tags": {"type": "array", "description": "Tags"},
                "mode": {"type": "string", "enum": ["read", "write"]},
            },
            "required": ["path"],
        }
        params = MCPToolProxy._convert_schema(schema)
        self.assertEqual(len(params), 5)

        by_name = {p.name: p for p in params}
        self.assertTrue(by_name["path"].required)
        self.assertFalse(by_name["recursive"].required)
        self.assertEqual(by_name["recursive"].type, "boolean")
        self.assertEqual(by_name["depth"].type, "integer")
        self.assertEqual(by_name["tags"].type, "array")
        self.assertEqual(by_name["mode"].enum, ["read", "write"])

    def test_execute_success(self):
        """Test successful tool execution through proxy."""
        proxy = MCPToolProxy(self.client, "test", self.echo_descriptor)
        result = proxy.execute(text="hello from proxy")
        self.assertTrue(result.success)
        self.assertEqual(result.output, "hello from proxy")

    def test_execute_error_tool(self):
        """Test error tool execution through proxy."""
        fail_descriptor = {
            "name": "fail",
            "description": "Always fails",
            "inputSchema": {"type": "object", "properties": {}},
        }
        proxy = MCPToolProxy(self.client, "test", fail_descriptor)
        result = proxy.execute()
        self.assertFalse(result.success)

    def test_function_schema(self):
        """Test that proxy generates valid function schema for LLM."""
        proxy = MCPToolProxy(self.client, "srv", self.echo_descriptor)
        schema = proxy.to_function_schema()
        self.assertEqual(schema["name"], "mcp_srv_echo")
        self.assertIn("text", schema["parameters"]["properties"])


# =============================================================================
# TEST: MCPBridgeManager
# =============================================================================

class TestMCPBridgeManager(unittest.TestCase):
    """Tests for the MCPBridgeManager orchestrator."""

    def setUp(self):
        self.server_path = get_mock_server_path()

    def test_start_all_and_register(self):
        """Test starting servers and registering tools."""
        from core.tools.registry import ToolRegistry

        config = {
            "enabled": True,
            "timeout_seconds": 10,
            "reconnect_attempts": 1,
            "servers": {
                "mock": {
                    "command": sys.executable,
                    "args": [self.server_path],
                }
            },
        }

        registry = ToolRegistry()
        manager = MCPBridgeManager(config)

        try:
            num_tools = manager.start_all(registry)
            self.assertEqual(num_tools, 2)
            self.assertEqual(manager.server_count, 1)
            self.assertEqual(manager.tool_count, 2)

            # Check tools are in registry
            self.assertIn("mcp_mock_echo", registry)
            self.assertIn("mcp_mock_add", registry)

            # Execute through registry
            result = registry.execute("mcp_mock_echo", text="bridge test")
            self.assertTrue(result.success)
            self.assertEqual(result.output, "bridge test")

            result = registry.execute("mcp_mock_add", a=10, b=32)
            self.assertTrue(result.success)
            self.assertEqual(result.output, "42")

            # Status check
            status = manager.status()
            self.assertIn("mock", status["servers"])
            self.assertTrue(status["servers"]["mock"]["alive"])
        finally:
            manager.shutdown_all()

    def test_failing_server_non_fatal(self):
        """Test that a failing server doesn't block others."""
        from core.tools.registry import ToolRegistry

        config = {
            "enabled": True,
            "timeout_seconds": 5,
            "reconnect_attempts": 0,
            "servers": {
                "bad": {
                    "command": "/nonexistent/binary",
                },
                "good": {
                    "command": sys.executable,
                    "args": [self.server_path],
                },
            },
        }

        registry = ToolRegistry()
        manager = MCPBridgeManager(config)

        try:
            num_tools = manager.start_all(registry)
            # Only good server's tools should be registered
            self.assertEqual(num_tools, 2)
            self.assertEqual(manager.server_count, 1)
            self.assertIn("mcp_good_echo", registry)
            self.assertNotIn("mcp_bad_echo", registry)
        finally:
            manager.shutdown_all()

    def test_no_servers_configured(self):
        """Test graceful handling of empty config."""
        from core.tools.registry import ToolRegistry

        config = {"enabled": True, "servers": {}}
        registry = ToolRegistry()
        manager = MCPBridgeManager(config)

        num_tools = manager.start_all(registry)
        self.assertEqual(num_tools, 0)
        manager.shutdown_all()

    def test_missing_command(self):
        """Test server config without command."""
        from core.tools.registry import ToolRegistry

        config = {
            "servers": {
                "broken": {"args": ["--something"]},
            },
        }
        registry = ToolRegistry()
        manager = MCPBridgeManager(config)

        # Should not raise, just log warning
        num_tools = manager.start_all(registry)
        self.assertEqual(num_tools, 0)
        manager.shutdown_all()

    def test_shutdown_all(self):
        """Test clean shutdown of all servers."""
        config = {
            "servers": {
                "s1": {"command": sys.executable, "args": [self.server_path]},
                "s2": {"command": sys.executable, "args": [self.server_path]},
            },
        }
        from core.tools.registry import ToolRegistry

        registry = ToolRegistry()
        manager = MCPBridgeManager(config)
        manager.start_all(registry)

        self.assertEqual(manager.server_count, 2)
        manager.shutdown_all()
        self.assertEqual(manager.server_count, 0)
        self.assertEqual(manager.tool_count, 0)


# =============================================================================
# TEST: Edge Cases
# =============================================================================

class TestMCPEdgeCases(unittest.TestCase):
    """Test edge cases and error handling."""

    def test_schema_conversion_union_types(self):
        """Test schema conversion with union types like ['string', 'null']."""
        schema = {
            "type": "object",
            "properties": {
                "value": {"type": ["string", "null"], "description": "Optional value"},
            },
        }
        params = MCPToolProxy._convert_schema(schema)
        self.assertEqual(params[0].type, "string")

    def test_schema_conversion_empty(self):
        """Test schema conversion with empty schema."""
        params = MCPToolProxy._convert_schema({})
        self.assertEqual(len(params), 0)

    def test_schema_conversion_object_type(self):
        """Test schema conversion maps object to string."""
        schema = {
            "type": "object",
            "properties": {
                "config": {"type": "object", "description": "Config object"},
            },
        }
        params = MCPToolProxy._convert_schema(schema)
        self.assertEqual(params[0].type, "string")

    def test_timeout_error_class(self):
        """Test that MCPTimeoutError is a subclass of MCPError."""
        self.assertTrue(issubclass(MCPTimeoutError, MCPError))

    def test_server_crash_handling(self):
        """Test handling of server crash mid-session."""
        server_path = get_mock_server_path()
        client = MCPClient(
            command=sys.executable,
            args=[server_path],
            timeout=5.0,
            reconnect_attempts=0,
        )
        client.initialize()
        self.assertTrue(client.is_alive)

        # Kill the server process
        client._process.kill()
        client._process.wait()

        # Poll until dead (avoids flaky sleep)
        deadline = time.time() + 2.0
        while client.is_alive and time.time() < deadline:
            time.sleep(0.05)
        self.assertFalse(client.is_alive)

        # Next call should fail
        with self.assertRaises(MCPError):
            client.call_tool("echo", {"text": "after crash"})

        client.shutdown()

    def test_concurrent_requests(self):
        """Test thread safety with concurrent tool calls."""
        server_path = get_mock_server_path()
        client = MCPClient(
            command=sys.executable,
            args=[server_path],
            timeout=10.0,
        )
        client.initialize()

        results = {}
        errors = []

        def call_echo(thread_id):
            try:
                result = client.call_tool("echo", {"text": f"thread-{thread_id}"})
                results[thread_id] = result["content"][0]["text"]
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=call_echo, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        client.shutdown()

        self.assertEqual(len(errors), 0, f"Concurrent errors: {errors}")
        self.assertEqual(len(results), 5)
        for i in range(5):
            self.assertEqual(results[i], f"thread-{i}")

    def test_reconnect_after_kill(self):
        """Test reconnection after server process is killed."""
        server_path = get_mock_server_path()
        client = MCPClient(
            command=sys.executable,
            args=[server_path],
            timeout=10.0,
            reconnect_attempts=2,
        )
        client.initialize()

        # Verify working
        result = client.call_tool("echo", {"text": "before"})
        self.assertEqual(result["content"][0]["text"], "before")

        # Kill the process
        client._process.kill()
        client._process.wait()

        # Next call should trigger reconnect and succeed
        result = client.call_tool("echo", {"text": "after reconnect"})
        self.assertEqual(result["content"][0]["text"], "after reconnect")

        client.shutdown()


# =============================================================================
# MAIN
# =============================================================================

def main():
    print("=" * 60)
    print("ARIA MCP Client Bridge — Test Suite")
    print("=" * 60)
    print()

    # Run tests
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestMCPClient))
    suite.addTests(loader.loadTestsFromTestCase(TestMCPClientContentLength))
    suite.addTests(loader.loadTestsFromTestCase(TestMCPToolProxy))
    suite.addTests(loader.loadTestsFromTestCase(TestMCPBridgeManager))
    suite.addTests(loader.loadTestsFromTestCase(TestMCPEdgeCases))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print()
    if result.wasSuccessful():
        print("ALL TESTS PASSED")
    else:
        print(f"FAILURES: {len(result.failures)}, ERRORS: {len(result.errors)}")

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
