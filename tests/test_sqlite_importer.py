"""Tests for K3: SQL injection prevention in SQLite importer."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from src.importers.sqlite import detect_sqlite_type


def _create_test_db(path: Path, table: str = "notes") -> Path:
    db_path = path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(f"CREATE TABLE [{table}] (id TEXT, content TEXT, tags TEXT)")
    conn.execute(f"INSERT INTO [{table}] VALUES ('k1', 'hello world', '[\"test\"]')")
    conn.execute(f"INSERT INTO [{table}] VALUES ('k2', 'second note', '[\"demo\"]')")
    conn.commit()
    conn.close()
    return db_path


def test_detect_sqlite_type_unknown(tmp_path: Path) -> None:
    db_path = _create_test_db(tmp_path)
    assert detect_sqlite_type(db_path) is None


def test_detect_sqlite_type_memory_mcp(tmp_path: Path) -> None:
    db_path = tmp_path / "mcp.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE memories (id TEXT)")
    conn.execute("CREATE TABLE memory_entities (memory_id TEXT, entity_id TEXT)")
    conn.commit()
    conn.close()
    assert detect_sqlite_type(db_path) == "memory-mcp"
