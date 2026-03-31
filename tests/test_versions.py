"""Tests for src.storage.versions — memory version history."""
from __future__ import annotations

import pytest

from src.storage.db import Database
from src.storage.versions import VersionStore


@pytest.fixture
def db():
    database = Database(None)  # in-memory
    yield database
    database.close()


@pytest.fixture
def vstore(db: Database) -> VersionStore:
    return VersionStore(db)


class TestRecord:
    def test_record_creates_version(self, vstore: VersionStore) -> None:
        vstore.record("my-key", "value1", ["tag1"], changed_by="test")
        hist = vstore.history("my-key")
        assert len(hist) == 1
        assert hist[0].memory_key == "my-key"
        assert hist[0].value == "value1"
        assert hist[0].tags == ["tag1"]
        assert hist[0].changed_by == "test"

    def test_record_multiple_versions(self, vstore: VersionStore) -> None:
        vstore.record("k", "v1", [])
        vstore.record("k", "v2", ["new-tag"])
        vstore.record("k", "v3", ["new-tag", "extra"])
        assert vstore.count("k") == 3


class TestHistory:
    def test_descending_order(self, vstore: VersionStore) -> None:
        vstore.record("k", "first", [])
        vstore.record("k", "second", [])
        vstore.record("k", "third", [])
        hist = vstore.history("k")
        assert hist[0].value == "third"
        assert hist[-1].value == "first"

    def test_respects_limit(self, vstore: VersionStore) -> None:
        for i in range(10):
            vstore.record("k", f"v{i}", [])
        hist = vstore.history("k", limit=3)
        assert len(hist) == 3

    def test_empty_for_unknown_key(self, vstore: VersionStore) -> None:
        assert vstore.history("nonexistent") == []


class TestCount:
    def test_count_matches(self, vstore: VersionStore) -> None:
        vstore.record("k", "a", [])
        vstore.record("k", "b", [])
        assert vstore.count("k") == 2

    def test_count_zero_for_unknown(self, vstore: VersionStore) -> None:
        assert vstore.count("ghost") == 0


class TestCleanup:
    def test_cleanup_keeps_n(self, vstore: VersionStore) -> None:
        for i in range(15):
            vstore.record("k", f"v{i}", [])
        removed = vstore.cleanup("k", keep=5)
        assert removed == 10
        assert vstore.count("k") == 5
        # Most recent should survive
        hist = vstore.history("k")
        assert hist[0].value == "v14"

    def test_cleanup_noop_when_under_limit(self, vstore: VersionStore) -> None:
        vstore.record("k", "v1", [])
        removed = vstore.cleanup("k", keep=10)
        assert removed == 0
