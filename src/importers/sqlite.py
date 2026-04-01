"""Import memories from external SQLite databases (memory-mcp, generic)."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.storage.memory import Memory


def _parse_json_safe(text: str, fallback: Any = None) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return fallback if fallback is not None else {}


def import_memory_mcp(path: Path, include_deleted: bool = False) -> List[Memory]:
    """Import from a memory-mcp SQLite database.

    Schema expected:
        memories(id, content, type, importance, summary, metadata, is_deleted, created_at, ...)
        entities(id, name, type, metadata, created_at)
        memory_entities(memory_id, entity_id)
    """
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if "memories" not in tables:
        conn.close()
        raise ValueError("Not a memory-mcp database: 'memories' table not found.")

    where = "" if include_deleted else "WHERE is_deleted = 0"
    rows = conn.execute(
        f"SELECT id, content, type, importance, summary, metadata, created_at FROM memories {where}"
    ).fetchall()

    entity_map: Dict[str, List[str]] = {}
    if "memory_entities" in tables and "entities" in tables:
        for r in conn.execute(
            "SELECT me.memory_id, e.name FROM memory_entities me JOIN entities e ON me.entity_id = e.id"
        ).fetchall():
            entity_map.setdefault(r[0], []).append(r[1])

    conn.close()

    memories: List[Memory] = []
    for row in rows:
        meta = _parse_json_safe(row["metadata"])
        tags_from_meta = meta.get("tags", []) if isinstance(meta, dict) else []

        tags = ["memory-mcp", row["type"]]
        tags.extend(tags_from_meta)

        entities = entity_map.get(row["id"], [])
        if entities:
            tags.extend(f"entity:{e}" for e in entities)

        created = row["created_at"] / 1000.0 if row["created_at"] > 1e12 else float(row["created_at"])

        key = f"mcp/{row['id']}"
        value = row["content"]
        if row["summary"]:
            value = f"{row['summary']}\n\n{value}"

        memories.append(Memory(
            key=key,
            value=value,
            tags=list(dict.fromkeys(tags)),
            metadata={
                "source": "memory-mcp",
                "original_id": row["id"],
                "type": row["type"],
                "importance": row["importance"],
            },
            created_at=created,
            updated_at=time.time(),
        ))

    return memories


def detect_sqlite_type(path: Path) -> Optional[str]:
    """Detect which type of SQLite memory database a file is.

    Returns: 'memory-mcp', 'context-pilot', or None if unknown.
    """
    try:
        conn = sqlite3.connect(str(path))
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        conn.close()
    except sqlite3.Error:
        return None

    if "memories" in tables and "memory_entities" in tables:
        return "memory-mcp"
    if "memories" in tables and "projects" in tables:
        return "context-pilot"
    return None


def import_generic_sqlite(path: Path, table: str, key_col: str, value_col: str,
                          tag_col: Optional[str] = None) -> List[Memory]:
    """Import from any SQLite table with configurable column mapping."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row

    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    if table not in tables:
        conn.close()
        raise ValueError(f"Table '{table}' not found in database.")

    columns = {row[1] for row in conn.execute(f"PRAGMA table_info([{table}])").fetchall()}
    if key_col not in columns:
        conn.close()
        raise ValueError(f"Column '{key_col}' not found in table '{table}'")
    if value_col not in columns:
        conn.close()
        raise ValueError(f"Column '{value_col}' not found in table '{table}'")
    if tag_col and tag_col not in columns:
        conn.close()
        raise ValueError(f"Column '{tag_col}' not found in table '{table}'")

    rows = conn.execute(f"SELECT * FROM [{table}]").fetchall()
    conn.close()

    now = time.time()
    memories: List[Memory] = []
    for row in rows:
        row_dict = dict(row)
        key_val = str(row_dict.get(key_col, ""))
        value_val = str(row_dict.get(value_col, ""))
        if not key_val or not value_val:
            continue

        tags = ["sqlite-import"]
        if tag_col and tag_col in row_dict:
            raw = row_dict[tag_col]
            if isinstance(raw, str):
                parsed = _parse_json_safe(raw, None)
                if isinstance(parsed, list):
                    tags.extend(str(t) for t in parsed)
                else:
                    tags.append(raw)

        memories.append(Memory(
            key=f"sqlite/{key_val}",
            value=value_val,
            tags=tags,
            metadata={"source": str(path), "table": table},
            created_at=now,
            updated_at=now,
        ))

    return memories
