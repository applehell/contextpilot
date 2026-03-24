"""Context templates — predefined assembly configurations."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import List

from .db import Database


@dataclass
class ContextTemplate:
    name: str
    description: str = ""
    tag_filter: List[str] = field(default_factory=list)
    key_filter: str = ""
    budget: int = 4000
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class TemplateStore:

    def __init__(self, db: Database) -> None:
        self._db = db

    def list(self) -> List[ContextTemplate]:
        rows = self._db.conn.execute(
            "SELECT name, description, tag_filter, key_filter, budget, created_at, updated_at FROM context_templates ORDER BY name"
        ).fetchall()
        return [ContextTemplate(
            name=r["name"], description=r["description"],
            tag_filter=json.loads(r["tag_filter"]), key_filter=r["key_filter"],
            budget=r["budget"], created_at=r["created_at"], updated_at=r["updated_at"],
        ) for r in rows]

    def get(self, name: str) -> ContextTemplate:
        row = self._db.conn.execute(
            "SELECT name, description, tag_filter, key_filter, budget, created_at, updated_at FROM context_templates WHERE name = ?",
            (name,),
        ).fetchone()
        if not row:
            raise KeyError(f"Template '{name}' not found")
        return ContextTemplate(
            name=row["name"], description=row["description"],
            tag_filter=json.loads(row["tag_filter"]), key_filter=row["key_filter"],
            budget=row["budget"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    def save(self, template: ContextTemplate) -> None:
        now = time.time()
        self._db.conn.execute(
            """INSERT INTO context_templates (name, description, tag_filter, key_filter, budget, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 description=excluded.description, tag_filter=excluded.tag_filter,
                 key_filter=excluded.key_filter, budget=excluded.budget, updated_at=?""",
            (template.name, template.description, json.dumps(template.tag_filter),
             template.key_filter, template.budget, now, now, now),
        )
        self._db.conn.commit()

    def delete(self, name: str) -> None:
        cursor = self._db.conn.execute("DELETE FROM context_templates WHERE name = ?", (name,))
        self._db.conn.commit()
        if cursor.rowcount == 0:
            raise KeyError(f"Template '{name}' not found")
