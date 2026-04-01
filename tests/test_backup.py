"""Tests for BackupManager — create, list, restore, cleanup, export/import."""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.core.backup import BackupManager
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.web.app import create_app


@pytest.fixture
def tmp_data(tmp_path):
    """Create a temp data dir with a real database."""
    db_path = tmp_path / "data.db"
    db = Database(db_path)
    store = MemoryStore(db)
    return tmp_path, db, store


class TestCreateBackup:
    def test_creates_file_in_backups_dir(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        path = bm.create_backup()
        assert path.exists()
        assert path.parent == data_dir / "backups"
        assert path.name.startswith("backup_")
        assert path.name.endswith(".db")
        db.close()

    def test_creates_backups_dir_if_missing(self, tmp_data):
        data_dir, db, store = tmp_data
        assert not (data_dir / "backups").exists()
        bm = BackupManager(data_dir)
        bm.create_backup()
        assert (data_dir / "backups").exists()
        db.close()

    def test_raises_if_no_db(self, tmp_path):
        bm = BackupManager(tmp_path)
        with pytest.raises(FileNotFoundError):
            bm.create_backup()


class TestListBackups:
    def test_returns_correct_metadata(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        bm.create_backup()
        backups = bm.list_backups()
        assert len(backups) == 1
        b = backups[0]
        assert "filename" in b
        assert "created_at" in b
        assert "size_bytes" in b
        assert b["size_bytes"] > 0
        db.close()

    def test_sorted_newest_first(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        bm.create_backup()
        time.sleep(1.1)
        bm.create_backup()
        backups = bm.list_backups()
        assert len(backups) == 2
        assert backups[0]["filename"] > backups[1]["filename"]
        db.close()

    def test_empty_when_no_backups(self, tmp_path):
        bm = BackupManager(tmp_path)
        assert bm.list_backups() == []


class TestRestoreBackup:
    def test_copies_file_correctly(self, tmp_data):
        data_dir, db, store = tmp_data
        store.set(Memory(key="test/a", value="original"))
        db.close()

        bm = BackupManager(data_dir)
        backup_path = bm.create_backup()

        # Modify the DB after backup
        db2 = Database(data_dir / "data.db")
        store2 = MemoryStore(db2)
        store2.set(Memory(key="test/b", value="new"))
        db2.close()

        # Restore
        bm.restore_backup(backup_path.name)

        # Verify restored state
        db3 = Database(data_dir / "data.db")
        store3 = MemoryStore(db3)
        assert store3.count() == 1
        m = store3.get("test/a")
        assert m.value == "original"
        db3.close()

    def test_rejects_path_traversal(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        with pytest.raises(ValueError, match="Invalid backup filename"):
            bm.restore_backup("../../etc/passwd")
        with pytest.raises(ValueError, match="Invalid backup filename"):
            bm.restore_backup("../secret.db")
        with pytest.raises(ValueError, match="Invalid backup filename"):
            bm.restore_backup("foo/bar.db")
        db.close()

    def test_raises_if_not_found(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        with pytest.raises(ValueError, match="Backup not found"):
            bm.restore_backup("backup_20260101_000000.db")
        db.close()


class TestCleanupOldBackups:
    def test_respects_max_backups(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir, max_backups=2)
        # Create 4 backups with different timestamps
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        for i in range(4):
            name = f"backup_20260101_00000{i}.db"
            (backup_dir / name).write_bytes(b"x" * 100)

        deleted = bm.cleanup_old_backups()
        assert deleted == 2
        remaining = bm.list_backups()
        assert len(remaining) == 2
        # Newest should remain
        assert remaining[0]["filename"] == "backup_20260101_000003.db"
        assert remaining[1]["filename"] == "backup_20260101_000002.db"
        db.close()

    def test_no_op_when_under_limit(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir, max_backups=10)
        bm.create_backup()
        assert bm.cleanup_old_backups() == 0
        db.close()


class TestExportImportJson:
    def test_roundtrip_preserves_data(self, tmp_data):
        data_dir, db, store = tmp_data
        store.set(Memory(key="proj/readme", value="Hello", tags=["doc", "intro"], metadata={"source": "manual"}))
        store.set(Memory(key="proj/config", value="key=val", tags=["config"]))

        bm = BackupManager(data_dir)
        exported = bm.export_json(store)
        assert exported["count"] == 2
        assert "exported_at" in exported
        assert len(exported["memories"]) == 2

        # Import into a fresh store
        db2 = Database(None)
        store2 = MemoryStore(db2)
        count = bm.import_json(store2, exported)
        assert count == 2

        m = store2.get("proj/readme")
        assert m.value == "Hello"
        assert set(m.tags) == {"doc", "intro"}
        assert m.metadata["source"] == "manual"

        m2 = store2.get("proj/config")
        assert m2.value == "key=val"
        db.close()
        db2.close()

    def test_import_empty(self, tmp_data):
        data_dir, db, store = tmp_data
        bm = BackupManager(data_dir)
        count = bm.import_json(store, {"memories": []})
        assert count == 0
        db.close()


class TestBackupAPI:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(db_path=None)
        with TestClient(app) as c:
            yield c

    def test_create_and_list(self, client, tmp_path, monkeypatch):
        # The in-memory DB won't have a file to copy, so we test via the API
        # which uses ProfileManager. For unit tests, the BackupManager tests above
        # cover the logic. Here we just ensure the endpoints are wired up.
        r = client.get("/api/backups")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_restore_invalid_filename(self, client):
        r = client.post("/api/backups/../../etc/passwd/restore")
        assert r.status_code in (400, 404, 422)

    def test_delete_nonexistent(self, client):
        r = client.delete("/api/backups/backup_20260101_000000.db")
        assert r.status_code in (400, 404)
