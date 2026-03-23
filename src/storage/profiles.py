"""Profile manager — multiple isolated knowledge databases."""
from __future__ import annotations

import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .db import Database


import os

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
PROFILES_DIR = _DATA_DIR / "profiles"
CONFIG_FILE = _DATA_DIR / "profiles.json"
DEFAULT_DB = _DATA_DIR / "data.db"


@dataclass
class Profile:
    name: str
    description: str = ""
    db_path: str = ""
    created_at: float = field(default_factory=time.time)
    memory_count: int = 0
    is_default: bool = False


class ProfileManager:
    """Manages multiple knowledge-base profiles, each backed by its own SQLite DB."""

    def __init__(self) -> None:
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        self._config = self._load_config()
        self._ensure_default()

    def _load_config(self) -> Dict:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
        return {"active": "default", "profiles": {}}

    def _save_config(self) -> None:
        CONFIG_FILE.write_text(json.dumps(self._config, indent=2))

    def _ensure_default(self) -> None:
        if "default" not in self._config["profiles"]:
            self._config["profiles"]["default"] = {
                "name": "default",
                "description": "Standard-Wissensdatenbank",
                "db_path": str(DEFAULT_DB),
                "created_at": time.time(),
                "is_default": True,
            }
            if "active" not in self._config or not self._config["active"]:
                self._config["active"] = "default"
            self._save_config()

    @property
    def active_name(self) -> str:
        return self._config.get("active", "default")

    @property
    def active_db_path(self) -> Path:
        p = self._config["profiles"].get(self.active_name, {})
        return Path(p.get("db_path", str(DEFAULT_DB)))

    def list(self) -> List[Profile]:
        result = []
        for name, data in self._config["profiles"].items():
            db_path = Path(data.get("db_path", ""))
            count = 0
            if db_path.exists():
                try:
                    db = Database(db_path, check_same_thread=False)
                    row = db.conn.execute("SELECT count(*) FROM memories").fetchone()
                    count = row[0] if row else 0
                    db.close()
                except Exception:
                    pass
            result.append(Profile(
                name=name,
                description=data.get("description", ""),
                db_path=data.get("db_path", ""),
                created_at=data.get("created_at", 0),
                memory_count=count,
                is_default=data.get("is_default", False),
            ))
        result.sort(key=lambda p: (not p.is_default, p.name))
        return result

    def get(self, name: str) -> Optional[Profile]:
        data = self._config["profiles"].get(name)
        if not data:
            return None
        return Profile(
            name=name,
            description=data.get("description", ""),
            db_path=data.get("db_path", ""),
            created_at=data.get("created_at", 0),
            is_default=data.get("is_default", False),
        )

    def rename(self, old_name: str, new_name: str, description: str = "") -> None:
        if old_name not in self._config["profiles"]:
            raise KeyError(f"Profile '{old_name}' not found.")
        if self._config["profiles"][old_name].get("is_default"):
            raise ValueError("Cannot rename the default profile.")
        if new_name in self._config["profiles"]:
            raise ValueError(f"Profile '{new_name}' already exists.")
        if not new_name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Profile name must be alphanumeric (with - and _ allowed).")

        data = self._config["profiles"].pop(old_name)
        data["name"] = new_name
        if description:
            data["description"] = description
        self._config["profiles"][new_name] = data

        if self._config["active"] == old_name:
            self._config["active"] = new_name
        self._save_config()

    def create(self, name: str, description: str = "") -> Profile:
        if name in self._config["profiles"]:
            raise ValueError(f"Profile '{name}' already exists.")
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Profile name must be alphanumeric (with - and _ allowed).")

        db_path = PROFILES_DIR / name / "data.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Create the DB (triggers migrations)
        db = Database(db_path)
        db.close()

        profile_data = {
            "name": name,
            "description": description,
            "db_path": str(db_path),
            "created_at": time.time(),
            "is_default": False,
        }
        self._config["profiles"][name] = profile_data
        self._save_config()
        return Profile(**profile_data, memory_count=0)

    def switch(self, name: str) -> Path:
        if name not in self._config["profiles"]:
            raise KeyError(f"Profile '{name}' not found.")
        self._config["active"] = name
        self._save_config()
        return self.active_db_path

    def delete(self, name: str) -> None:
        if name not in self._config["profiles"]:
            raise KeyError(f"Profile '{name}' not found.")
        if self._config["profiles"][name].get("is_default"):
            raise ValueError("Cannot delete the default profile.")

        db_path = Path(self._config["profiles"][name].get("db_path", ""))
        del self._config["profiles"][name]

        if self._config["active"] == name:
            self._config["active"] = "default"

        self._save_config()

        # Remove profile directory
        if db_path.exists() and str(PROFILES_DIR) in str(db_path):
            profile_dir = db_path.parent
            if profile_dir.exists() and profile_dir != PROFILES_DIR:
                shutil.rmtree(profile_dir, ignore_errors=True)

    def duplicate(self, source_name: str, new_name: str, description: str = "") -> Profile:
        source = self._config["profiles"].get(source_name)
        if not source:
            raise KeyError(f"Profile '{source_name}' not found.")

        new_profile = self.create(new_name, description or f"Kopie von {source_name}")
        source_path = Path(source["db_path"])
        dest_path = Path(new_profile.db_path)

        if source_path.exists():
            shutil.copy2(str(source_path), str(dest_path))

        return new_profile

    def import_memories_from(self, target_name: str, source_name: str, tags: Optional[List[str]] = None) -> int:
        """Copy memories from source profile into target profile. Optionally filter by tags."""
        source = self._config["profiles"].get(source_name)
        target = self._config["profiles"].get(target_name)
        if not source:
            raise KeyError(f"Profile '{source_name}' not found.")
        if not target:
            raise KeyError(f"Profile '{target_name}' not found.")

        source_path = Path(source["db_path"])
        target_path = Path(target["db_path"])
        if not source_path.exists():
            return 0

        import json as _json

        src_db = Database(source_path, check_same_thread=False)
        tgt_db = Database(target_path, check_same_thread=False)
        count = 0

        try:
            rows = src_db.conn.execute(
                "SELECT key, value, tags, metadata, created_at, updated_at FROM memories"
            ).fetchall()

            for row in rows:
                row_tags = _json.loads(row["tags"]) if row["tags"] else []
                if tags and not any(t in row_tags for t in tags):
                    continue

                existing = tgt_db.conn.execute(
                    "SELECT key FROM memories WHERE key = ?", (row["key"],)
                ).fetchone()
                if existing:
                    continue

                tgt_db.conn.execute(
                    "INSERT INTO memories (key, value, tags, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["key"], row["value"], row["tags"], row["metadata"], row["created_at"], row["updated_at"]),
                )
                count += 1

            tgt_db.conn.commit()
        finally:
            src_db.close()
            tgt_db.close()

        return count
