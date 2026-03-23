"""MCP Client — connects to MCP servers for skill data retrieval.

Reads server configurations from ~/.claude.json and provides
async tool calling for any registered MCP server.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def load_mcp_servers() -> Dict[str, Dict[str, Any]]:
    """Load MCP server configs from ~/.claude.json."""
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return {}
    try:
        data = json.loads(claude_json.read_text(encoding="utf-8"))
        return data.get("mcpServers", {})
    except (json.JSONDecodeError, OSError):
        return {}


async def call_mcp_tool(
    server_name: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    timeout: float = 15,
) -> str:
    """Call a tool on an MCP server and return the text result.

    Supports 'http' type servers (streamable HTTP / SSE).
    """
    servers = load_mcp_servers()
    server_cfg = servers.get(server_name)
    if not server_cfg:
        raise ConnectionError(f"MCP server '{server_name}' not configured in ~/.claude.json")

    server_type = server_cfg.get("type", "")
    if server_type != "http":
        raise ValueError(f"Unsupported MCP server type '{server_type}' — only 'http' is supported")

    url = server_cfg["url"]
    headers = server_cfg.get("headers", {})

    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    async with streamablehttp_client(url=url, headers=headers, timeout=timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments or {})
            parts = []
            for content in result.content:
                if hasattr(content, "text"):
                    parts.append(content.text)
                else:
                    parts.append(str(content))
            return "\n".join(parts)


async def list_mcp_tools(server_name: str, timeout: float = 10) -> List[Dict[str, str]]:
    """List available tools on an MCP server."""
    servers = load_mcp_servers()
    server_cfg = servers.get(server_name)
    if not server_cfg:
        raise ConnectionError(f"MCP server '{server_name}' not configured")

    if server_cfg.get("type") != "http":
        raise ValueError(f"Unsupported MCP server type")

    url = server_cfg["url"]
    headers = server_cfg.get("headers", {})

    from mcp.client.streamable_http import streamablehttp_client
    from mcp import ClientSession

    async with streamablehttp_client(url=url, headers=headers, timeout=timeout) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            return [{"name": t.name, "description": t.description or ""} for t in tools.tools]


def call_mcp_tool_sync(
    server_name: str,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    timeout: float = 15,
) -> str:
    """Synchronous wrapper around call_mcp_tool for use in non-async contexts."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an async context (e.g. Qt event loop) — use a thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, call_mcp_tool(server_name, tool_name, arguments, timeout))
            return future.result(timeout=timeout + 5)
    else:
        return asyncio.run(call_mcp_tool(server_name, tool_name, arguments, timeout))


def list_mcp_tools_sync(server_name: str, timeout: float = 10) -> List[Dict[str, str]]:
    """Synchronous wrapper around list_mcp_tools."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, list_mcp_tools(server_name, timeout))
            return future.result(timeout=timeout + 5)
    else:
        return asyncio.run(list_mcp_tools(server_name, timeout))
