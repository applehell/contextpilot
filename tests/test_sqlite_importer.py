"""Tests for K3: SQL injection prevention in SQLite importer."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.importers.sqlite import import_generic_sqlite, detect_sqlite_type


def _create_test_db(path: Path, table: str = "notes") -> Path:
    db_path = path / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(f"CREATE TABLE [{table}] (id TEXT, content TEXT, tags TEXT)")
    conn.execute(f"INSERT INTO [{table}] VALUES ('k1', 'hello world', '[\"test\"]')")
    conn.execute(f"INSERT INTO [{table}] VALUES ('k2', 'second note', '[\"demo\"]')")
    conn.commit()
    conn.close()
    return db_path


def test_valid_import(tmp_path: Path) -> None:
    db_path = _create_test_db(tmp_path)
    memories = import_generic_sqlite(db_path, "notes", "id", "content", tag_col="tags")
    assert len(memories) == 2
    assert memories[0].key == "sqlite/k1"
    assert memories[0].value == "hello world"
    assert "test" in memories[0].tags


def test_invalid_key_column_raises(tmp_path: Path) -> None:
    db_path = _create_test_db(tmp_path)
    with pytest.raises(ValueError, match="Column 'nonexistent' not found"):
        import_generic_sqlite(db_path, "notes", "nonexistent", "content")


def test_invalid_value_column_raises(tmp_path: Path) -> None:
    db_path = _create_test_db(tmp_path)
    with pytest.raises(ValueError, match="Column 'bad_col' not found"):
        import_generic_sqlite(db_path, "notes", "id", "bad_col")


def test_invalid_tag_column_raises(tmp_path: Path) -> None:
    db_path = _create_test_db(tmp_path)
    with pytest.raises(ValueError, match="Column 'bad_tag' not found"):
        import_generic_sqlite(db_path, "notes", "id", "content", tag_col="bad_tag")


def test_table_not_found_raises(tmp_path: Path) -> None:
    db_path = _create_test_db(tmp_path)
    with pytest.raises(ValueError, match="Table 'missing' not found"):
        import_generic_sqlite(db_path, "missing", "id", "content")


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
