"""Tests for memory auto-capture MCP tool (F3: capture_learnings)."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore


@pytest.fixture
def db():
    d = Database(None)
    yield d
    d.close()


@pytest.fixture
def store(db):
    return MemoryStore(db)


def _call_capture(store, db, learnings):
    with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
         patch("src.interfaces.mcp_server._get_db", return_value=db):
        from src.interfaces.mcp_server import capture_learnings
        return capture_learnings(learnings)


class TestCaptureLearnings:
    def test_save_new_learnings(self, store, db):
        result = _call_capture(store, db, [
            {"key": "learn/test1", "value": "First learning", "tags": ["test"], "category": "persistent"},
        ])
        assert result["saved"] == 1
        assert result["updated"] == 0
        assert result["skipped"] == 0
        assert "learn/test1" in result["keys"]

        m = store.get("learn/test1")
        assert m.value == "First learning"

    def test_update_existing_memory_merges(self, store, db):
        store.set(Memory(key="learn/merge", value="Original content", tags=["old"]))

        result = _call_capture(store, db, [
            {"key": "learn/merge", "value": "New content", "tags": ["new"], "category": "persistent"},
        ])
        assert result["updated"] == 1
        assert result["saved"] == 0

        m = store.get("learn/merge")
        assert "Original content" in m.value
        assert "\n---\n" in m.value
        assert "New content" in m.value
        # Tags should be merged
        assert "old" in m.tags
        assert "new" in m.tags

    def test_auto_tagging(self, store, db):
        result = _call_capture(store, db, [
            {"key": "learn/tagged", "value": "Some learning", "tags": [], "category": "session"},
        ])
        m = store.get("learn/tagged")
        assert "source:auto-capture" in m.tags
        assert any(t.startswith("captured:") for t in m.tags)
        assert "category:session" in m.tags

    def test_multiple_learnings(self, store, db):
        result = _call_capture(store, db, [
            {"key": "learn/a", "value": "Learning A", "tags": [], "category": "persistent"},
            {"key": "learn/b", "value": "Learning B", "tags": [], "category": "persistent"},
            {"key": "learn/c", "value": "Learning C", "tags": [], "category": "persistent"},
        ])
        assert result["saved"] == 3
        assert len(result["keys"]) == 3

    def test_skip_empty_key(self, store, db):
        result = _call_capture(store, db, [
            {"key": "", "value": "Some value", "tags": []},
        ])
        assert result["skipped"] == 1
        assert result["saved"] == 0

    def test_skip_empty_value(self, store, db):
        result = _call_capture(store, db, [
            {"key": "learn/empty", "value": "", "tags": []},
        ])
        assert result["skipped"] == 1
        assert result["saved"] == 0

    def test_skip_none_key(self, store, db):
        result = _call_capture(store, db, [
            {"key": None, "value": "val", "tags": []},
        ])
        assert result["skipped"] == 1

    def test_skip_whitespace_only(self, store, db):
        result = _call_capture(store, db, [
            {"key": "   ", "value": "val", "tags": []},
            {"key": "k", "value": "   ", "tags": []},
        ])
        assert result["skipped"] == 2

    def test_mixed_save_update_skip(self, store, db):
        store.set(Memory(key="learn/existing", value="Old", tags=[]))

        result = _call_capture(store, db, [
            {"key": "learn/new1", "value": "New learning", "tags": []},
            {"key": "learn/existing", "value": "Updated", "tags": []},
            {"key": "", "value": "Skip me", "tags": []},
        ])
        assert result["saved"] == 1
        assert result["updated"] == 1
        assert result["skipped"] == 1
        assert len(result["keys"]) == 2

    def test_empty_learnings_list(self, store, db):
        result = _call_capture(store, db, [])
        assert result["saved"] == 0
        assert result["updated"] == 0
        assert result["skipped"] == 0
        assert result["keys"] == []

    def test_default_category(self, store, db):
        result = _call_capture(store, db, [
            {"key": "learn/nocat", "value": "No category specified", "tags": []},
        ])
        m = store.get("learn/nocat")
        assert "category:persistent" in m.tags

    def test_auto_capture_tag_not_duplicated(self, store, db):
        result = _call_capture(store, db, [
            {"key": "learn/dup", "value": "Test", "tags": ["source:auto-capture"]},
        ])
        m = store.get("learn/dup")
        assert m.tags.count("source:auto-capture") == 1
