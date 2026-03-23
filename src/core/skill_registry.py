"""Shared skill registry — SQLite-backed so MCP server and GUI see the same data."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

_STALE_TIMEOUT = 3600  # 1 hour without heartbeat → stale
_DB_PATH = Path.home() / ".contextpilot" / "data.db"


@dataclass
class ExternalSkill:
    """An externally registered skill (via MCP)."""
    name: str
    description: str
    context_hints: List[str] = field(default_factory=list)
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    blocks_served: int = 0

    @property
    def is_alive(self) -> bool:
        return time.time() - self.last_seen < _STALE_TIMEOUT

    @property
    def status(self) -> str:
        return "connected" if self.is_alive else "stale"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "context_hints": self.context_hints,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "blocks_served": self.blocks_served,
            "status": self.status,
        }


def _get_conn():
    """Get a connection to the shared DB. Creates tables if needed."""
    import sqlite3
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_registry (
        name TEXT PRIMARY KEY,
        description TEXT NOT NULL DEFAULT '',
        context_hints TEXT NOT NULL DEFAULT '[]',
        registered_at REAL NOT NULL,
        last_seen REAL NOT NULL,
        blocks_served INTEGER NOT NULL DEFAULT 0
    )""")
    conn.commit()
    return conn


def _row_to_skill(row) -> ExternalSkill:
    hints = []
    try:
        hints = json.loads(row["context_hints"])
    except (json.JSONDecodeError, TypeError):
        pass
    return ExternalSkill(
        name=row["name"],
        description=row["description"],
        context_hints=hints,
        registered_at=row["registered_at"],
        last_seen=row["last_seen"],
        blocks_served=row["blocks_served"],
    )


class SkillRegistry:
    """SQLite-backed registry for external skills.

    Both the MCP server process and the GUI read/write to the same
    ~/.contextpilot/data.db file, so changes are visible across processes.
    """

    _instance: Optional[SkillRegistry] = None

    def __init__(self) -> None:
        self._conn = _get_conn()

    @classmethod
    def instance(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, name: str, description: str, context_hints: Optional[List[str]] = None) -> ExternalSkill:
        now = time.time()
        hints_json = json.dumps(context_hints or [])
        self._conn.execute(
            """INSERT INTO skill_registry (name, description, context_hints, registered_at, last_seen, blocks_served)
               VALUES (?, ?, ?, ?, ?, 0)
               ON CONFLICT(name) DO UPDATE SET
                 description = excluded.description,
                 context_hints = excluded.context_hints,
                 last_seen = excluded.last_seen""",
            (name, description, hints_json, now, now),
        )
        self._conn.commit()
        return ExternalSkill(name=name, description=description,
                             context_hints=context_hints or [],
                             registered_at=now, last_seen=now)

    def unregister(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM skill_registry WHERE name = ?", (name,))
        self._conn.commit()
        return cur.rowcount > 0

    def heartbeat(self, name: str) -> bool:
        now = time.time()
        cur = self._conn.execute(
            "UPDATE skill_registry SET last_seen = ? WHERE name = ?", (now, name),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def get(self, name: str) -> Optional[ExternalSkill]:
        row = self._conn.execute(
            "SELECT * FROM skill_registry WHERE name = ?", (name,),
        ).fetchone()
        return _row_to_skill(row) if row else None

    def list_all(self) -> List[ExternalSkill]:
        rows = self._conn.execute("SELECT * FROM skill_registry ORDER BY name").fetchall()
        return [_row_to_skill(r) for r in rows]

    def list_alive(self) -> List[ExternalSkill]:
        cutoff = time.time() - _STALE_TIMEOUT
        rows = self._conn.execute(
            "SELECT * FROM skill_registry WHERE last_seen > ? ORDER BY name", (cutoff,),
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def list_stale(self) -> List[ExternalSkill]:
        cutoff = time.time() - _STALE_TIMEOUT
        rows = self._conn.execute(
            "SELECT * FROM skill_registry WHERE last_seen <= ? ORDER BY name", (cutoff,),
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def add_blocks_served(self, name: str, count: int) -> None:
        self._conn.execute(
            "UPDATE skill_registry SET blocks_served = blocks_served + ? WHERE name = ?",
            (count, name),
        )
        self._conn.commit()

    def cleanup_stale(self) -> int:
        cutoff = time.time() - _STALE_TIMEOUT
        cur = self._conn.execute(
            "DELETE FROM skill_registry WHERE last_seen <= ?", (cutoff,),
        )
        self._conn.commit()
        return cur.rowcount
