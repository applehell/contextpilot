"""Tests for AnalyticsEngine — all 5 methods + edge cases + API endpoints."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.core.analytics import AnalyticsEngine
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.storage.usage import UsageRecord, UsageStore
from src.web.app import create_app


@pytest.fixture
def engine():
    """Create an AnalyticsEngine with in-memory DB and seeded test data."""
    db = Database(None)
    store = MemoryStore(db)
    usage = UsageStore(db)

    now = time.time()
    day = 86400

    # Create memories with different sources, tags, dates
    store.set(Memory(key="github/repo1", value="Repo 1 info", tags=["code", "python"],
                     created_at=now - 5 * day, updated_at=now - 5 * day))
    store.set(Memory(key="github/repo2", value="Repo 2 info", tags=["code", "go"],
                     created_at=now - 3 * day, updated_at=now - 3 * day))
    store.set(Memory(key="confluence/page1", value="Wiki page", tags=["docs", "python"],
                     created_at=now - 1 * day, updated_at=now - 1 * day))
    store.set(Memory(key="manual/note", value="A manual note", tags=["notes"],
                     created_at=now, updated_at=now))
    store.set(Memory(key="standalone", value="No source prefix", tags=["misc"],
                     created_at=now - 10 * day, updated_at=now - 10 * day))

    # Record some usage
    usage.record_usage([
        UsageRecord(block_hash="hash_a", included=True, created_at=now),
        UsageRecord(block_hash="hash_a", included=True, created_at=now),
        UsageRecord(block_hash="hash_a", included=True, created_at=now),
        UsageRecord(block_hash="hash_b", included=True, created_at=now),
        UsageRecord(block_hash="hash_c", included=False, created_at=now),
    ])

    return AnalyticsEngine(db, store, usage), db


@pytest.fixture
def empty_engine():
    """AnalyticsEngine with an empty database."""
    db = Database(None)
    store = MemoryStore(db)
    usage = UsageStore(db)
    return AnalyticsEngine(db, store, usage), db


class TestTopMemories:
    def test_returns_by_usage(self, engine):
        eng, db = engine
        result = eng.top_memories()
        assert len(result) == 2  # hash_a and hash_b (hash_c excluded=False)
        assert result[0]["block_hash"] == "hash_a"
        assert result[0]["use_count"] == 3
        assert result[1]["block_hash"] == "hash_b"
        assert result[1]["use_count"] == 1
        db.close()

    def test_respects_limit(self, engine):
        eng, db = engine
        result = eng.top_memories(limit=1)
        assert len(result) == 1
        db.close()

    def test_empty_db(self, empty_engine):
        eng, db = empty_engine
        assert eng.top_memories() == []
        db.close()


class TestTopTags:
    def test_counts_tags(self, engine):
        eng, db = engine
        result = eng.top_tags()
        tag_map = {r["tag"]: r["count"] for r in result}
        assert tag_map["python"] == 2
        assert tag_map["code"] == 2
        assert tag_map["go"] == 1
        assert tag_map["docs"] == 1
        db.close()

    def test_respects_limit(self, engine):
        eng, db = engine
        result = eng.top_tags(limit=2)
        assert len(result) == 2
        db.close()

    def test_empty_db(self, empty_engine):
        eng, db = empty_engine
        assert eng.top_tags() == []
        db.close()


class TestConnectorStats:
    def test_groups_by_source(self, engine):
        eng, db = engine
        result = eng.connector_stats()
        source_map = {r["source"]: r["count"] for r in result}
        assert source_map["github"] == 2
        assert source_map["confluence"] == 1
        assert source_map["manual"] == 1
        assert source_map["(none)"] == 1
        db.close()

    def test_sorted_by_count_desc(self, engine):
        eng, db = engine
        result = eng.connector_stats()
        counts = [r["count"] for r in result]
        assert counts == sorted(counts, reverse=True)
        db.close()

    def test_empty_db(self, empty_engine):
        eng, db = empty_engine
        assert eng.connector_stats() == []
        db.close()


class TestMemoryGrowth:
    def test_returns_daily_counts(self, engine):
        eng, db = engine
        result = eng.memory_growth(days=30)
        assert len(result) > 0
        total = sum(r["count"] for r in result)
        assert total == 5
        for r in result:
            assert "date" in r
            assert "count" in r
        db.close()

    def test_respects_days_limit(self, engine):
        eng, db = engine
        result = eng.memory_growth(days=2)
        assert len(result) <= 2
        db.close()

    def test_empty_db(self, empty_engine):
        eng, db = empty_engine
        assert eng.memory_growth() == []
        db.close()


class TestSummary:
    def test_returns_all_fields(self, engine):
        eng, db = engine
        result = eng.summary()
        assert result["total_memories"] == 5
        assert result["total_tags"] > 0
        assert result["sources"] > 0
        assert result["oldest_memory"] is not None
        assert result["newest_memory"] is not None
        db.close()

    def test_empty_db_defaults(self, empty_engine):
        eng, db = empty_engine
        result = eng.summary()
        assert result["total_memories"] == 0
        assert result["total_tags"] == 0
        assert result["sources"] == 0
        assert result["oldest_memory"] is None
        assert result["newest_memory"] is None
        db.close()


class TestAnalyticsAPI:
    @pytest.fixture
    def client(self):
        app = create_app(db_path=None)
        with TestClient(app) as c:
            yield c

    def test_summary_endpoint(self, client):
        r = client.get("/api/analytics/summary")
        assert r.status_code == 200
        data = r.json()
        assert "total_memories" in data
        assert "total_tags" in data
        assert "sources" in data

    def test_top_memories_endpoint(self, client):
        r = client.get("/api/analytics/top-memories?limit=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_top_tags_endpoint(self, client):
        r = client.get("/api/analytics/top-tags?limit=5")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_connector_stats_endpoint(self, client):
        r = client.get("/api/analytics/connector-stats")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_memory_growth_endpoint(self, client):
        r = client.get("/api/analytics/memory-growth?days=7")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
