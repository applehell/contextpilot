"""Base class for all connector plugins."""
from __future__ import annotations

import json
import os
import stat
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.memory import MemoryStore

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))


@dataclass
class ConfigField:
    """Describes a configuration field for the UI."""
    name: str
    label: str
    type: str = "text"          # text, password, tags, boolean, number
    placeholder: str = ""
    required: bool = False
    default: Any = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "placeholder": self.placeholder,
            "required": self.required,
            "default": self.default,
        }


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    total_remote: int = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "added": self.added,
            "updated": self.updated,
            "removed": self.removed,
            "skipped": self.skipped,
            "total_remote": self.total_remote,
            "errors": self.errors,
        }


class ConnectorPlugin(ABC):
    """Base class for connector plugins. Drop a subclass into src/connectors/ and it gets auto-discovered."""

    name: str = ""              # unique ID, e.g. "paperless"
    display_name: str = ""      # e.g. "Paperless-ngx"
    description: str = ""       # short description for the UI
    icon: str = ""              # emoji or short label
    category: str = "Other"     # "Development", "Documents", "Smart Home", "Communication", "Knowledge"
    setup_guide: str = ""       # how to get credentials/tokens
    color: str = ""             # CSS accent color for store card

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir or _DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self._data_dir / f"connector_{self.name}.json"
        self._config: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._config_path.exists():
            return json.loads(self._config_path.read_text())
        return {}

    def _save(self) -> None:
        self._config_path.write_text(json.dumps(self._config, indent=2))
        try:
            self._config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # Docker volumes may not support chmod

    @property
    def configured(self) -> bool:
        return bool(self._config.get("_configured"))

    @property
    def enabled(self) -> bool:
        return self._config.get("_enabled", True)

    @property
    def ttl_days(self) -> Optional[int]:
        val = self._config.get("ttl_days")
        if val and int(val) > 0:
            return int(val)
        return None

    def _compute_expires_at(self) -> Optional[float]:
        days = self.ttl_days
        if days:
            return time.time() + (days * 86400)
        return None

    def _ttl_seconds(self) -> Optional[float]:
        days = self.ttl_days
        if days:
            return days * 86400
        return None

    @abstractmethod
    def config_schema(self) -> List[ConfigField]:
        """Return the list of configuration fields for the setup UI."""
        ...

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """Test the connection. Returns {"ok": True/False, ...}."""
        ...

    @abstractmethod
    def sync(self, store: MemoryStore) -> SyncResult:
        """Sync data from the external source into the memory store."""
        ...

    def configure(self, values: Dict[str, Any]) -> None:
        """Save configuration values."""
        for f in self.config_schema():
            if f.name in values:
                self._config[f.name] = values[f.name]
        self._config["_configured"] = True
        self._config["_enabled"] = True
        self._save()

    def update(self, values: Dict[str, Any]) -> None:
        """Partial update of configuration."""
        for k, v in values.items():
            if v is not None:
                self._config[k] = v
        self._save()

    def set_enabled(self, enabled: bool) -> None:
        self._config["_enabled"] = enabled
        self._save()

    def get_status(self) -> Dict[str, Any]:
        """Return current status for the UI."""
        schema = self.config_schema()
        display_values = {}
        for f in schema:
            val = self._config.get(f.name, f.default)
            if f.type == "password" and val:
                display_values[f.name] = "••••••••"
            else:
                display_values[f.name] = val

        sync_history = self._config.get("_sync_history", [])
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "icon": self.icon,
            "category": self.category,
            "setup_guide": self.setup_guide,
            "color": self.color,
            "configured": self.configured,
            "enabled": self.enabled,
            "last_sync": self._config.get("_last_sync"),
            "synced_count": self._config.get("_synced_count", 0),
            "ttl_days": self.ttl_days,
            "config": display_values,
            "schema": [f.to_dict() for f in schema],
            "sync_history": sync_history,
            "error_count": sum(s.get("errors", 0) for s in sync_history),
        }

    def remove(self) -> None:
        """Remove configuration."""
        if self._config_path.exists():
            self._config_path.unlink()
        self._config = {}

    def purge(self, store: MemoryStore) -> int:
        """Remove all memories created by this connector."""
        prefix = f"{self.name}/"
        count = 0
        for m in store.list():
            if m.key.startswith(prefix):
                store.delete(m.key)
                count += 1
        return count

    def _record_sync(self, result: SyncResult) -> None:
        history = self._config.get("_sync_history", [])
        history.insert(0, {
            "timestamp": time.time(),
            "added": result.added,
            "updated": result.updated,
            "removed": result.removed,
            "skipped": result.skipped,
            "errors": len(result.errors),
            "error_details": result.errors[:5] if result.errors else [],
        })
        self._config["_sync_history"] = history[:20]
        self._save()

    def _update_sync_stats(self, count: int, result: Optional[SyncResult] = None) -> None:
        self._config["_last_sync"] = time.time()
        self._config["_synced_count"] = count
        self._save()
        if result is not None:
            self._record_sync(result)
