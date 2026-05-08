"""Memory persistence — SQLite-backed key-value store with metadata, tagging, and FTS5 search."""
from __future__ import annotations

import json
import re
import sqlite3
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
    expires_at: Optional[float] = None
    category: str = "persistent"

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= time.time()

    @property
    def ttl_remaining(self) -> Optional[float]:
        if self.expires_at is None:
            return None
        return max(0.0, self.expires_at - time.time())

    @property
    def ttl_label(self) -> Optional[str]:
        rem = self.ttl_remaining
        if rem is None:
            return None
        if rem <= 0:
            return "expired"
        days = rem / 86400
        if days >= 1:
            return f"{int(days)}d"
        hours = rem / 3600
        if hours >= 1:
            return f"{int(hours)}h"
        return f"{int(rem / 60)}m"

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "key": self.key,
            "value": self.value,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "pinned": self.pinned,
            "expires_at": self.expires_at,
            "category": self.category,
        }
        d["ttl_label"] = self.ttl_label
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Memory:
        return cls(
            key=d["key"],
            value=d["value"],
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
            pinned=d.get("pinned", False),
            expires_at=d.get("expires_at"),
            category=d.get("category", "persistent"),
        )


def _row_to_memory(row) -> Memory:
    try:
        tags = json.loads(row["tags"])
    except (json.JSONDecodeError, TypeError):
        tags = []
    try:
        metadata = json.loads(row["metadata"])
    except (json.JSONDecodeError, TypeError):
        metadata = {}
    return Memory(
        key=row["key"],
        value=row["value"],
        tags=tags,
        metadata=metadata,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        pinned=bool(row["pinned"]),
        expires_at=row["expires_at"],
        category=row["category"] or "persistent",
    )


class MemoryStore:
    """SQLite-backed memory storage with FTS5 full-text search."""

    CATEGORY_TTL = {"session": 86400, "ephemeral": 3600}

    _COLS = "key, value, tags, metadata, created_at, updated_at, pinned, expires_at, category"

    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self, limit: int = 0, offset: int = 0, source: str = "",
             sort: str = "key", order: str = "asc", category: Optional[str] = None) -> List[Memory]:
        allowed_sorts = {"key": "key", "updated": "updated_at", "created": "created_at",
                         "size": "length(value)", "expires": "expires_at"}
        sort_col = allowed_sorts.get(sort, "key")
        order_dir = "DESC" if order == "desc" else "ASC"

        sql = f"SELECT {self._COLS} FROM memories"
        params: list = []
        conditions = []

        if source:
            conditions.append("key LIKE ?")
            params.append(f"{source}/%")

        if category:
            conditions.append("category = ?")
            params.append(category)

        if conditions:
            sql += " WHERE " + " AND ".join(conditions)

        sql += f" ORDER BY pinned DESC, {sort_col} {order_dir}"

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

    def category_stats(self) -> dict:
        """Return count of memories per category."""
        stats = {"persistent": 0, "session": 0, "ephemeral": 0}
        rows = self._db.conn.execute(
            "SELECT COALESCE(category, 'persistent') as cat, count(*) as cnt FROM memories GROUP BY cat"
        ).fetchall()
        for r in rows:
            cat = r["cat"]
            if cat in stats:
                stats[cat] = r["cnt"]
            else:
                stats["persistent"] += r["cnt"]
        return stats

    def sources(self) -> List[dict]:
        """Return distinct source prefixes with counts."""
        rows = self._db.conn.execute(
            """SELECT
                CASE WHEN INSTR(key, '/') > 0
                     THEN SUBSTR(key, 1, INSTR(key, '/') - 1)
                     ELSE '(none)'
                END AS prefix,
                COUNT(*) AS cnt
               FROM memories
               GROUP BY prefix
               ORDER BY cnt DESC"""
        ).fetchall()
        return [{"source": r["prefix"], "count": r["cnt"]} for r in rows]

    def get(self, key: str) -> Memory:
        row = self._db.conn.execute(
            f"SELECT {self._COLS} FROM memories WHERE key = ?", (key,),
        ).fetchone()
        if not row:
            raise KeyError(f"Memory '{key}' not found.")
        return _row_to_memory(row)

    def set(self, memory: Memory, reset_ttl: bool = True) -> None:
        if not memory.key or not memory.key.strip():
            raise ValueError("Memory key must not be empty.")
        existing = self._db.conn.execute(
            "SELECT created_at FROM memories WHERE key = ?", (memory.key,)
        ).fetchone()

        # Auto-set expires_at for category-based TTL on new memories
        if not existing and memory.expires_at is None and memory.category in self.CATEGORY_TTL:
            memory.expires_at = time.time() + self.CATEGORY_TTL[memory.category]

        # If updating and reset_ttl is True and memory has a TTL duration in metadata, recalculate
        if existing and reset_ttl and memory.expires_at is not None:
            ttl_seconds = memory.metadata.get("ttl_seconds")
            if ttl_seconds:
                memory.expires_at = time.time() + ttl_seconds

        if existing:
            memory.created_at = existing["created_at"]
            memory.updated_at = time.time()
            self._db.conn.execute(
                """UPDATE memories SET value = ?, tags = ?, metadata = ?,
                   created_at = ?, updated_at = ?, expires_at = ?, category = ?
                   WHERE key = ?""",
                (memory.value, json.dumps(memory.tags), json.dumps(memory.metadata),
                 memory.created_at, memory.updated_at, memory.expires_at, memory.category,
                 memory.key),
            )
        else:
            self._db.conn.execute(
                """INSERT INTO memories
                   (key, value, tags, metadata, created_at, updated_at, pinned, expires_at, category)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (memory.key, memory.value, json.dumps(memory.tags),
                 json.dumps(memory.metadata), memory.created_at, memory.updated_at,
                 1 if memory.pinned else 0, memory.expires_at, memory.category),
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
            except sqlite3.OperationalError:
                pass  # trash table may not exist yet
        self._db.conn.execute("DELETE FROM memories WHERE key = ?", (key,))
        self._db.conn.commit()

    def pin(self, key: str, pinned: bool = True) -> None:
        self._db.conn.execute("UPDATE memories SET pinned = ? WHERE key = ?", (1 if pinned else 0, key))
        self._db.conn.commit()

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

    def set_ttl(self, key: str, ttl_seconds: Optional[float]) -> None:
        if ttl_seconds is None or ttl_seconds <= 0:
            expires_at = None
            self._db.conn.execute(
                "UPDATE memories SET expires_at = NULL WHERE key = ?", (key,))
            # Remove ttl_seconds from metadata
            row = self._db.conn.execute("SELECT metadata FROM memories WHERE key = ?", (key,)).fetchone()
            if row:
                meta = json.loads(row["metadata"])
                meta.pop("ttl_seconds", None)
                self._db.conn.execute("UPDATE memories SET metadata = ? WHERE key = ?",
                                      (json.dumps(meta), key))
        else:
            expires_at = time.time() + ttl_seconds
            self._db.conn.execute(
                "UPDATE memories SET expires_at = ? WHERE key = ?", (expires_at, key))
            # Store ttl_seconds in metadata for reset on update
            row = self._db.conn.execute("SELECT metadata FROM memories WHERE key = ?", (key,)).fetchone()
            if row:
                meta = json.loads(row["metadata"])
                meta["ttl_seconds"] = ttl_seconds
                self._db.conn.execute("UPDATE memories SET metadata = ? WHERE key = ?",
                                      (json.dumps(meta), key))
        self._db.conn.commit()

    def cleanup_expired(self) -> int:
        now = time.time()
        # Move to trash first
        try:
            self._db.conn.execute(
                """INSERT OR REPLACE INTO memory_trash (key, value, tags, metadata, created_at, deleted_at)
                   SELECT key, value, tags, metadata, created_at, ? FROM memories
                   WHERE expires_at IS NOT NULL AND expires_at <= ?""",
                (now, now))
        except Exception:
            pass
        self._db.conn.execute(
            "DELETE FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,))
        self._db.conn.commit()
        return self._db.conn.execute("SELECT changes()").fetchone()[0]

    def expiring_soon(self, within_hours: float = 24.0) -> List[Memory]:
        now = time.time()
        cutoff = now + (within_hours * 3600)
        rows = self._db.conn.execute(
            f"""SELECT {self._COLS}
               FROM memories
               WHERE expires_at IS NOT NULL AND expires_at > ? AND expires_at <= ?
               ORDER BY expires_at ASC""",
            (now, cutoff),
        ).fetchall()
        return [_row_to_memory(r) for r in rows]

    def expired_count(self) -> int:
        now = time.time()
        row = self._db.conn.execute(
            "SELECT count(*) FROM memories WHERE expires_at IS NOT NULL AND expires_at <= ?", (now,)
        ).fetchone()
        return row[0] if row else 0

    def search(self, query: str, tags: Optional[List[str]] = None,
               source: str = "", limit: int = 0, offset: int = 0) -> List[Memory]:
        q = query.strip()
        tag_set: Optional[Set[str]] = set(tags) if tags else None

        m_cols = ", ".join(f"m.{c.strip()}" for c in self._COLS.split(","))

        if q:
            escaped_q = q.replace('"', '""')
            escaped_q = re.sub(r'[*()\{\}\[\]^~:]', ' ', escaped_q)
            for kw in ('AND', 'OR', 'NOT', 'NEAR'):
                escaped_q = re.sub(r'\b' + kw + r'\b', kw.lower(), escaped_q)
            fts_query = '"' + escaped_q + '"'
            try:
                rows = self._db.conn.execute(
                    f"""SELECT {m_cols}
                       FROM memories m
                       JOIN memories_fts fts ON m.rowid = fts.rowid
                       WHERE memories_fts MATCH ?
                       ORDER BY rank""",
                    (fts_query,),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            MAX_FTS_KEYS = 500
            fts_keys = {r["key"] for r in rows}
            if len(fts_keys) > MAX_FTS_KEYS:
                fts_keys = set(list(fts_keys)[:MAX_FTS_KEYS])
            like_pattern = f"%{q}%"
            like_rows = self._db.conn.execute(
                f"""SELECT {self._COLS}
                   FROM memories
                   WHERE (key LIKE ? OR value LIKE ?) AND key NOT IN (
                     SELECT key FROM memories WHERE key IN ({",".join("?" * len(fts_keys))})
                   )""" if fts_keys else
                f"""SELECT {self._COLS}
                   FROM memories
                   WHERE key LIKE ? OR value LIKE ?""",
                (like_pattern, like_pattern, *fts_keys) if fts_keys else
                (like_pattern, like_pattern),
            ).fetchall()
            all_rows = list(rows) + list(like_rows)
        else:
            all_rows = self._db.conn.execute(
                f"SELECT {self._COLS} FROM memories"
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

    def search_count(self, query: str, tags: Optional[List[str]] = None,
                     source: str = "") -> int:
        """Count matching memories without loading data."""
        q = query.strip()
        tag_set: Optional[Set[str]] = set(tags) if tags else None

        if q:
            escaped_q = q.replace('"', '""')
            escaped_q = re.sub(r'[*()\{\}\[\]^~:]', ' ', escaped_q)
            for kw in ('AND', 'OR', 'NOT', 'NEAR'):
                escaped_q = re.sub(r'\b' + kw + r'\b', kw.lower(), escaped_q)
            fts_query = '"' + escaped_q + '"'

            # FTS matches
            try:
                fts_rows = self._db.conn.execute(
                    """SELECT m.key, m.tags
                       FROM memories m
                       JOIN memories_fts fts ON m.rowid = fts.rowid
                       WHERE memories_fts MATCH ?""",
                    (fts_query,),
                ).fetchall()
            except sqlite3.OperationalError:
                fts_rows = []

            MAX_FTS_KEYS = 500
            fts_keys = {r["key"] for r in fts_rows}
            if len(fts_keys) > MAX_FTS_KEYS:
                fts_keys = set(list(fts_keys)[:MAX_FTS_KEYS])
            like_pattern = f"%{q}%"
            if fts_keys:
                like_rows = self._db.conn.execute(
                    f"""SELECT key, tags
                       FROM memories
                       WHERE (key LIKE ? OR value LIKE ?) AND key NOT IN (
                         SELECT key FROM memories WHERE key IN ({",".join("?" * len(fts_keys))})
                       )""",
                    (like_pattern, like_pattern, *fts_keys),
                ).fetchall()
            else:
                like_rows = self._db.conn.execute(
                    """SELECT key, tags
                       FROM memories
                       WHERE key LIKE ? OR value LIKE ?""",
                    (like_pattern, like_pattern),
                ).fetchall()
            all_rows = list(fts_rows) + list(like_rows)
        else:
            all_rows = self._db.conn.execute(
                "SELECT key, tags FROM memories"
            ).fetchall()

        count = 0
        for r in all_rows:
            if tag_set:
                try:
                    row_tags = set(json.loads(r["tags"]))
                except (json.JSONDecodeError, TypeError):
                    row_tags = set()
                if not tag_set.issubset(row_tags):
                    continue
            if source and not r["key"].startswith(f"{source}/"):
                continue
            count += 1
        return count

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
            self.set(m, reset_ttl=False)
        return len(imported)
