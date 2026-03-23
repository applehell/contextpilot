#!/usr/bin/env python3
"""Unifi Skill — standalone script that connects to Context Pilot via MCP.

Usage:
    python scripts/skills/unifi_skill.py [--interval 60]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.mcp_client import call_mcp_tool_sync

UNIFI_URL = "https://192.168.1.1"
UNIFI_USER = "user"
UNIFI_PASS = "tipfif-xymzip-5vymnU"
SKILL_NAME = "unifi"
CP_MCP_SERVER = "context-pilot"
COOKIE_FILE = "/tmp/unifi_cookies.txt"


def unifi_login(url, user, pw):
    result = subprocess.run([
        "curl", "-s", "-k", "-X", "POST", f"{url}/api/auth/login",
        "-H", "Content-Type: application/json",
        "-c", COOKIE_FILE, "-D", "-",
        "-d", json.dumps({"username": user, "password": pw}),
    ], capture_output=True, text=True, timeout=10)
    for line in result.stdout.splitlines():
        if line.lower().startswith("x-csrf-token:") and "x-updated" not in line.lower():
            return line.split(":", 1)[1].strip()
    return None


def unifi_get(url, path, csrf):
    result = subprocess.run([
        "curl", "-s", "-k", f"{url}{path}",
        "-b", COOKIE_FILE, "-H", f"X-Csrf-Token: {csrf}",
    ], capture_output=True, text=True, timeout=10)
    try:
        return json.loads(result.stdout).get("data", [])
    except (json.JSONDecodeError, AttributeError):
        return []


def register():
    result = call_mcp_tool_sync(CP_MCP_SERVER, "register_skill", {
        "name": SKILL_NAME,
        "description": "Network status: clients, APs, WLANs from Unifi Dream Machine SE",
        "context_hints": ["network", "wifi", "wlan", "client", "device", "unifi", "access point"],
    })
    print(f"Registered: {result}")


def push_data(url, user, pw):
    csrf = unifi_login(url, user, pw)
    if not csrf:
        print("Login failed")
        return

    clients = unifi_get(url, "/proxy/network/api/s/default/stat/sta", csrf)
    devices = unifi_get(url, "/proxy/network/api/s/default/stat/device", csrf)

    summary = f"Network: {len(devices)} devices, {len(clients)} clients online\n"

    # Group clients by SSID
    by_ssid = {}
    for c in clients:
        ssid = c.get("essid", "wired")
        by_ssid.setdefault(ssid, []).append(c)
    for ssid, ssid_clients in sorted(by_ssid.items()):
        names = [c.get("name", c.get("hostname", "?")) for c in ssid_clients[:5]]
        summary += f"  {ssid}: {len(ssid_clients)} clients ({', '.join(names)})\n"

    # Device status
    for d in devices:
        name = d.get("name", d.get("model", "?"))
        state = "UP" if d.get("state", 0) == 1 else "DOWN"
        summary += f"  {name}: {state}\n"

    call_mcp_tool_sync(CP_MCP_SERVER, "memory_set", {
        "key": "unifi/live",
        "value": summary,
        "tags": ["unifi", "network", "live"],
    })
    call_mcp_tool_sync(CP_MCP_SERVER, "heartbeat", {"name": SKILL_NAME})
    print(f"[{time.strftime('%H:%M:%S')}] Pushed: {len(clients)} clients, {len(devices)} devices")


def main():
    parser = argparse.ArgumentParser(description="Unifi skill for Context Pilot")
    parser.add_argument("--interval", type=int, default=60, help="Update interval in seconds")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    register()

    if args.once:
        push_data(UNIFI_URL, UNIFI_USER, UNIFI_PASS)
        return

    print(f"Running every {args.interval}s — Ctrl+C to stop")
    while True:
        try:
            push_data(UNIFI_URL, UNIFI_USER, UNIFI_PASS)
        except Exception as exc:
            print(f"Error: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
