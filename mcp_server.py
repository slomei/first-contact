"""
MCP (Model Context Protocol) server for First Contact.

Exposes core tools to external MCP clients (Claude Desktop, Cursor, etc.)
over stdio transport. Reads tools from the existing tool registry and plugin
system without modifying them.

Usage:
    python mcp_server.py

Configure in config.json:
    "mcp": {
        "blacklist": ["run_python"],
        "server_name": "first-contact",
        "server_version": "1.0.0"
    }
"""

from dotenv import load_dotenv
load_dotenv()

import asyncio
import logging
import os
import sys

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

import memory

# --- Config ---

MCP_DEFAULTS = {
    "blacklist": ["run_python"],
    "server_name": "first-contact",
    "server_version": "1.0.0",
}


def _get_mcp_config():
    """Load MCP config, merging defaults for missing keys."""
    cfg = memory.load_config().get("mcp", {})
    merged = dict(MCP_DEFAULTS)
    merged.update(cfg)
    return merged


# --- Tool translation (testable without MCP SDK) ---

def get_mcp_tools():
    """Return core + plugin tools translated for MCP (no cache_control, blacklist filtered).

    Each tool is a dict with 'name', 'description', 'inputSchema'.
    """
    import tools
    try:
        import plugins
        plugin_tools = plugins.get_all_plugin_tools()
    except Exception:
        plugin_tools = []

    blacklist = set(_get_mcp_config().get("blacklist", []))

    mcp_tools = []
    for tool_def in list(tools.TOOLS) + list(plugin_tools):
        name = tool_def.get("name")
        if not name or name in blacklist:
            continue
        mcp_tools.append({
            "name": name,
            "description": tool_def.get("description", ""),
            "inputSchema": tool_def.get("input_schema", {"type": "object", "properties": {}}),
        })
    return mcp_tools


# --- Tool execution bridge ---

async def call_tool(name, arguments):
    """Execute a tool via the existing tools.execute_tool, returning (text, is_error).

    Runs execute_tool in a thread to avoid blocking the async event loop.
    confirm_fn=None means auto-approve (same as daemon usage).
    """
    blacklist = set(_get_mcp_config().get("blacklist", []))
    if name in blacklist:
        return f"Tool '{name}' is blacklisted in MCP config.", True

    import tools
    try:
        result, is_error = await asyncio.to_thread(
            tools.execute_tool, name, arguments, None
        )
        return str(result), is_error
    except Exception as e:
        return f"Tool execution error: {e}", True


# --- MCP server ---

async def run_server():
    """Start the MCP server over stdio transport."""
    if not MCP_AVAILABLE:
        print("Error: mcp package not installed. Install with: pip install mcp", file=sys.stderr)
        sys.exit(1)

    # Logging to stderr only — stdout is the JSON-RPC transport
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("mcp_server")

    cfg = _get_mcp_config()
    server = Server(cfg["server_name"])

    @server.list_tools()
    async def handle_list_tools():
        tool_dicts = get_mcp_tools()
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in tool_dicts
        ]

    @server.call_tool()
    async def handle_call_tool(name: str, arguments: dict):
        log.info("Tool call: %s", name)
        text, is_error = await call_tool(name, arguments or {})
        return [TextContent(type="text", text=text, isError=is_error)]

    log.info("Starting First Contact MCP server (tools: %d)", len(get_mcp_tools()))
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(run_server())
