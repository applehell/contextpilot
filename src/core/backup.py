"""Backup & Restore — create, list, restore, and manage database backups."""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.memory import MemoryStore


class BackupManager:
    """Manages database backups in a dedicated backups directory."""

    FILENAME_PATTERN = re.compile(r"^backup_\d{8}_\d{6}\.db$")

    def __init__(self, data_dir: Path, max_backups: int = 10) -> None:
        self._data_dir = data_dir
        self._backup_dir = data_dir / "backups"
        self._max_backups = max_backups

    @property
    def backup_dir(self) -> Path:
        return self._backup_dir

    def _db_path(self) -> Path:
        return self._data_dir / "data.db"

    def _validate_filename(self, filename: str) -> Path:
        if not self.FILENAME_PATTERN.match(filename):
            raise ValueError(f"Invalid backup filename: {filename}")
        resolved = (self._backup_dir / filename).resolve()
        if not str(resolved).startswith(str(self._backup_dir.resolve())):
            raise ValueError("Path traversal detected")
        return resolved

    def create_backup(self) -> Path:
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = self._backup_dir / f"backup_{ts}.db"
        db_path = self._db_path()
        if not db_path.exists():
            raise FileNotFoundError(f"Database not found: {db_path}")
        shutil.copy2(str(db_path), str(dest))
        return dest

    def list_backups(self) -> List[Dict[str, Any]]:
        if not self._backup_dir.exists():
            return []
        result = []
        for f in self._backup_dir.iterdir():
            if f.is_file() and self.FILENAME_PATTERN.match(f.name):
                stat = f.stat()
                result.append({
                    "filename": f.name,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    "size_bytes": stat.st_size,
                })
        result.sort(key=lambda x: x["filename"], reverse=True)
        return result

    def restore_backup(self, filename: str) -> Path:
        src = self._validate_filename(filename)
        if not src.exists():
            raise ValueError(f"Backup not found: {filename}")
        db_path = self._db_path()
        shutil.copy2(str(src), str(db_path))
        return db_path

    def delete_backup(self, filename: str) -> None:
        path = self._validate_filename(filename)
        if not path.exists():
            raise ValueError(f"Backup not found: {filename}")
        path.unlink()

    def cleanup_old_backups(self) -> int:
        backups = self.list_backups()
        if len(backups) <= self._max_backups:
            return 0
        to_delete = backups[self._max_backups:]
        for b in to_delete:
            path = self._backup_dir / b["filename"]
            if path.exists():
                path.unlink()
        return len(to_delete)

    def export_json(self, store: MemoryStore) -> Dict[str, Any]:
        memories = store.list()
        exported = []
        for m in memories:
            exported.append({
                "key": m.key,
                "value": m.value,
                "tags": m.tags,
                "metadata": m.metadata,
            })
        return {
            "memories": exported,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "count": len(exported),
        }

    def import_json(self, store: MemoryStore, data: Dict[str, Any]) -> int:
        from ..storage.memory import Memory
        items = data.get("memories", [])
        count = 0
        for item in items:
            m = Memory(
                key=item["key"],
                value=item["value"],
                tags=item.get("tags", []),
                metadata=item.get("metadata", {}),
            )
            store.set(m)
            count += 1
        return count
