"""evcc Skill — live energy/charging data via REST API."""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Dict, List, Optional

from ..block import Block, Priority
from ..skill_connector import BaseSkill, SkillConfig

_DEFAULT_URL = "http://<server-ip>:7070"
_CACHE_TTL = 30


class EvccSkill(BaseSkill):
    """Injects live evcc energy and charging state.

    Params:
        url: evcc base URL (default: http://<server-ip>:7070)
    """

    def __init__(self) -> None:
        self._cached: Optional[Dict] = None
        self._cache_time: float = 0

    @property
    def name(self) -> str:
        return "evcc"

    @property
    def description(self) -> str:
        return "Live energy dashboard: solar, grid, battery, Tesla charging status from evcc."

    @property
    def context_hints(self) -> List[str]:
        return [
            "energy", "solar", "battery", "charging", "tesla", "wallbox",
            "grid", "power", "photovoltaic", "evcc", "car", "vehicle",
        ]

    def _fetch(self, url: str) -> Dict:
        now = time.time()
        if self._cached and now - self._cache_time < _CACHE_TTL:
            return self._cached
        req = urllib.request.Request(f"{url}/api/state")
        with urllib.request.urlopen(req, timeout=10) as resp:
            self._cached = json.loads(resp.read())
            self._cache_time = now
            return self._cached

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        url = config.params.get("url", _DEFAULT_URL)
        try:
            d = self._fetch(url)
        except Exception as exc:
            return [Block(content=f"## evcc\n\nConnection failed: {exc}", priority=Priority.LOW)]

        lp = d.get("loadpoints", [{}])[0]
        bat = d.get("battery", {})
        grid_power = d.get("grid", {}).get("power", 0)
        solar = d.get("pvPower", 0)
        home = d.get("homePower", 0)
        surplus = solar - home - max(0, bat.get("power", 0))
        green = d.get("greenShareHome", 0) * 100

        # Energy overview (HIGH)
        energy_lines = [
            "## Energy Status",
            "",
            f"Solar:    {solar:>6.0f} W",
            f"Grid:     {grid_power:>+7.0f} W  ({'Import' if grid_power > 0 else 'Export'})",
            f"Home:     {home:>6.0f} W",
            f"Battery:  {bat.get('soc', '?')}%  {bat.get('power', 0):>+7.0f} W",
            f"Surplus:  {surplus:>+7.0f} W",
            f"Green:    {green:>5.1f}%",
        ]
        blocks = [Block(content="\n".join(energy_lines), priority=Priority.HIGH)]

        # Car/charging block (MEDIUM if connected)
        connected = lp.get("connected", False)
        charging = lp.get("charging", False)
        car_soc = lp.get("vehicleSoc", 0)
        mode = lp.get("mode", "off")
        charge_power = lp.get("chargePower", 0)
        vehicle = lp.get("vehicleTitle", "")
        session_kwh = lp.get("sessionEnergy", 0) / 1000

        car_lines = [
            "## Tesla Charging",
            "",
            f"Vehicle:    {vehicle or '(not detected)'}",
            f"Connected:  {connected}",
            f"SOC:        {car_soc}%",
            f"Mode:       {mode}",
            f"Charging:   {charging}",
            f"Power:      {charge_power:.0f} W",
            f"Session:    {session_kwh:.2f} kWh",
        ]

        if connected:
            # Add recommendation
            if car_soc >= 95:
                car_lines.append("\nEmpfehlung: Auto fast voll — mode=off")
            elif surplus > 2000:
                car_lines.append("\nEmpfehlung: Starker Solarueberschuss — mode=pv")
            elif surplus > 700:
                car_lines.append("\nEmpfehlung: Moderater Ueberschuss — mode=pv oder minpv")
            elif solar > 500:
                car_lines.append("\nEmpfehlung: Etwas Solar — mode=minpv")
            else:
                car_lines.append("\nEmpfehlung: Wenig Solar — mode=now nur bei Bedarf")

        blocks.append(Block(
            content="\n".join(car_lines),
            priority=Priority.MEDIUM if connected else Priority.LOW,
        ))

        return blocks

    def propose_memory_changes(self, config: SkillConfig) -> List[Dict[str, Any]]:
        if not self._cached:
            return []
        d = self._cached
        lp = d.get("loadpoints", [{}])[0]
        bat = d.get("battery", {})
        solar = d.get("pvPower", 0)
        grid = d.get("grid", {}).get("power", 0)

        summary = (
            f"Solar: {solar:.0f}W | Grid: {grid:+.0f}W | "
            f"Battery: {bat.get('soc', '?')}% | "
            f"Car: {lp.get('vehicleSoc', '?')}% ({lp.get('mode', '?')})"
        )
        return [{
            "key": "evcc/snapshot",
            "value": summary,
            "tags": ["evcc", "energy", "snapshot"],
        }]
