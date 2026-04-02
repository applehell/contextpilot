"""Tests for enhanced BackupManager — auto_backup, needs_backup, verify_backup, backup_age_hours."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.core.backup import BackupManager
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore


@pytest.fixture
def tmp_data(tmp_path):
    db_path = tmp_path / "data.db"
    db = Database(db_path)
    store = MemoryStore(db)
    store.set(Memory(key="test/x", value="hello"))
    yield tmp_path, db, store
    db.close()


class TestAutoBackup:
    def test_creates_backup(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        path = bm.auto_backup(max_backups=7)
        assert path.exists()
        assert len(bm.list_backups()) == 1

    def test_rotates_old_backups(self, tmp_data):
        data_dir, db, store = tmp_data
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for i in range(5):
            name = f"backup_20260101_00000{i}.db"
            (backup_dir / name).write_bytes(b"x" * 100)

        bm = BackupManager(data_dir)
        bm.auto_backup(max_backups=3)
        backups = bm.list_backups()
        assert len(backups) == 3
        # newest should be the auto-created one (today's date)
        assert backups[0]["filename"] > "backup_20260101"

    def test_max_backups_one(self, tmp_data):
        data_dir, db, store = tmp_data
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for i in range(3):
            name = f"backup_20260101_00000{i}.db"
            (backup_dir / name).write_bytes(b"x" * 100)

        bm = BackupManager(data_dir)
        bm.auto_backup(max_backups=1)
        assert len(bm.list_backups()) == 1


class TestNeedsBackup:
    def test_true_when_no_backups(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        assert bm.needs_backup() is True

    def test_false_after_fresh_backup(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        bm.create_backup()
        assert bm.needs_backup(max_age_hours=24) is False

    def test_true_when_backup_old(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        bm.create_backup()
        # A fresh backup is 0 hours old, so max_age_hours=0 should trigger
        assert bm.needs_backup(max_age_hours=0) is True

    def test_respects_max_age(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        bm.create_backup()
        assert bm.needs_backup(max_age_hours=1) is False
        assert bm.needs_backup(max_age_hours=0) is True


class TestBackupAgeHours:
    def test_none_when_no_backups(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        assert bm.backup_age_hours() is None

    def test_returns_small_value_after_fresh_backup(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        bm.create_backup()
        age = bm.backup_age_hours()
        assert age is not None
        assert age < 0.1  # less than 6 minutes

    def test_increases_with_older_backups(self, tmp_data):
        data_dir, db, store = tmp_data
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        import os
        old_file = backup_dir / "backup_20250101_000000.db"
        old_file.write_bytes(b"x")
        # Set mtime to 48 hours ago
        old_ts = time.time() - 48 * 3600
        os.utime(str(old_file), (old_ts, old_ts))
        bm = BackupManager(data_dir)
        age = bm.backup_age_hours()
        assert age is not None
        assert age > 24


class TestVerifyBackup:
    def test_valid_backup(self, tmp_path):
        db_path = tmp_path / "data.db"
        db = Database(db_path)
        s = MemoryStore(db)
        s.set(Memory(key="test/v", value="verify"))
        db.close()
        bm = BackupManager(tmp_path)
        path = bm.create_backup()
        result = bm.verify_backup(path.name)
        assert result["valid"] is True
        assert result["memory_count"] >= 1
        assert isinstance(result["schema_version"], int)

    def test_invalid_file(self, tmp_data):
        data_dir, db, store = tmp_data
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        bad_file = backup_dir / "backup_20260101_000000.db"
        bad_file.write_text("this is not a sqlite database")
        bm = BackupManager(data_dir)
        result = bm.verify_backup("backup_20260101_000000.db")
        assert result["valid"] is False
        assert "error" in result

    def test_nonexistent_backup(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        with pytest.raises(ValueError, match="Backup not found"):
            bm.verify_backup("backup_20260101_999999.db")

    def test_rejects_invalid_filename(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        with pytest.raises(ValueError, match="Invalid backup filename"):
            bm.verify_backup("../../etc/passwd")
