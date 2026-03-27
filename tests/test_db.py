"""Tests for src.storage.db — Database engine."""
from __future__ import annotations

import sqlite3

import pytest
from pathlib import Path

from src.storage.db import Database, SCHEMA_VERSION, MIGRATIONS


class TestDatabase:
    def test_in_memory(self) -> None:
        db = Database(None)
        assert db.conn is not None
        db.close()

    def test_file_based(self, tmp_path: Path) -> None:
        db_path = tmp_path / "sub" / "test.db"
        db = Database(db_path)
        assert db_path.exists()
        db.close()

    def test_schema_version(self) -> None:
        db = Database(None)
        version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        db.close()

    def test_tables_created(self) -> None:
        db = Database(None)
        tables = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "projects" in tables
        assert "contexts" in tables
        assert "memories" in tables
        assert "memories_fts" in tables
        db.close()

    def test_foreign_keys_enabled(self) -> None:
        db = Database(None)
        fk = db.conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        db.close()

    def test_reopen_no_error(self, tmp_path: Path) -> None:
        db_path = tmp_path / "reopen.db"
        db1 = Database(db_path)
        db1.conn.execute("INSERT INTO projects (name, description, created_at, last_used) VALUES (?, ?, ?, ?)",
                         ("test", "", 1.0, 1.0))
        db1.conn.commit()
        db1.close()
        db2 = Database(db_path)
        row = db2.conn.execute("SELECT name FROM projects").fetchone()
        assert row["name"] == "test"
        db2.close()


class TestMigration:
    def test_migration_from_v1_to_current(self, tmp_path: Path) -> None:
        """Create a DB with only v1 schema, then reopen with Database to trigger v2+v3 migrations."""
        db_path = tmp_path / "migrate.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        for stmt in MIGRATIONS[1]:
            conn.execute(stmt)
        conn.execute(f"PRAGMA user_version = 1")
        conn.commit()
        conn.close()

        db = Database(db_path)
        version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

        tables = {r[0] for r in db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "block_usage" in tables
        assert "assembly_feedback" in tables
        assert "block_weights" in tables
        # v12: skill_profiles and skill_budget_allocation dropped
        assert "skill_profiles" not in tables
        assert "skill_budget_allocation" not in tables
        db.close()

    def test_migration_from_v2_to_current(self, tmp_path: Path) -> None:
        """Create a DB at v2 with a NULL project_name row, verify v3 migration fixes it."""
        db_path = tmp_path / "migrate_v2.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        # Apply v1 migrations
        for stmt in MIGRATIONS[1]:
            conn.execute(stmt)
        # Apply v2 migrations except block_weights — create it without NOT NULL
        for stmt in MIGRATIONS[2]:
            if "block_weights" in stmt:
                continue
            conn.execute(stmt)
        # Create block_weights with nullable project_name (the pre-v3 bug)
        conn.execute("""CREATE TABLE IF NOT EXISTS block_weights (
            block_hash TEXT NOT NULL,
            project_name TEXT,
            weight REAL NOT NULL DEFAULT 1.0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            feedback_score REAL NOT NULL DEFAULT 0.0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (block_hash, project_name)
        )""")
        conn.execute(f"PRAGMA user_version = 2")
        # Insert a row with NULL project_name (the bug v3 fixes)
        conn.execute(
            "INSERT INTO block_weights (block_hash, project_name, weight, usage_count, feedback_score, updated_at) "
            "VALUES (?, NULL, 1.0, 5, 0.5, 1.0)",
            ("abc123",),
        )
        conn.commit()
        conn.close()

        db = Database(db_path)
        version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

        row = db.conn.execute(
            "SELECT project_name FROM block_weights WHERE block_hash = ?", ("abc123",)
        ).fetchone()
        assert row is not None
        assert row["project_name"] == ""  # NULL migrated to sentinel ''
        db.close()

    def test_fresh_db_is_at_current_version(self) -> None:
        db = Database(None)
        version = db.conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION
        db.close()
