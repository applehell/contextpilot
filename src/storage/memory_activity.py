"""Memory activity log — tracks memory operations (get, set, delete, search) for the dashboard."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List, Optional

from .db import Database


@dataclass
class ActivityEntry:
    operation: str  # "created", "updated", "deleted", "loaded", "searched"
    memory_key: str
    detail: str
    created_at: float

    @property
    def age_label(self) -> str:
        delta = time.time() - self.created_at
        if delta < 60:
            return "gerade eben"
        if delta < 3600:
            return f"vor {int(delta / 60)} Min"
        if delta < 86400:
            return f"vor {int(delta / 3600)} Std"
        return f"vor {int(delta / 86400)} Tagen"


class MemoryActivityLog:
    """SQLite-backed activity log for memory operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, operation: str, memory_key: str, detail: str = "") -> None:
        self._db.conn.execute(
            "INSERT INTO memory_activity (operation, memory_key, detail, created_at) VALUES (?, ?, ?, ?)",
            (operation, memory_key, detail, time.time()),
        )
        self._db.conn.commit()

    def recent(self, limit: int = 20) -> List[ActivityEntry]:
        rows = self._db.conn.execute(
            "SELECT operation, memory_key, detail, created_at FROM memory_activity ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            ActivityEntry(
                operation=r["operation"],
                memory_key=r["memory_key"],
                detail=r["detail"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    def clear(self, older_than_days: int = 30) -> int:
        cutoff = time.time() - older_than_days * 86400
        cursor = self._db.conn.execute(
            "DELETE FROM memory_activity WHERE created_at < ?", (cutoff,)
        )
        self._db.conn.commit()
        return cursor.rowcount
