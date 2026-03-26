"""Memory persistence — SQLite-backed key-value store with metadata, tagging, and FTS5 search."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .db import Database


@dataclass
class Memory:
    key: str
    value: str
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    pinned: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pinned": self.pinned,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Memory:
        return cls(
            key=d["key"],
            value=d["value"],
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )


def _row_to_memory(row) -> Memory:
    pinned = False
    try:
        pinned = bool(row["pinned"])
    except (IndexError, KeyError):
        pass
    return Memory(
        key=row["key"],
        value=row["value"],
        tags=json.loads(row["tags"]),
        metadata=json.loads(row["metadata"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        pinned=pinned,
    )


class MemoryStore:
    """SQLite-backed memory storage with FTS5 full-text search."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._has_pin: Optional[bool] = None

    def _has_pinned_column(self) -> bool:
        if self._has_pin is None:
            try:
                self._db.conn.execute("SELECT pinned FROM memories LIMIT 0")
                self._has_pin = True
            except Exception:
                self._has_pin = False
        return self._has_pin

    def list(self, limit: int = 0, offset: int = 0, source: str = "",
             sort: str = "key", order: str = "asc") -> List[Memory]:
        allowed_sorts = {"key": "key", "updated": "updated_at", "created": "created_at", "size": "length(value)"}
        sort_col = allowed_sorts.get(sort, "key")
        order_dir = "DESC" if order == "desc" else "ASC"
        has_pin = self._has_pinned_column()

        cols = "key, value, tags, metadata, created_at, updated_at"
        if has_pin:
            cols += ", pinned"

        sql = f"SELECT {cols} FROM memories"
        params: list = []

        if source:
            sql += " WHERE key LIKE ?"
            params.append(f"{source}/%")

        if has_pin:
            sql += f" ORDER BY pinned DESC, {sort_col} {order_dir}"
        else:
            sql += f" ORDER BY {sort_col} {order_dir}"

        if limit > 0:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = self._db.conn.execute(sql, params).fetchall()
        return [_row_to_memory(r) for r in rows]

    def count(self, source: str = "") -> int:
        if source:
            row = self._db.conn.execute("SELECT count(*) FROM memories WHERE key LIKE ?", (f"{source}/%",)).fetchone()
        else:
            row = self._db.conn.execute("SELECT count(*) FROM memories").fetchone()
        return row[0] if row else 0

    def sources(self) -> List[dict]:
        """Return distinct source prefixes with counts."""
        rows = self._db.conn.execute(
            "SELECT key FROM memories"
        ).fetchall()
        counts: dict = {}
        for r in rows:
            key = r["key"]
            prefix = key.split("/")[0] if "/" in key else "(none)"
            counts[prefix] = counts.get(prefix, 0) + 1
        return sorted([{"source": k, "count": v} for k, v in counts.items()], key=lambda x: -x["count"])

    def get(self, key: str) -> Memory:
        pin_col = ", pinned" if self._has_pinned_column() else ""
        row = self._db.conn.execute(
            f"SELECT key, value, tags, metadata, created_at, updated_at{pin_col} FROM memories WHERE key = ?",
            (key,),
        ).fetchone()
        if not row:
            raise KeyError(f"Memory '{key}' not found.")
        return _row_to_memory(row)

    def set(self, memory: Memory) -> None:
        existing = self._db.conn.execute(
            "SELECT created_at FROM memories WHERE key = ?", (memory.key,)
        ).fetchone()
        if existing:
            memory.created_at = existing["created_at"]
            memory.updated_at = time.time()
            self._db.conn.execute(
                """UPDATE memories SET value = ?, tags = ?, metadata = ?,
                   created_at = ?, updated_at = ? WHERE key = ?""",
                (memory.value, json.dumps(memory.tags), json.dumps(memory.metadata),
                 memory.created_at, memory.updated_at, memory.key),
            )
        else:
            has_pin = self._has_pinned_column()
            if has_pin:
                self._db.conn.execute(
                    """INSERT INTO memories (key, value, tags, metadata, created_at, updated_at, pinned)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (memory.key, memory.value, json.dumps(memory.tags),
                     json.dumps(memory.metadata), memory.created_at, memory.updated_at,
                     1 if memory.pinned else 0),
                )
            else:
                self._db.conn.execute(
                    """INSERT INTO memories (key, value, tags, metadata, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (memory.key, memory.value, json.dumps(memory.tags),
                     json.dumps(memory.metadata), memory.created_at, memory.updated_at),
                )
        self._db.conn.commit()

    def delete(self, key: str, soft: bool = True) -> None:
        row = self._db.conn.execute(
            "SELECT key, value, tags, metadata, created_at FROM memories WHERE key = ?", (key,)
        ).fetchone()
        if not row:
            raise KeyError(f"Memory '{key}' not found.")
        if soft:
            try:
                self._db.conn.execute(
                    "INSERT OR REPLACE INTO memory_trash (key, value, tags, metadata, created_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (row["key"], row["value"], row["tags"], row["metadata"], row["created_at"], time.time()),
                )
            except Exception:
                pass  # trash table may not exist yet
        self._db.conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        self._db.conn.commit()

    def pin(self, key: str, pinned: bool = True) -> None:
        try:
            self._db.conn.execute("UPDATE memories SET pinned = ? WHERE key = ?", (1 if pinned else 0, key))
            self._db.conn.commit()
        except Exception:
            pass  # pinned column may not exist yet

    def trash_list(self) -> list:
        try:
            rows = self._db.conn.execute(
                "SELECT key, value, tags, metadata, created_at, deleted_at FROM memory_trash ORDER BY deleted_at DESC"
            ).fetchall()
            return [{"key": r["key"], "value": r["value"][:200], "tags": json.loads(r["tags"]),
                     "created_at": r["created_at"], "deleted_at": r["deleted_at"]} for r in rows]
        except Exception:
            return []

    def trash_restore(self, key: str) -> None:
        row = self._db.conn.execute("SELECT * FROM memory_trash WHERE key = ?", (key,)).fetchone()
        if not row:
            raise KeyError(f"Trashed memory '{key}' not found.")
        m = Memory(key=row["key"], value=row["value"], tags=json.loads(row["tags"]),
                   metadata=json.loads(row["metadata"]), created_at=row["created_at"])
        self.set(m)
        self._db.conn.execute("DELETE FROM memory_trash WHERE key = ?", (key,))
        self._db.conn.commit()

    def trash_purge(self, key: str = "") -> int:
        if key:
            self._db.conn.execute("DELETE FROM memory_trash WHERE key = ?", (key,))
        else:
            self._db.conn.execute("DELETE FROM memory_trash")
        self._db.conn.commit()
        return self._db.conn.execute("SELECT changes()").fetchone()[0]

    def trash_cleanup(self, days: int = 30) -> int:
        cutoff = time.time() - (days * 86400)
        self._db.conn.execute("DELETE FROM memory_trash WHERE deleted_at < ?", (cutoff,))
        self._db.conn.commit()
        return self._db.conn.execute("SELECT changes()").fetchone()[0]

    def search(self, query: str, tags: Optional[List[str]] = None,
               source: str = "", limit: int = 0, offset: int = 0) -> List[Memory]:
        q = query.strip()
        tag_set: Optional[Set[str]] = set(tags) if tags else None

        has_pin = self._has_pinned_column()
        pin_col = ", pinned" if has_pin else ""
        m_pin_col = ", m.pinned" if has_pin else ""

        if q:
            fts_query = '"' + q.replace('"', '""') + '"'
            rows = self._db.conn.execute(
                f"""SELECT m.key, m.value, m.tags, m.metadata, m.created_at, m.updated_at{m_pin_col}
                   FROM memories m
                   JOIN memories_fts fts ON m.rowid = fts.rowid
                   WHERE memories_fts MATCH ?
                   ORDER BY rank""",
                (fts_query,),
            ).fetchall()
            fts_keys = {r["key"] for r in rows}
            like_pattern = f"%{q}%"
            like_rows = self._db.conn.execute(
                f"""SELECT key, value, tags, metadata, created_at, updated_at{pin_col}
                   FROM memories
                   WHERE (key LIKE ? OR value LIKE ?) AND key NOT IN (
                     SELECT key FROM memories WHERE key IN ({",".join("?" * len(fts_keys))})
                   )""" if fts_keys else
                f"""SELECT key, value, tags, metadata, created_at, updated_at{pin_col}
                   FROM memories
                   WHERE key LIKE ? OR value LIKE ?""",
                (like_pattern, like_pattern, *fts_keys) if fts_keys else
                (like_pattern, like_pattern),
            ).fetchall()
            all_rows = list(rows) + list(like_rows)
        else:
            all_rows = self._db.conn.execute(
                f"SELECT key, value, tags, metadata, created_at, updated_at{pin_col} FROM memories"
            ).fetchall()

        results = []
        for r in all_rows:
            mem = _row_to_memory(r)
            if tag_set and not tag_set.issubset(set(mem.tags)):
                continue
            if source and not mem.key.startswith(f"{source}/"):
                continue
            results.append(mem)

        if limit > 0:
            return results[offset:offset + limit]
        return results

    def tags(self) -> List[str]:
        all_tags: Set[str] = set()
        rows = self._db.conn.execute("SELECT tags FROM memories").fetchall()
        for r in rows:
            all_tags.update(json.loads(r["tags"]))
        return sorted(all_tags)

    def export_json(self) -> str:
        memories = self.list()
        return json.dumps({"memories": [m.to_dict() for m in memories]}, indent=2)

    def import_json(self, data: str, merge: bool = True) -> int:
        incoming = json.loads(data)
        imported = [Memory.from_dict(d) for d in incoming.get("memories", [])]
        if not merge:
            self._db.conn.execute("DELETE FROM memories")
            self._db.conn.commit()
        for m in imported:
            self.set(m)
        return len(imported)
