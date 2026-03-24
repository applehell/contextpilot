"""Tests for the memory activity log."""
from __future__ import annotations

import time

import pytest

from src.storage.db import Database
from src.storage.memory_activity import MemoryActivityLog, ActivityEntry


@pytest.fixture
def log():
    db = Database()  # in-memory
    return MemoryActivityLog(db)


class TestRecord:
    def test_record_and_recent(self, log):
        log.record("created", "test-key", "100 chars")
        entries = log.recent()
        assert len(entries) == 1
        assert entries[0].operation == "created"
        assert entries[0].memory_key == "test-key"
        assert entries[0].detail == "100 chars"

    def test_multiple_entries_ordered(self, log):
        log.record("created", "a")
        log.record("updated", "b")
        log.record("deleted", "c")
        entries = log.recent()
        assert len(entries) == 3
        assert entries[0].memory_key == "c"  # most recent first
        assert entries[2].memory_key == "a"

    def test_limit(self, log):
        for i in range(10):
            log.record("created", f"key-{i}")
        entries = log.recent(limit=3)
        assert len(entries) == 3

    def test_empty(self, log):
        entries = log.recent()
        assert entries == []


class TestClear:
    def test_clear_old(self, log):
        log.record("created", "old-key")
        # Manually set the timestamp to 60 days ago
        log._db.conn.execute(
            "UPDATE memory_activity SET created_at = ?",
            (time.time() - 60 * 86400,),
        )
        log._db.conn.commit()
        log.record("created", "new-key")

        deleted = log.clear(older_than_days=30)
        assert deleted == 1
        entries = log.recent()
        assert len(entries) == 1
        assert entries[0].memory_key == "new-key"


class TestActivityEntry:
    def test_age_label_just_now(self):
        e = ActivityEntry("created", "k", "", time.time())
        assert e.age_label == "just now"

    def test_age_label_minutes(self):
        e = ActivityEntry("created", "k", "", time.time() - 300)
        assert "m ago" in e.age_label

    def test_age_label_hours(self):
        e = ActivityEntry("created", "k", "", time.time() - 7200)
        assert "h ago" in e.age_label

    def test_age_label_days(self):
        e = ActivityEntry("created", "k", "", time.time() - 172800)
        assert "d ago" in e.age_label
