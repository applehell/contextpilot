#!/usr/bin/env python3
"""evcc Skill — standalone script that connects to Context Pilot via MCP.

Usage:
    python scripts/skills/evcc_skill.py [--interval 30] [--budget 2000]

Registers with Context Pilot MCP Server, fetches energy data from evcc,
and writes it as memories + blocks.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.mcp_client import call_mcp_tool_sync

EVCC_URL = "http://<server-ip>:7070"
SKILL_NAME = "evcc"
CP_MCP_SERVER = "context-pilot"  # must be configured in ~/.claude.json


def fetch_evcc_state(url: str) -> dict:
    req = urllib.request.Request(f"{url}/api/state")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def register():
    result = call_mcp_tool_sync(CP_MCP_SERVER, "register_skill", {
        "name": SKILL_NAME,
        "description": "Live energy data: solar, grid, battery, Tesla charging from evcc",
        "context_hints": ["energy", "solar", "battery", "charging", "tesla", "wallbox", "grid", "power"],
    })
    print(f"Registered: {result}")


def push_data(url: str):
    d = fetch_evcc_state(url)
    lp = d.get("loadpoints", [{}])[0]
    bat = d.get("battery", {})
    grid = d.get("grid", {}).get("power", 0)
    solar = d.get("pvPower", 0)
    home = d.get("homePower", 0)
    surplus = solar - home - max(0, bat.get("power", 0))
    green = d.get("greenShareHome", 0) * 100

    summary = (
        f"Solar: {solar:.0f}W | Grid: {grid:+.0f}W | "
        f"Battery: {bat.get('soc', '?')}% ({bat.get('power', 0):+.0f}W) | "
        f"Home: {home:.0f}W | Surplus: {surplus:+.0f}W | Green: {green:.0f}%\n"
        f"Car: {lp.get('vehicleTitle', '?')} SOC={lp.get('vehicleSoc', '?')}% "
        f"Mode={lp.get('mode', '?')} Charging={lp.get('charging', False)} "
        f"Power={lp.get('chargePower', 0):.0f}W"
    )

    # Write as memory
    call_mcp_tool_sync(CP_MCP_SERVER, "memory_set", {
        "key": "evcc/live",
        "value": summary,
        "tags": ["evcc", "energy", "live"],
    })

    # Heartbeat
    call_mcp_tool_sync(CP_MCP_SERVER, "heartbeat", {"name": SKILL_NAME})

    print(f"[{time.strftime('%H:%M:%S')}] Pushed: {summary[:80]}...")


def main():
    parser = argparse.ArgumentParser(description="evcc skill for Context Pilot")
    parser.add_argument("--interval", type=int, default=30, help="Update interval in seconds")
    parser.add_argument("--url", default=EVCC_URL, help="evcc URL")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    register()

    if args.once:
        push_data(args.url)
        return

    print(f"Running every {args.interval}s — Ctrl+C to stop")
    while True:
        try:
            push_data(args.url)
        except Exception as exc:
            print(f"Error: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
