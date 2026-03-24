"""Profile manager — multiple isolated knowledge databases."""
from __future__ import annotations

import json
import shutil
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .db import Database


import os

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
PROFILES_DIR = _DATA_DIR / "profiles"
CONFIG_FILE = _DATA_DIR / "profiles.json"
DEFAULT_DB = _DATA_DIR / "data.db"

DEFAULT_ID = "default"


@dataclass
class Profile:
    id: str
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
        self._migrate_legacy()
        self._ensure_default()

    def _load_config(self) -> Dict:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
        return {"active": DEFAULT_ID, "profiles": {}}

    def _save_config(self) -> None:
        CONFIG_FILE.write_text(json.dumps(self._config, indent=2))

    def _migrate_legacy(self) -> None:
        """Migrate old name-keyed profiles to UUID-keyed."""
        changed = False
        new_profiles = {}
        for key, data in list(self._config["profiles"].items()):
            if "id" not in data:
                # Legacy profile — key was the name
                pid = DEFAULT_ID if data.get("is_default") else str(uuid.uuid4())[:8]
                data["id"] = pid
                data.setdefault("name", key)
                new_profiles[pid] = data
                # Update active reference
                if self._config.get("active") == key:
                    self._config["active"] = pid
                changed = True
            else:
                new_profiles[key] = data
        if changed:
            self._config["profiles"] = new_profiles
            self._save_config()

    def _ensure_default(self) -> None:
        if DEFAULT_ID not in self._config["profiles"]:
            self._config["profiles"][DEFAULT_ID] = {
                "id": DEFAULT_ID,
                "name": "default",
                "description": "Default knowledge base",
                "db_path": str(DEFAULT_DB),
                "created_at": time.time(),
                "is_default": True,
            }
            if not self._config.get("active"):
                self._config["active"] = DEFAULT_ID
            self._save_config()

    @property
    def active_id(self) -> str:
        return self._config.get("active", DEFAULT_ID)

    @property
    def active_name(self) -> str:
        data = self._config["profiles"].get(self.active_id, {})
        return data.get("name", "default")

    @property
    def active_db_path(self) -> Path:
        p = self._config["profiles"].get(self.active_id, {})
        return Path(p.get("db_path", str(DEFAULT_DB)))

    @property
    def active_data_dir(self) -> Path:
        if self.active_id == DEFAULT_ID:
            return _DATA_DIR
        return PROFILES_DIR / self.active_id

    def _find_by_name(self, name: str) -> Optional[str]:
        """Find profile ID by name."""
        for pid, data in self._config["profiles"].items():
            if data.get("name") == name:
                return pid
        return None

    def list(self) -> List[Profile]:
        result = []
        for pid, data in self._config["profiles"].items():
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
                id=pid,
                name=data.get("name", pid),
                description=data.get("description", ""),
                db_path=data.get("db_path", ""),
                created_at=data.get("created_at", 0),
                memory_count=count,
                is_default=data.get("is_default", False),
            ))
        result.sort(key=lambda p: (not p.is_default, p.name))
        return result

    def get(self, pid: str) -> Optional[Profile]:
        data = self._config["profiles"].get(pid)
        if not data:
            return None
        return Profile(
            id=pid,
            name=data.get("name", pid),
            description=data.get("description", ""),
            db_path=data.get("db_path", ""),
            created_at=data.get("created_at", 0),
            is_default=data.get("is_default", False),
        )

    def rename(self, pid: str, new_name: str, description: str = "") -> None:
        if pid not in self._config["profiles"]:
            raise KeyError(f"Profile '{pid}' not found.")
        if self._config["profiles"][pid].get("is_default"):
            raise ValueError("Cannot rename the default profile.")
        # Check name uniqueness
        existing = self._find_by_name(new_name)
        if existing and existing != pid:
            raise ValueError(f"Profile name '{new_name}' already in use.")

        self._config["profiles"][pid]["name"] = new_name
        if description:
            self._config["profiles"][pid]["description"] = description
        self._save_config()

    def create(self, name: str, description: str = "") -> Profile:
        # Check name uniqueness
        if self._find_by_name(name):
            raise ValueError(f"Profile '{name}' already exists.")

        pid = str(uuid.uuid4())[:8]
        db_path = PROFILES_DIR / pid / "data.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = Database(db_path)
        db.close()

        profile_data = {
            "id": pid,
            "name": name,
            "description": description,
            "db_path": str(db_path),
            "created_at": time.time(),
            "is_default": False,
        }
        self._config["profiles"][pid] = profile_data
        self._save_config()
        return Profile(**profile_data, memory_count=0)

    def switch(self, pid: str) -> Path:
        if pid not in self._config["profiles"]:
            raise KeyError(f"Profile '{pid}' not found.")
        self._config["active"] = pid
        self._save_config()
        return self.active_db_path

    def delete(self, pid: str) -> None:
        if pid not in self._config["profiles"]:
            raise KeyError(f"Profile '{pid}' not found.")
        if self._config["profiles"][pid].get("is_default"):
            raise ValueError("Cannot delete the default profile.")

        db_path = Path(self._config["profiles"][pid].get("db_path", ""))
        del self._config["profiles"][pid]

        if self._config["active"] == pid:
            self._config["active"] = DEFAULT_ID

        self._save_config()

        if db_path.exists() and str(PROFILES_DIR) in str(db_path):
            profile_dir = db_path.parent
            if profile_dir.exists() and profile_dir != PROFILES_DIR:
                shutil.rmtree(profile_dir, ignore_errors=True)

    def duplicate(self, source_pid: str, new_name: str, description: str = "") -> Profile:
        source = self._config["profiles"].get(source_pid)
        if not source:
            raise KeyError(f"Profile '{source_pid}' not found.")

        new_profile = self.create(new_name, description or f"Copy of {source.get('name', source_pid)}")
        source_path = Path(source["db_path"])
        dest_path = Path(new_profile.db_path)

        if source_path.exists():
            shutil.copy2(str(source_path), str(dest_path))

        return new_profile

    def import_memories_from(self, target_pid: str, source_pid: str, tags: Optional[List[str]] = None) -> int:
        source = self._config["profiles"].get(source_pid)
        target = self._config["profiles"].get(target_pid)
        if not source:
            raise KeyError(f"Profile '{source_pid}' not found.")
        if not target:
            raise KeyError(f"Profile '{target_pid}' not found.")

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
            # Rebuild FTS index to include imported memories
            if count > 0:
                tgt_db.conn.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
                tgt_db.conn.commit()
        finally:
            src_db.close()
            tgt_db.close()

        return count

    def preview_import(self, target_pid: str, source_pid: str, tags: Optional[List[str]] = None) -> Dict:
        """Preview how many memories would be imported (total, new, skipped)."""
        source = self._config["profiles"].get(source_pid)
        target = self._config["profiles"].get(target_pid)
        if not source:
            raise KeyError(f"Profile '{source_pid}' not found.")
        if not target:
            raise KeyError(f"Profile '{target_pid}' not found.")

        source_path = Path(source["db_path"])
        target_path = Path(target["db_path"])
        if not source_path.exists():
            return {"total": 0, "new": 0, "skipped": 0}

        import json as _json

        src_db = Database(source_path, check_same_thread=False)
        tgt_db = Database(target_path, check_same_thread=False)
        total = 0
        new = 0

        try:
            rows = src_db.conn.execute(
                "SELECT key, tags FROM memories"
            ).fetchall()

            for row in rows:
                row_tags = _json.loads(row["tags"]) if row["tags"] else []
                if tags and not any(t in row_tags for t in tags):
                    continue
                total += 1
                existing = tgt_db.conn.execute(
                    "SELECT key FROM memories WHERE key = ?", (row["key"],)
                ).fetchone()
                if not existing:
                    new += 1
        finally:
            src_db.close()
            tgt_db.close()

        return {"total": total, "new": new, "skipped": total - new}

    def get_profile_tags(self, pid: str) -> List[str]:
        """Get all unique tags from a profile's memories."""
        profile = self._config["profiles"].get(pid)
        if not profile:
            raise KeyError(f"Profile '{pid}' not found.")
        db_path = Path(profile["db_path"])
        if not db_path.exists():
            return []

        import json as _json

        db = Database(db_path, check_same_thread=False)
        try:
            rows = db.conn.execute("SELECT tags FROM memories").fetchall()
            all_tags = set()
            for row in rows:
                tags = _json.loads(row["tags"]) if row["tags"] else []
                all_tags.update(tags)
            return sorted(all_tags)
        finally:
            db.close()
