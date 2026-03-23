"""Project persistence — SQLite-backed project and context storage."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .db import Database


@dataclass
class ProjectMeta:
    name: str
    description: str = ""
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ProjectMeta:
        return cls(
            name=d["name"],
            description=d.get("description", ""),
            created_at=d.get("created_at", time.time()),
            last_used=d.get("last_used", time.time()),
        )


@dataclass
class ContextConfig:
    """A named context configuration within a project (collection of block dicts)."""
    name: str
    blocks: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "blocks": self.blocks}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ContextConfig:
        return cls(name=d["name"], blocks=d.get("blocks", []))


class ProjectStore:
    """SQLite-backed project storage."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def list_projects(self) -> List[ProjectMeta]:
        rows = self._db.conn.execute(
            "SELECT name, description, created_at, last_used FROM projects ORDER BY name"
        ).fetchall()
        return [
            ProjectMeta(name=r["name"], description=r["description"],
                        created_at=r["created_at"], last_used=r["last_used"])
            for r in rows
        ]

    def create(self, meta: ProjectMeta) -> None:
        try:
            self._db.conn.execute(
                "INSERT INTO projects (name, description, created_at, last_used) VALUES (?, ?, ?, ?)",
                (meta.name, meta.description, meta.created_at, meta.last_used),
            )
            self._db.conn.commit()
        except Exception:
            self._db.conn.rollback()
            existing = self._db.conn.execute(
                "SELECT 1 FROM projects WHERE name = ?", (meta.name,)
            ).fetchone()
            if existing:
                raise FileExistsError(f"Project '{meta.name}' already exists.")
            raise

    def load(self, name: str) -> tuple[ProjectMeta, List[ContextConfig]]:
        row = self._db.conn.execute(
            "SELECT name, description, created_at, last_used FROM projects WHERE name = ?",
            (name,),
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"Project '{name}' not found.")
        now = time.time()
        self._db.conn.execute(
            "UPDATE projects SET last_used = ? WHERE name = ?", (now, name)
        )
        self._db.conn.commit()
        meta = ProjectMeta(
            name=row["name"], description=row["description"],
            created_at=row["created_at"], last_used=now,
        )
        ctx_rows = self._db.conn.execute(
            "SELECT name, blocks FROM contexts WHERE project_name = ? ORDER BY id",
            (name,),
        ).fetchall()
        contexts = [
            ContextConfig(name=r["name"], blocks=json.loads(r["blocks"]))
            for r in ctx_rows
        ]
        return meta, contexts

    def save(self, meta: ProjectMeta, contexts: Optional[List[ContextConfig]] = None) -> None:
        if contexts is None:
            _, existing = self.load(meta.name)
            contexts = existing
        meta.last_used = time.time()
        self._db.conn.execute(
            """INSERT INTO projects (name, description, created_at, last_used)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                 description = excluded.description,
                 last_used = excluded.last_used""",
            (meta.name, meta.description, meta.created_at, meta.last_used),
        )
        self._db.conn.execute(
            "DELETE FROM contexts WHERE project_name = ?", (meta.name,)
        )
        for ctx in contexts:
            self._db.conn.execute(
                "INSERT INTO contexts (project_name, name, blocks) VALUES (?, ?, ?)",
                (meta.name, ctx.name, json.dumps(ctx.blocks)),
            )
        self._db.conn.commit()

    def delete(self, name: str) -> None:
        row = self._db.conn.execute(
            "SELECT 1 FROM projects WHERE name = ?", (name,)
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"Project '{name}' not found.")
        self._db.conn.execute("DELETE FROM projects WHERE name = ?", (name,))
        self._db.conn.commit()

    def add_context(self, project_name: str, ctx: ContextConfig) -> None:
        row = self._db.conn.execute(
            "SELECT 1 FROM projects WHERE name = ?", (project_name,)
        ).fetchone()
        if not row:
            raise FileNotFoundError(f"Project '{project_name}' not found.")
        existing = self._db.conn.execute(
            "SELECT 1 FROM contexts WHERE project_name = ? AND name = ?",
            (project_name, ctx.name),
        ).fetchone()
        if existing:
            raise ValueError(f"Context '{ctx.name}' already exists in project '{project_name}'.")
        self._db.conn.execute(
            "INSERT INTO contexts (project_name, name, blocks) VALUES (?, ?, ?)",
            (project_name, ctx.name, json.dumps(ctx.blocks)),
        )
        self._db.conn.commit()

    def remove_context(self, project_name: str, context_name: str) -> None:
        self._db.conn.execute(
            "DELETE FROM contexts WHERE project_name = ? AND name = ?",
            (project_name, context_name),
        )
        self._db.conn.commit()
