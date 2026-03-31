"""Memory relations — manual and auto-detected links between memories."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import List

from .db import Database


@dataclass
class Relation:
    id: int
    source_key: str
    target_key: str
    relation_type: str
    created_at: float
    auto: bool = False
    confidence: float = 1.0


class RelationStore:

    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, source_key: str, target_key: str, relation_type: str = "related") -> Relation:
        try:
            self._db.conn.execute(
                "INSERT INTO memory_relations (source_key, target_key, relation_type, created_at) VALUES (?, ?, ?, ?)",
                (source_key, target_key, relation_type, time.time()),
            )
            self._db.conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError(f"Relation already exists: {source_key} -> {target_key} ({relation_type})")
        row = self._db.conn.execute(
            "SELECT id, source_key, target_key, relation_type, created_at FROM memory_relations WHERE source_key = ? AND target_key = ? AND relation_type = ?",
            (source_key, target_key, relation_type),
        ).fetchone()
        return Relation(id=row["id"], source_key=row["source_key"], target_key=row["target_key"],
                        relation_type=row["relation_type"], created_at=row["created_at"])

    def remove(self, relation_id: int) -> None:
        cursor = self._db.conn.execute("DELETE FROM memory_relations WHERE id = ?", (relation_id,))
        self._db.conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Relation {relation_id} not found")

    def get_relations(self, memory_key: str) -> List[Relation]:
        rows = self._db.conn.execute(
            "SELECT id, source_key, target_key, relation_type, created_at, auto, confidence FROM memory_relations WHERE source_key = ? OR target_key = ? ORDER BY created_at DESC",
            (memory_key, memory_key),
        ).fetchall()
        return [self._row_to_relation(r) for r in rows]

    def list_all(self) -> List[Relation]:
        rows = self._db.conn.execute(
            "SELECT id, source_key, target_key, relation_type, created_at, auto, confidence FROM memory_relations ORDER BY created_at DESC",
        ).fetchall()
        return [self._row_to_relation(r) for r in rows]

    def bulk_add_auto(self, relations: List[dict]) -> int:
        """Batch-insert auto-detected relations. Skips duplicates."""
        count = 0
        now = time.time()
        for r in relations:
            try:
                self._db.conn.execute(
                    "INSERT OR IGNORE INTO memory_relations (source_key, target_key, relation_type, auto, confidence, created_at) VALUES (?, ?, ?, 1, ?, ?)",
                    (r["source_key"], r["target_key"], r["relation_type"], r.get("confidence", 1.0), now),
                )
                count += self._db.conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
        self._db.conn.commit()
        return count

    def clear_auto(self) -> int:
        """Remove all auto-detected relations."""
        cursor = self._db.conn.execute("DELETE FROM memory_relations WHERE auto = 1")
        self._db.conn.commit()
        return cursor.rowcount

    def _row_to_relation(self, r) -> Relation:
        return Relation(
            id=r["id"], source_key=r["source_key"], target_key=r["target_key"],
            relation_type=r["relation_type"], created_at=r["created_at"],
            auto=bool(r["auto"]) if "auto" in r.keys() else False,
            confidence=r["confidence"] if "confidence" in r.keys() else 1.0,
        )
