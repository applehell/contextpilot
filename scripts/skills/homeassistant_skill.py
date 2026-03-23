#!/usr/bin/env python3
"""Home Assistant Skill — standalone script that connects to Context Pilot via MCP.

Usage:
    python scripts/skills/homeassistant_skill.py [--interval 30]

Connects to HA via its MCP server, fetches GetLiveContext,
and pushes the data to Context Pilot as memories.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.mcp_client import call_mcp_tool_sync

SKILL_NAME = "homeassistant"
HA_MCP_SERVER = "homeassistant"  # from ~/.claude.json
CP_MCP_SERVER = "context-pilot"  # Context Pilot MCP server


def register():
    result = call_mcp_tool_sync(CP_MCP_SERVER, "register_skill", {
        "name": SKILL_NAME,
        "description": "Live Home Assistant state: devices, areas, automations, persons",
        "context_hints": [
            "home assistant", "smart home", "automation", "sensor",
            "temperature", "climate", "light", "switch", "person", "energy",
        ],
    })
    print(f"Registered: {result}")


def push_data():
    # Fetch from HA via its own MCP server
    raw = call_mcp_tool_sync(HA_MCP_SERVER, "GetLiveContext", timeout=15)

    # Parse
    context_text = raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "result" in parsed:
            context_text = parsed["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Count entities
    domains = {}
    for line in context_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("domain:"):
            d = stripped.replace("domain:", "").strip()
            domains[d] = domains.get(d, 0) + 1

    total = sum(domains.values())
    summary = f"HA Live: {total} devices\n"
    summary += ", ".join(f"{k}({v})" for k, v in sorted(domains.items()))

    # Push full context as memory
    call_mcp_tool_sync(CP_MCP_SERVER, "memory_set", {
        "key": "ha/live-context",
        "value": context_text[:5000],  # truncate for memory
        "tags": ["homeassistant", "live"],
    })

    # Push summary
    call_mcp_tool_sync(CP_MCP_SERVER, "memory_set", {
        "key": "ha/summary",
        "value": summary,
        "tags": ["homeassistant", "summary"],
    })

    call_mcp_tool_sync(CP_MCP_SERVER, "heartbeat", {"name": SKILL_NAME})
    print(f"[{time.strftime('%H:%M:%S')}] Pushed: {total} devices across {len(domains)} domains")


def main():
    parser = argparse.ArgumentParser(description="Home Assistant skill for Context Pilot")
    parser.add_argument("--interval", type=int, default=30, help="Update interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    register()

    if args.once:
        push_data()
        return

    print(f"Running every {args.interval}s — Ctrl+C to stop")
    while True:
        try:
            push_data()
        except Exception as exc:
            print(f"Error: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
