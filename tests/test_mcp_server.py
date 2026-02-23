"""Tests for MCP server — config, tool listing, call routing, error handling."""

import asyncio
import pytest


# --- Config ---

class TestMCPConfig:
    def test_default_config_has_run_python_blacklisted(self):
        import mcp_server
        cfg = mcp_server._get_mcp_config()
        assert "run_python" in cfg["blacklist"]

    def test_user_config_merges_with_defaults(self, monkeypatch):
        import mcp_server
        import memory
        monkeypatch.setattr(memory, "load_config", lambda: {
            "mcp": {"blacklist": ["run_python", "write_file"], "server_name": "custom"}
        })
        cfg = mcp_server._get_mcp_config()
        assert cfg["blacklist"] == ["run_python", "write_file"]
        assert cfg["server_name"] == "custom"
        # Default keys still present
        assert "server_version" in cfg


# --- Tool listing ---

class TestGetMCPTools:
    def test_returns_nonempty_list(self):
        import mcp_server
        tools = mcp_server.get_mcp_tools()
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_every_tool_has_required_keys(self):
        import mcp_server
        for tool in mcp_server.get_mcp_tools():
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool missing 'description': {tool}"
            assert "inputSchema" in tool, f"Tool missing 'inputSchema': {tool}"

    def test_run_python_excluded_by_default(self):
        import mcp_server
        names = [t["name"] for t in mcp_server.get_mcp_tools()]
        assert "run_python" not in names

    def test_standard_tools_included(self):
        import mcp_server
        names = [t["name"] for t in mcp_server.get_mcp_tools()]
        for expected in ("web_search", "check_email", "list_tasks"):
            assert expected in names, f"Expected tool '{expected}' not found"

    def test_no_cache_control_on_any_tool(self):
        import mcp_server
        for tool in mcp_server.get_mcp_tools():
            assert "cache_control" not in tool, f"Tool '{tool['name']}' has cache_control"

    def test_custom_blacklist_removes_additional_tools(self, monkeypatch):
        import mcp_server
        import memory
        monkeypatch.setattr(memory, "load_config", lambda: {
            "mcp": {"blacklist": ["run_python", "web_search", "check_email"]}
        })
        names = [t["name"] for t in mcp_server.get_mcp_tools()]
        assert "web_search" not in names
        assert "check_email" not in names

    def test_input_schema_has_type_object(self):
        import mcp_server
        for tool in mcp_server.get_mcp_tools():
            schema = tool["inputSchema"]
            assert schema.get("type") == "object", (
                f"Tool '{tool['name']}' inputSchema type is '{schema.get('type')}', expected 'object'"
            )


# --- Tool execution ---

class TestCallTool:
    def test_routes_to_execute_tool(self, monkeypatch):
        import mcp_server
        import tools
        calls = []
        def fake_execute(name, tool_input, confirm_fn):
            calls.append((name, tool_input, confirm_fn))
            return "ok", False
        monkeypatch.setattr(tools, "execute_tool", fake_execute)
        text, is_error = asyncio.run(mcp_server.call_tool("web_search", {"query": "test"}))
        assert len(calls) == 1
        assert calls[0][0] == "web_search"
        assert calls[0][1] == {"query": "test"}
        assert calls[0][2] is None  # confirm_fn always None
        assert not is_error

    def test_blacklisted_tool_returns_error(self):
        import mcp_server
        text, is_error = asyncio.run(mcp_server.call_tool("run_python", {"code": "print(1)"}))
        assert is_error
        assert "blacklisted" in text.lower()

    def test_unknown_tool_returns_error(self, monkeypatch):
        import mcp_server
        import tools
        monkeypatch.setattr(tools, "execute_tool", lambda n, i, c: (f"Unknown tool: {n}", True))
        text, is_error = asyncio.run(mcp_server.call_tool("nonexistent_tool", {}))
        assert is_error
        assert "nonexistent_tool" in text

    def test_exception_caught_and_returned(self, monkeypatch):
        import mcp_server
        import tools
        def exploding_execute(name, tool_input, confirm_fn):
            raise RuntimeError("kaboom")
        monkeypatch.setattr(tools, "execute_tool", exploding_execute)
        text, is_error = asyncio.run(mcp_server.call_tool("web_search", {"query": "test"}))
        assert is_error
        assert "kaboom" in text


# --- Module-level ---

class TestErrorHandling:
    def test_mcp_available_is_bool(self):
        import mcp_server
        assert isinstance(mcp_server.MCP_AVAILABLE, bool)

    def test_get_mcp_tools_callable(self):
        import mcp_server
        assert callable(mcp_server.get_mcp_tools)

    def test_call_tool_callable(self):
        import mcp_server
        assert callable(mcp_server.call_tool)
