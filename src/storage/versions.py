"""Memory version history — tracks changes to memories over time."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import List

from .db import Database


@dataclass
class MemoryVersion:
    id: int
    memory_key: str
    value: str
    tags: List[str]
    changed_by: str
    created_at: float


class VersionStore:

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, memory_key: str, value: str, tags: List[str],
               metadata: dict = None, changed_by: str = "") -> None:
        self._db.conn.execute(
            "INSERT INTO memory_versions (memory_key, value, tags, metadata, changed_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (memory_key, value, json.dumps(tags), json.dumps(metadata or {}), changed_by, time.time()),
        )
        self._db.conn.commit()

    def history(self, memory_key: str, limit: int = 20) -> List[MemoryVersion]:
        rows = self._db.conn.execute(
            "SELECT id, memory_key, value, tags, changed_by, created_at FROM memory_versions WHERE memory_key = ? ORDER BY created_at DESC LIMIT ?",
            (memory_key, limit),
        ).fetchall()
        return [
            MemoryVersion(
                id=r["id"], memory_key=r["memory_key"], value=r["value"],
                tags=json.loads(r["tags"]), changed_by=r["changed_by"], created_at=r["created_at"],
            )
            for r in rows
        ]

    def count(self, memory_key: str) -> int:
        row = self._db.conn.execute(
            "SELECT count(*) FROM memory_versions WHERE memory_key = ?", (memory_key,)
        ).fetchone()
        return row[0] if row else 0

    def cleanup(self, memory_key: str, keep: int = 10) -> int:
        """Keep only the N most recent versions."""
        rows = self._db.conn.execute(
            "SELECT id FROM memory_versions WHERE memory_key = ? ORDER BY created_at DESC",
            (memory_key,),
        ).fetchall()
        if len(rows) <= keep:
            return 0
        ids_to_delete = [r["id"] for r in rows[keep:]]
        placeholders = ",".join("?" * len(ids_to_delete))
        self._db.conn.execute(f"DELETE FROM memory_versions WHERE id IN ({placeholders})", ids_to_delete)
        self._db.conn.commit()
        return len(ids_to_delete)
