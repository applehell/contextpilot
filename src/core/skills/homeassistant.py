"""Home Assistant Skill — connects via MCP to inject live HA state as context blocks."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from ..block import Block, Priority
from ..mcp_client import call_mcp_tool_sync, list_mcp_tools_sync
from ..skill_connector import BaseSkill, SkillConfig

_MCP_SERVER = "homeassistant"
_CACHE_TTL = 30  # seconds


class HomeAssistantSkill(BaseSkill):
    """Injects live Home Assistant state via MCP.

    Connects to the HA MCP server configured in ~/.claude.json
    and calls GetLiveContext for a full state overview.

    Params:
        mcp_server: MCP server name (default: 'homeassistant')
        domains: Comma-separated domain filter (default: all)
        max_lines: Max lines per domain block (default: 50)
    """

    def __init__(self) -> None:
        self._context: List[Block] = []
        self._cached_data: Optional[str] = None
        self._cached_tools: Optional[List[Dict]] = None
        self._cache_time: float = 0

    @property
    def name(self) -> str:
        return "homeassistant"

    @property
    def description(self) -> str:
        return "Live Home Assistant state via MCP (GetLiveContext, device control, automations)."

    @property
    def context_hints(self) -> List[str]:
        return [
            "home assistant", "smart home", "automation", "sensor",
            "temperature", "climate", "light", "switch", "person",
            "energy", "power", "device", "entity", "state",
        ]

    def receive_context(self, blocks: List[Block]) -> None:
        self._context = blocks

    def _fetch_live_context(self, server: str) -> str:
        """Fetch live context from HA MCP, with caching."""
        now = time.time()
        if self._cached_data and now - self._cache_time < _CACHE_TTL:
            return self._cached_data

        raw = call_mcp_tool_sync(server, "GetLiveContext", timeout=15)
        self._cached_data = raw
        self._cache_time = now
        return raw

    def _fetch_tools(self, server: str) -> List[Dict]:
        """Fetch available MCP tools, cached."""
        if self._cached_tools is not None:
            return self._cached_tools
        self._cached_tools = list_mcp_tools_sync(server, timeout=10)
        return self._cached_tools

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        server = config.params.get("mcp_server", _MCP_SERVER)
        domains_filter = config.params.get("domains", "")
        max_lines = int(config.params.get("max_lines", "50"))

        # Fetch live context via MCP
        try:
            raw = self._fetch_live_context(server)
        except Exception as exc:
            return [Block(
                content=f"## Home Assistant (MCP)\n\nConnection failed: {exc}",
                priority=Priority.LOW,
            )]

        # Parse the response — may be JSON wrapped or plain YAML
        context_text = raw
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "result" in parsed:
                context_text = parsed["result"]
        except (json.JSONDecodeError, TypeError):
            pass

        if not context_text:
            return [Block(content="## Home Assistant\n\n(no data)", priority=Priority.LOW)]

        # Split into domain sections
        blocks = self._parse_context_to_blocks(context_text, domains_filter, max_lines)

        # Add available tools block
        try:
            tools = self._fetch_tools(server)
            tool_lines = ["## HA MCP Tools", ""]
            for t in tools:
                tool_lines.append(f"- **{t['name']}**: {t['description'][:80]}")
            blocks.append(Block(
                content="\n".join(tool_lines),
                priority=Priority.LOW,
                compress_hint="bullet_extract",
            ))
        except Exception:
            pass

        return blocks

    def _parse_context_to_blocks(
        self, text: str, domains_filter: str, max_lines: int,
    ) -> List[Block]:
        """Parse GetLiveContext YAML output into structured blocks per area/domain."""
        allowed = {d.strip() for d in domains_filter.split(",") if d.strip()} if domains_filter else None

        # Group entries by area
        areas: Dict[str, List[str]] = {}
        current_entry_lines: List[str] = []

        for line in text.splitlines():
            if line.startswith("- names:"):
                if current_entry_lines:
                    self._assign_entry(areas, current_entry_lines, allowed)
                current_entry_lines = [line]
            elif current_entry_lines:
                current_entry_lines.append(line)
            elif line.strip():
                # Header text before first entry
                areas.setdefault("_overview", []).append(line)

        if current_entry_lines:
            self._assign_entry(areas, current_entry_lines, allowed)

        # Build blocks
        blocks: List[Block] = []

        # Overview block
        overview_lines = areas.pop("_overview", [])
        if overview_lines:
            blocks.append(Block(
                content="## Home Assistant Live Context\n\n" + "\n".join(overview_lines[:5]),
                priority=Priority.HIGH,
            ))

        # Area blocks
        for area, lines in sorted(areas.items()):
            if not lines:
                continue
            truncated = lines[:max_lines]
            content = f"### {area}\n\n" + "\n".join(truncated)
            if len(lines) > max_lines:
                content += f"\n... +{len(lines) - max_lines} more devices"

            # Higher priority for climate/person areas
            priority = Priority.MEDIUM if any(
                kw in area.lower() for kw in ["wohn", "schlaf", "büro", "küche"]
            ) else Priority.LOW

            blocks.append(Block(
                content=content,
                priority=priority,
                compress_hint="bullet_extract",
            ))

        if not blocks:
            # Fallback: raw text as single block
            blocks.append(Block(
                content=f"## Home Assistant\n\n{text[:2000]}",
                priority=Priority.MEDIUM,
            ))

        return blocks

    def _assign_entry(
        self,
        areas: Dict[str, List[str]],
        entry_lines: List[str],
        allowed_domains: Optional[set],
    ) -> None:
        """Parse a YAML entry and assign it to the right area bucket."""
        name = ""
        domain = ""
        state = ""
        area = "Unbekannt"

        for line in entry_lines:
            stripped = line.strip()
            if stripped.startswith("- names:"):
                name = stripped.replace("- names:", "").strip().strip("'\"")
            elif stripped.startswith("domain:"):
                domain = stripped.replace("domain:", "").strip()
            elif stripped.startswith("state:"):
                state = stripped.replace("state:", "").strip().strip("'\"")
            elif stripped.startswith("areas:"):
                area = stripped.replace("areas:", "").strip()

        if allowed_domains and domain not in allowed_domains:
            return

        # Skip unavailable entities
        if state in ("unavailable", "unknown", ""):
            return

        display = f"- {name} ({domain}): {state}"
        areas.setdefault(area, []).append(display)

    def propose_memory_changes(self, config: SkillConfig) -> List[Dict[str, Any]]:
        """Propose a state snapshot memory from the last fetch."""
        if not self._cached_data:
            return []

        context_text = self._cached_data
        try:
            parsed = json.loads(self._cached_data)
            if isinstance(parsed, dict) and "result" in parsed:
                context_text = parsed["result"]
        except (json.JSONDecodeError, TypeError):
            pass

        # Count entities per domain
        domains: Dict[str, int] = {}
        for line in context_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("domain:"):
                d = stripped.replace("domain:", "").strip()
                domains[d] = domains.get(d, 0) + 1

        total = sum(domains.values())
        summary = f"HA MCP Live Context: {total} devices\n"
        summary += ", ".join(f"{k}({v})" for k, v in sorted(domains.items()))

        return [{
            "key": "ha/mcp-snapshot",
            "value": summary,
            "tags": ["homeassistant", "mcp", "snapshot"],
        }]
