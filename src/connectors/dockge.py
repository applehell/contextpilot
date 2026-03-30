"""Dockge connector — sync Docker Compose stacks from a Dockge stacks directory."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

COMPOSE_FILENAMES = ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")


class DockgeConnector(ConnectorPlugin):
    name = "dockge"
    display_name = "Dockge"
    description = "Sync Docker Compose stacks from a Dockge stacks directory"
    icon = "DK"
    category = "Infrastructure"
    setup_guide = "Point to the Dockge stacks directory (e.g. /opt/stacks). Each subdirectory is a stack with a compose.yml."
    color = "#86c800"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("stacks_dir", "Stacks directory", placeholder="/opt/stacks", required=True),
            ConfigField("dockge_url", "Dockge web UI URL (optional)", placeholder="http://192.168.1.78:5001"),
            ConfigField("include_env", "Include .env values (WARNING: may contain secrets)", type="boolean", default=False),
        ]

    @property
    def configured(self) -> bool:
        path = self._config.get("stacks_dir", "")
        return bool(path and Path(path).is_dir())

    def test_connection(self) -> Dict[str, Any]:
        path = self._config.get("stacks_dir", "")
        if not path:
            return {"ok": False, "error": "Stacks directory not set"}
        stacks_dir = Path(path)
        if not stacks_dir.is_dir():
            return {"ok": False, "error": f"Directory not found: {path}"}

        stacks = self._find_stacks(stacks_dir)
        if not stacks:
            return {"ok": False, "error": f"No compose files found in subdirectories of {path}"}

        return {"ok": True, "stacks_count": len(stacks), "stacks_dir": str(stacks_dir)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r

        result = SyncResult()
        stacks_dir = Path(self._config["stacks_dir"])
        dockge_url = (self._config.get("dockge_url") or "").rstrip("/")
        include_env = self._config.get("include_env", False)
        prefix = f"{self.name}/"

        stacks = self._find_stacks(stacks_dir)
        result.total_remote = len(stacks)
        synced_keys = set()

        for stack_name, compose_path in stacks:
            key = f"{prefix}{stack_name}"
            synced_keys.add(key)

            try:
                raw = compose_path.read_text(errors="replace")
            except Exception as e:
                result.errors.append(f"{stack_name}: {e}")
                continue

            env_data: Dict[str, str] = {}
            env_path = compose_path.parent / ".env"
            if env_path.is_file():
                try:
                    env_data = self._parse_env_file(env_path)
                except Exception:
                    pass

            try:
                compose = yaml.safe_load(raw) or {}
            except yaml.YAMLError as e:
                result.errors.append(f"{stack_name}: YAML parse error: {e}")
                continue

            content = self._format_stack(stack_name, compose, dockge_url, include_env, env_data)
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            services = compose.get("services", {})
            service_names = list(services.keys()) if isinstance(services, dict) else []
            mem_tags = [self.name, stack_name] + service_names

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
                        "stack_name": stack_name,
                        "compose_path": str(compose_path),
                        "service_count": len(service_names),
                    },
                    expires_at=self._compute_expires_at(),
                )
                store.set(mem)
                result.added += 1

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _find_stacks(self, stacks_dir: Path) -> List[tuple]:
        stacks = []
        try:
            entries = sorted(stacks_dir.iterdir())
        except PermissionError:
            return stacks

        for entry in entries:
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            for fname in COMPOSE_FILENAMES:
                compose_path = entry / fname
                if compose_path.is_file():
                    stacks.append((entry.name, compose_path))
                    break
        return stacks

    def _format_stack(self, name: str, compose: dict, dockge_url: str,
                      include_env: bool, env_data: Dict[str, str]) -> str:
        services = compose.get("services", {})
        if not isinstance(services, dict):
            services = {}

        parts = [f"# Stack: {name}"]
        parts.append(f"Services: {len(services)}")
        if dockge_url:
            parts.append(f"URL: {dockge_url}/#/compose/{name}")
        parts.append("")

        for svc_name, svc_cfg in services.items():
            if not isinstance(svc_cfg, dict):
                continue
            parts.append(f"## {svc_name}")
            image = svc_cfg.get("image", "")
            if image:
                parts.append(f"Image: {image}")

            ports = svc_cfg.get("ports", [])
            if ports:
                parts.append(f"Ports: {', '.join(str(p) for p in ports)}")

            volumes = svc_cfg.get("volumes", [])
            if volumes:
                parts.append(f"Volumes: {', '.join(str(v) for v in volumes)}")

            networks = svc_cfg.get("networks")
            if networks:
                if isinstance(networks, list):
                    parts.append(f"Networks: {', '.join(networks)}")
                elif isinstance(networks, dict):
                    parts.append(f"Networks: {', '.join(networks.keys())}")

            env = svc_cfg.get("environment")
            if env:
                parts.append("Environment:")
                if isinstance(env, dict):
                    for k, v in env.items():
                        val = str(v) if include_env else "***"
                        parts.append(f"  {k}={val}")
                elif isinstance(env, list):
                    for item in env:
                        item_str = str(item)
                        if "=" in item_str:
                            k, _, v = item_str.partition("=")
                            val = v if include_env else "***"
                            parts.append(f"  {k}={val}")
                        else:
                            parts.append(f"  {item_str}")

            env_file = svc_cfg.get("env_file")
            if env_file:
                files = env_file if isinstance(env_file, list) else [env_file]
                parts.append(f"Env files: {', '.join(str(f) for f in files)}")

            if env_data:
                parts.append("Env (.env file):")
                for k, v in env_data.items():
                    val = v if include_env else "***"
                    parts.append(f"  {k}={val}")

            restart = svc_cfg.get("restart", "")
            if restart:
                parts.append(f"Restart: {restart}")

            depends = svc_cfg.get("depends_on")
            if depends:
                if isinstance(depends, list):
                    parts.append(f"Depends on: {', '.join(depends)}")
                elif isinstance(depends, dict):
                    parts.append(f"Depends on: {', '.join(depends.keys())}")

            parts.append("")

        top_networks = compose.get("networks")
        if top_networks and isinstance(top_networks, dict):
            parts.append("## Networks")
            for net_name in top_networks:
                parts.append(f"- {net_name}")
            parts.append("")

        top_volumes = compose.get("volumes")
        if top_volumes and isinstance(top_volumes, dict):
            parts.append("## Volumes")
            for vol_name in top_volumes:
                parts.append(f"- {vol_name}")
            parts.append("")

        return "\n".join(parts).rstrip()

    @staticmethod
    def _parse_env_file(path: Path) -> Dict[str, str]:
        data = {}
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    data[k] = v
        return data
