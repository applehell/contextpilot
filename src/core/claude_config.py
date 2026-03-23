"""Claude Code config helper — register/deregister MCP server in ~/.claude.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

CLAUDE_CONFIG = Path.home() / ".claude.json"
MCP_NAME = "context-pilot"
DEFAULT_PORT = 8400


def _load_config() -> dict:
    if not CLAUDE_CONFIG.exists():
        return {}
    return json.loads(CLAUDE_CONFIG.read_text())


def _save_config(config: dict) -> None:
    CLAUDE_CONFIG.write_text(json.dumps(config, indent=2))


def register_mcp(port: int = DEFAULT_PORT, transport: str = "sse") -> None:
    """Register the Context Pilot MCP server in ~/.claude.json as an SSE server."""
    config = _load_config()
    servers = config.setdefault("mcpServers", {})

    if transport == "sse":
        servers[MCP_NAME] = {
            "type": "sse",
            "url": f"http://localhost:{port}/sse",
        }
    elif transport == "streamable-http":
        servers[MCP_NAME] = {
            "type": "url",
            "url": f"http://localhost:{port}/mcp",
        }

    _save_config(config)


def deregister_mcp() -> None:
    """Remove the Context Pilot MCP server from ~/.claude.json."""
    config = _load_config()
    servers = config.get("mcpServers", {})

    if MCP_NAME in servers:
        del servers[MCP_NAME]
        _save_config(config)


def is_registered() -> bool:
    """Check if Context Pilot MCP is currently registered."""
    config = _load_config()
    return MCP_NAME in config.get("mcpServers", {})


def get_current_config() -> Optional[dict]:
    """Get the current MCP config entry for Context Pilot."""
    config = _load_config()
    return config.get("mcpServers", {}).get(MCP_NAME)


def remove_stdio_entry() -> bool:
    """Remove any stdio-based Context Pilot entry (the old auto-start config)."""
    config = _load_config()
    servers = config.get("mcpServers", {})
    entry = servers.get(MCP_NAME)
    if entry and entry.get("type") == "stdio":
        del servers[MCP_NAME]
        _save_config(config)
        return True
    return False
