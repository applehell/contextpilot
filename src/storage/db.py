"""SQLite database engine — connection management and schema migrations."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 6

MIGRATIONS = {
    1: [
        # -- projects table --
        """CREATE TABLE IF NOT EXISTS projects (
            name TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            last_used REAL NOT NULL
        )""",
        # -- contexts table --
        """CREATE TABLE IF NOT EXISTS contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_name TEXT NOT NULL REFERENCES projects(name) ON DELETE CASCADE,
            name TEXT NOT NULL,
            blocks TEXT NOT NULL DEFAULT '[]',
            UNIQUE(project_name, name)
        )""",
        # -- memories table --
        """CREATE TABLE IF NOT EXISTS memories (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            tags TEXT NOT NULL DEFAULT '[]',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )""",
        # -- FTS5 virtual table for memory search --
        """CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
            key, value, content='memories', content_rowid='rowid'
        )""",
        # -- triggers to keep FTS in sync --
        """CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts(rowid, key, value)
            VALUES (new.rowid, new.key, new.value);
        END""",
        """CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, key, value)
            VALUES ('delete', old.rowid, old.key, old.value);
        END""",
        """CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
            INSERT INTO memories_fts(memories_fts, rowid, key, value)
            VALUES ('delete', old.rowid, old.key, old.value);
            INSERT INTO memories_fts(rowid, key, value)
            VALUES (new.rowid, new.key, new.value);
        END""",
    ],
    2: [
        # -- block usage tracking --
        """CREATE TABLE IF NOT EXISTS block_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_hash TEXT NOT NULL,
            project_name TEXT,
            context_name TEXT,
            skill_name TEXT,
            model_id TEXT,
            included INTEGER NOT NULL DEFAULT 1,
            token_count INTEGER NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_block_usage_hash ON block_usage(block_hash)""",
        """CREATE INDEX IF NOT EXISTS idx_block_usage_project ON block_usage(project_name)""",
        """CREATE INDEX IF NOT EXISTS idx_block_usage_skill ON block_usage(skill_name)""",
        # -- user feedback on assemblies --
        """CREATE TABLE IF NOT EXISTS assembly_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assembly_id TEXT NOT NULL,
            block_hash TEXT NOT NULL,
            helpful INTEGER NOT NULL,
            created_at REAL NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_feedback_block ON assembly_feedback(block_hash)""",
        """CREATE INDEX IF NOT EXISTS idx_feedback_assembly ON assembly_feedback(assembly_id)""",
        # -- computed block weights (cache for weight adjuster) --
        """CREATE TABLE IF NOT EXISTS block_weights (
            block_hash TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            weight REAL NOT NULL DEFAULT 1.0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            feedback_score REAL NOT NULL DEFAULT 0.0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (block_hash, project_name)
        )""",
        # -- skill adaption profiles --
        """CREATE TABLE IF NOT EXISTS skill_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            skill_name TEXT NOT NULL,
            model_id TEXT NOT NULL,
            avg_tokens INTEGER NOT NULL DEFAULT 0,
            inclusion_rate REAL NOT NULL DEFAULT 1.0,
            preferred_priority TEXT NOT NULL DEFAULT 'medium',
            updated_at REAL NOT NULL,
            UNIQUE(skill_name, model_id)
        )""",
    ],
    3: [
        # -- fix block_weights: project_name must not be NULL (sentinel '') --
        """UPDATE block_weights SET project_name = '' WHERE project_name IS NULL""",
        """CREATE TABLE IF NOT EXISTS block_weights_new (
            block_hash TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            weight REAL NOT NULL DEFAULT 1.0,
            usage_count INTEGER NOT NULL DEFAULT 0,
            feedback_score REAL NOT NULL DEFAULT 0.0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (block_hash, project_name)
        )""",
        """INSERT OR IGNORE INTO block_weights_new
           SELECT block_hash, project_name, weight, usage_count, feedback_score, updated_at
           FROM block_weights""",
        """DROP TABLE block_weights""",
        """ALTER TABLE block_weights_new RENAME TO block_weights""",
    ],
    4: [
        # -- per-skill block relevance tracking --
        """CREATE TABLE IF NOT EXISTS skill_block_relevance (
            skill_name TEXT NOT NULL,
            block_hash TEXT NOT NULL,
            score REAL NOT NULL DEFAULT 0.5,
            included_count INTEGER NOT NULL DEFAULT 0,
            dropped_count INTEGER NOT NULL DEFAULT 0,
            feedback_sum REAL NOT NULL DEFAULT 0.0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (skill_name, block_hash)
        )""",
        """CREATE INDEX IF NOT EXISTS idx_sbr_skill ON skill_block_relevance(skill_name)""",
        """CREATE INDEX IF NOT EXISTS idx_sbr_score ON skill_block_relevance(skill_name, score DESC)""",
        # -- per-skill budget allocation --
        """CREATE TABLE IF NOT EXISTS skill_budget_allocation (
            skill_name TEXT NOT NULL,
            project_name TEXT NOT NULL DEFAULT '',
            token_budget INTEGER NOT NULL DEFAULT 0,
            efficiency REAL NOT NULL DEFAULT 1.0,
            updated_at REAL NOT NULL,
            PRIMARY KEY (skill_name, project_name)
        )""",
    ],
    5: [
        # -- external skill registry (shared between MCP server + GUI) --
        """CREATE TABLE IF NOT EXISTS skill_registry (
            name TEXT PRIMARY KEY,
            description TEXT NOT NULL DEFAULT '',
            context_hints TEXT NOT NULL DEFAULT '[]',
            registered_at REAL NOT NULL,
            last_seen REAL NOT NULL,
            blocks_served INTEGER NOT NULL DEFAULT 0
        )""",
    ],
    6: [
        # -- memory activity log (tracks MCP memory operations) --
        """CREATE TABLE IF NOT EXISTS memory_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            operation TEXT NOT NULL,
            memory_key TEXT NOT NULL,
            detail TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL
        )""",
        """CREATE INDEX IF NOT EXISTS idx_memory_activity_time ON memory_activity(created_at DESC)""",
        """CREATE INDEX IF NOT EXISTS idx_memory_activity_key ON memory_activity(memory_key)""",
    ],
}


class Database:
    """Thin wrapper around a SQLite database with schema versioning."""

    def __init__(self, path: Optional[Path] = None, check_same_thread: bool = True) -> None:
        if path is None:
            self._conn = sqlite3.connect(":memory:", check_same_thread=check_same_thread)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        return self._conn

    def close(self) -> None:
        self._conn.close()

    def _current_version(self) -> int:
        try:
            row = self._conn.execute("PRAGMA user_version").fetchone()
            return row[0] if row else 0
        except sqlite3.OperationalError:
            return 0

    def _set_version(self, version: int) -> None:
        self._conn.execute(f"PRAGMA user_version = {version}")

    def _migrate(self) -> None:
        current = self._current_version()
        for ver in sorted(MIGRATIONS.keys()):
            if ver > current:
                for stmt in MIGRATIONS[ver]:
                    self._conn.execute(stmt)
                self._set_version(ver)
        self._conn.commit()
