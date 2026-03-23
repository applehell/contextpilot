"""Unifi Skill — network status via UniFi OS REST API."""
from __future__ import annotations

import json
import subprocess
import time
from typing import Any, Dict, List, Optional

from ..block import Block, Priority
from ..skill_connector import BaseSkill, SkillConfig

_DEFAULT_URL = "https://192.168.1.1"
_DEFAULT_USER = "user"
_DEFAULT_PASS = "tipfif-xymzip-5vymnU"
_COOKIE_FILE = "/tmp/unifi_cookies.txt"
_CACHE_TTL = 60


def _unifi_login(url: str, username: str, password: str) -> Optional[str]:
    """Login and return CSRF token."""
    result = subprocess.run([
        "curl", "-s", "-k", "-X", "POST", f"{url}/api/auth/login",
        "-H", "Content-Type: application/json",
        "-c", _COOKIE_FILE, "-D", "-",
        "-d", json.dumps({"username": username, "password": password}),
    ], capture_output=True, text=True, timeout=10)
    for line in result.stdout.splitlines():
        if line.lower().startswith("x-csrf-token:") and "x-updated" not in line.lower():
            return line.split(":", 1)[1].strip()
    return None


def _unifi_get(url: str, path: str, csrf: str) -> List[Dict]:
    """GET request to UniFi API."""
    result = subprocess.run([
        "curl", "-s", "-k", f"{url}{path}",
        "-b", _COOKIE_FILE,
        "-H", f"X-Csrf-Token: {csrf}",
    ], capture_output=True, text=True, timeout=10)
    try:
        return json.loads(result.stdout).get("data", [])
    except (json.JSONDecodeError, AttributeError):
        return []


class UnifiSkill(BaseSkill):
    """Injects live Unifi network status.

    Params:
        url: Controller URL (default: https://192.168.1.1)
        username: Login user (default: user)
        password: Login password
    """

    def __init__(self) -> None:
        self._cached_data: Optional[Dict[str, Any]] = None
        self._cache_time: float = 0

    @property
    def name(self) -> str:
        return "unifi"

    @property
    def description(self) -> str:
        return "Live network status: clients, APs, WLANs, and device health from Unifi Dream Machine SE."

    @property
    def context_hints(self) -> List[str]:
        return [
            "network", "wifi", "wlan", "client", "device", "unifi",
            "access point", "switch", "bandwidth", "internet", "vpn",
        ]

    def _fetch(self, url: str, username: str, password: str) -> Dict[str, Any]:
        now = time.time()
        if self._cached_data and now - self._cache_time < _CACHE_TTL:
            return self._cached_data

        csrf = _unifi_login(url, username, password)
        if not csrf:
            raise ConnectionError("Unifi login failed — no CSRF token")

        data: Dict[str, Any] = {}
        data["devices"] = _unifi_get(url, "/proxy/network/api/s/default/stat/device", csrf)
        data["clients"] = _unifi_get(url, "/proxy/network/api/s/default/stat/sta", csrf)
        data["wlans"] = _unifi_get(url, "/proxy/network/api/s/default/rest/wlanconf", csrf)
        data["health"] = _unifi_get(url, "/proxy/network/api/s/default/stat/health", csrf)

        self._cached_data = data
        self._cache_time = now
        return data

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        url = config.params.get("url", _DEFAULT_URL)
        username = config.params.get("username", _DEFAULT_USER)
        password = config.params.get("password", _DEFAULT_PASS)

        try:
            data = self._fetch(url, username, password)
        except Exception as exc:
            return [Block(content=f"## Unifi Network\n\nConnection failed: {exc}", priority=Priority.LOW)]

        blocks: List[Block] = []

        # Overview (HIGH)
        devices = data.get("devices", [])
        clients = data.get("clients", [])
        wlans = data.get("wlans", [])

        overview_lines = [
            "## Unifi Network Overview",
            "",
            f"Devices: {len(devices)} | Clients: {len(clients)} | WLANs: {len(wlans)}",
        ]

        # Health summary
        for h in data.get("health", []):
            subsystem = h.get("subsystem", "")
            status = h.get("status", "")
            if subsystem in ("www", "wan", "lan", "wlan"):
                overview_lines.append(f"  {subsystem}: {status}")

        blocks.append(Block(content="\n".join(overview_lines), priority=Priority.HIGH))

        # Devices (MEDIUM)
        if devices:
            dev_lines = ["### Network Devices", ""]
            for d in devices:
                name = d.get("name", d.get("model", "?"))
                model = d.get("model", "")
                ip = d.get("ip", "?")
                status = "UP" if d.get("state", 0) == 1 else "DOWN"
                uptime_h = d.get("uptime", 0) / 3600
                dev_lines.append(f"- {name} ({model}) — {ip} [{status}] uptime: {uptime_h:.0f}h")
            blocks.append(Block(content="\n".join(dev_lines), priority=Priority.MEDIUM))

        # Active clients (LOW, compressed)
        if clients:
            # Group by network
            wired = [c for c in clients if not c.get("is_wired") is False and not c.get("essid")]
            wireless = [c for c in clients if c.get("essid")]

            client_lines = [f"### Active Clients ({len(clients)} total)", ""]

            # Top wireless clients by network
            by_ssid: Dict[str, List] = {}
            for c in wireless:
                ssid = c.get("essid", "?")
                by_ssid.setdefault(ssid, []).append(c)

            for ssid, ssid_clients in sorted(by_ssid.items()):
                client_lines.append(f"**{ssid}** ({len(ssid_clients)} clients):")
                for c in ssid_clients[:10]:
                    name = c.get("name", c.get("hostname", c.get("mac", "?")))
                    ip = c.get("ip", "?")
                    signal = c.get("signal", 0)
                    client_lines.append(f"  - {name}: {ip} (signal: {signal}dBm)")
                if len(ssid_clients) > 10:
                    client_lines.append(f"  ... +{len(ssid_clients) - 10} more")
                client_lines.append("")

            if wired:
                client_lines.append(f"**Wired** ({len(wired)} clients):")
                for c in wired[:10]:
                    name = c.get("name", c.get("hostname", c.get("mac", "?")))
                    ip = c.get("ip", "?")
                    client_lines.append(f"  - {name}: {ip}")

            blocks.append(Block(
                content="\n".join(client_lines),
                priority=Priority.LOW,
                compress_hint="bullet_extract",
            ))

        return blocks

    def propose_memory_changes(self, config: SkillConfig) -> List[Dict[str, Any]]:
        if not self._cached_data:
            return []
        devices = len(self._cached_data.get("devices", []))
        clients = len(self._cached_data.get("clients", []))
        return [{
            "key": "unifi/snapshot",
            "value": f"Network: {devices} devices, {clients} clients online",
            "tags": ["unifi", "network", "snapshot"],
        }]
