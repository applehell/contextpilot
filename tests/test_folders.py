"""Tests for the FolderManager and file indexer."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.storage.db import Database
from src.storage.folders import FolderManager, FOLDERS_CONFIG
from src.storage.memory import MemoryStore


@pytest.fixture
def fm(tmp_path, monkeypatch):
    config = tmp_path / "folders.json"
    monkeypatch.setattr("src.storage.folders.FOLDERS_CONFIG", config)
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    return FolderManager()


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    return MemoryStore(db)


@pytest.fixture
def sample_folder(tmp_path):
    folder = tmp_path / "docs"
    folder.mkdir()
    (folder / "readme.md").write_text("# Hello\nThis is a test.")
    (folder / "notes.txt").write_text("Some notes here.")
    (folder / "config.json").write_text('{"key": "value"}')
    sub = folder / "sub"
    sub.mkdir()
    (sub / "deep.txt").write_text("Deep content.")
    return folder


class TestAdd:
    def test_add_source(self, fm, sample_folder):
        s = fm.add("docs", str(sample_folder), description="Test docs")
        assert s.name == "docs"
        assert s.path == str(sample_folder)
        assert s.enabled is True

    def test_add_duplicate_fails(self, fm, sample_folder):
        fm.add("docs", str(sample_folder))
        with pytest.raises(ValueError, match="already exists"):
            fm.add("docs", str(sample_folder))

    def test_add_invalid_name(self, fm, sample_folder):
        with pytest.raises(ValueError, match="alphanumeric"):
            fm.add("bad name!", str(sample_folder))

    def test_add_invalid_path(self, fm):
        with pytest.raises(ValueError, match="not a directory"):
            fm.add("nope", "/nonexistent/path")


class TestList:
    def test_list_empty(self, fm):
        assert fm.list() == []

    def test_list_after_add(self, fm, sample_folder):
        fm.add("a", str(sample_folder))
        fm.add("b", str(sample_folder))
        names = [s.name for s in fm.list()]
        assert "a" in names
        assert "b" in names


class TestRemove:
    def test_remove_source(self, fm, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.remove("docs")
        assert fm.get("docs") is None

    def test_remove_nonexistent_fails(self, fm):
        with pytest.raises(KeyError):
            fm.remove("nope")


class TestUpdate:
    def test_update_enabled(self, fm, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.update("docs", enabled=False)
        assert fm.get("docs").enabled is False

    def test_update_extensions(self, fm, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.update("docs", extensions=[".md", ".txt"])
        assert fm.get("docs").extensions == [".md", ".txt"]


class TestScan:
    def test_scan_indexes_files(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        result = fm.scan("docs", store)
        assert result.added == 4  # readme.md, notes.txt, config.json, sub/deep.txt
        assert result.errors == []

    def test_scan_creates_memories(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        memories = store.list()
        keys = [m.key for m in memories]
        assert "folder/docs/readme.md" in keys
        assert "folder/docs/notes.txt" in keys
        assert "folder/docs/sub/deep.txt" in keys

    def test_scan_idempotent(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        result = fm.scan("docs", store)
        assert result.added == 0
        assert result.skipped == 4

    def test_scan_detects_changes(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        (sample_folder / "notes.txt").write_text("Updated!")
        result = fm.scan("docs", store)
        assert result.updated == 1
        assert result.skipped == 3

    def test_scan_removes_deleted(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        (sample_folder / "config.json").unlink()
        result = fm.scan("docs", store)
        assert result.removed == 1

    def test_scan_respects_extensions(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder), extensions=[".md"])
        result = fm.scan("docs", store)
        assert result.added == 1
        keys = [m.key for m in store.list()]
        assert "folder/docs/readme.md" in keys
        assert "folder/docs/notes.txt" not in keys

    def test_scan_non_recursive(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder), recursive=False)
        result = fm.scan("docs", store)
        keys = [m.key for m in store.list()]
        assert "folder/docs/sub/deep.txt" not in keys

    def test_scan_tags(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        m = store.get("folder/docs/readme.md")
        assert "folder" in m.tags
        assert "docs" in m.tags
        assert "md" in m.tags

    def test_scan_metadata(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        m = store.get("folder/docs/readme.md")
        assert m.metadata["source"] == "folder"
        assert m.metadata["folder_source"] == "docs"
        assert "content_hash" in m.metadata

    def test_scan_updates_source_stats(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        s = fm.get("docs")
        assert s.last_scan is not None
        assert s.indexed_files == 4


class TestPurge:
    def test_purge_removes_all(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.scan("docs", store)
        count = fm.purge("docs", store)
        assert count == 4
        assert len(store.list()) == 0


class TestScanAll:
    def test_scan_all(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        results = fm.scan_all(store)
        assert "docs" in results
        assert results["docs"].added == 4

    def test_scan_all_skips_disabled(self, fm, store, sample_folder):
        fm.add("docs", str(sample_folder))
        fm.update("docs", enabled=False)
        results = fm.scan_all(store)
        assert "docs" not in results
