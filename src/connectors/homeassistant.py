"""Home Assistant connector — sync automations, entities, and scenes."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


class _HAAPI:
    def __init__(self, url: str, token: str) -> None:
        self.base_url = url.rstrip("/")
        self.token = token

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(f"{self.base_url}{path}", headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def config(self) -> Dict:
        return self._get("/api/config")

    def states(self) -> List[Dict]:
        return self._get("/api/states")

    def services(self) -> List[Dict]:
        return self._get("/api/services")

    def automations(self) -> List[Dict]:
        states = self.states()
        return [s for s in states if s["entity_id"].startswith("automation.")]

    def scenes(self) -> List[Dict]:
        states = self.states()
        return [s for s in states if s["entity_id"].startswith("scene.")]

    def scripts(self) -> List[Dict]:
        states = self.states()
        return [s for s in states if s["entity_id"].startswith("script.")]


class HomeAssistantConnector(ConnectorPlugin):
    name = "homeassistant"
    display_name = "Home Assistant"
    description = "Sync automations, scenes, and entity states from Home Assistant"
    icon = "H"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("url", "URL", placeholder="http://<server-ip>:8123", required=True),
            ConfigField("token", "Long-Lived Access Token", type="password", required=True),
            ConfigField("sync_types", "Sync types", type="tags",
                        placeholder="automations, scenes, scripts (empty = all)", default="automations, scenes, scripts"),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("url") and self._config.get("token"))

    def _api(self) -> _HAAPI:
        return _HAAPI(self._config["url"], self._config["token"])

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        try:
            api = self._api()
            cfg = api.config()
            states = api.states()
            return {
                "ok": True,
                "location": cfg.get("location_name", ""),
                "version": cfg.get("version", ""),
                "entity_count": len(states),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r

        result = SyncResult()
        api = self._api()
        prefix = f"{self.name}/"

        sync_types = self._config.get("sync_types", "automations, scenes, scripts")
        if isinstance(sync_types, str):
            types = [t.strip().lower() for t in sync_types.split(",") if t.strip()]
        else:
            types = [t.lower() for t in sync_types]
        if not types:
            types = ["automations", "scenes", "scripts"]

        synced_keys = set()

        try:
            items = []
            if "automations" in types:
                items.extend(("automation", a) for a in api.automations())
            if "scenes" in types:
                items.extend(("scene", s) for s in api.scenes())
            if "scripts" in types:
                items.extend(("script", s) for s in api.scripts())
            result.total_remote = len(items)
        except Exception as e:
            result.errors.append(f"API error: {e}")
            return result

        for item_type, state in items:
            entity_id = state["entity_id"]
            key = f"{prefix}{entity_id}"
            synced_keys.add(key)

            friendly_name = state.get("attributes", {}).get("friendly_name", entity_id)
            attrs = state.get("attributes", {})
            state_val = state.get("state", "")

            content_parts = [f"# {friendly_name}", f"Entity: {entity_id}", f"State: {state_val}"]
            if "last_triggered" in attrs:
                content_parts.append(f"Last triggered: {attrs['last_triggered']}")
            if "current" in attrs:
                content_parts.append(f"Mode: {attrs['current']}")

            # Include relevant attributes
            skip_attrs = {"friendly_name", "last_triggered", "current", "icon", "supported_features"}
            for k, v in attrs.items():
                if k not in skip_attrs and not k.startswith("_"):
                    content_parts.append(f"{k}: {v}")

            content = "\n".join(content_parts)
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            mem_tags = [self.name, item_type]
            area = attrs.get("area", "")
            if area:
                mem_tags.append(area.lower())

            try:
                existing = store.get(key)
                if existing.metadata.get("content_hash") == content_hash:
                    result.skipped += 1
                    continue
                existing.value = content
                existing.tags = mem_tags
                existing.metadata["content_hash"] = content_hash
                existing.updated_at = time.time()
                store.set(existing)
                result.updated += 1
            except KeyError:
                mem = Memory(
                    key=key, value=content, tags=mem_tags,
                    metadata={
                        "source": self.name,
                        "content_hash": content_hash,
                        "entity_id": entity_id,
                        "entity_type": item_type,
                        "friendly_name": friendly_name,
                    },
                )
                store.set(mem)
                result.added += 1

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result
