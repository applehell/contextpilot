"""Tests for F9 — Memory Categories with Retention Policies."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.web.app import create_app


@pytest.fixture
def db():
    return Database(path=None)


@pytest.fixture
def store(db):
    return MemoryStore(db)


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


class TestCategoryDefaults:
    def test_default_persistent(self) -> None:
        m = Memory(key="test", value="hello")
        assert m.category == "persistent"

    def test_from_dict_default(self) -> None:
        m = Memory.from_dict({"key": "x", "value": "y"})
        assert m.category == "persistent"

    def test_to_dict_includes_category(self) -> None:
        m = Memory(key="x", value="y", category="session")
        d = m.to_dict()
        assert d["category"] == "session"

    def test_from_dict_preserves_category(self) -> None:
        m = Memory.from_dict({"key": "x", "value": "y", "category": "ephemeral"})
        assert m.category == "ephemeral"


class TestCategoryAutoTTL:
    def test_session_auto_sets_expires_at(self, store) -> None:
        m = Memory(key="session-test", value="temp data", category="session")
        assert m.expires_at is None
        store.set(m)
        saved = store.get("session-test")
        assert saved.expires_at is not None
        expected = time.time() + 86400
        assert abs(saved.expires_at - expected) < 5

    def test_ephemeral_auto_sets_expires_at(self, store) -> None:
        m = Memory(key="ephemeral-test", value="short-lived", category="ephemeral")
        store.set(m)
        saved = store.get("ephemeral-test")
        assert saved.expires_at is not None
        expected = time.time() + 3600
        assert abs(saved.expires_at - expected) < 5

    def test_persistent_no_auto_ttl(self, store) -> None:
        m = Memory(key="persist-test", value="forever", category="persistent")
        store.set(m)
        saved = store.get("persist-test")
        assert saved.expires_at is None

    def test_explicit_expires_at_not_overridden(self, store) -> None:
        custom_exp = time.time() + 999
        m = Memory(key="custom-ttl", value="data", category="session", expires_at=custom_exp)
        store.set(m)
        saved = store.get("custom-ttl")
        assert abs(saved.expires_at - custom_exp) < 2

    def test_update_does_not_reset_category_ttl(self, store) -> None:
        m = Memory(key="up-test", value="v1", category="session")
        store.set(m)
        first = store.get("up-test")
        original_exp = first.expires_at

        m2 = Memory(key="up-test", value="v2", category="session", expires_at=original_exp)
        store.set(m2)
        updated = store.get("up-test")
        assert updated.value == "v2"


class TestCategoryFiltering:
    def test_list_filter_by_category(self, store) -> None:
        store.set(Memory(key="p1", value="persistent 1", category="persistent"))
        store.set(Memory(key="s1", value="session 1", category="session"))
        store.set(Memory(key="e1", value="ephemeral 1", category="ephemeral"))

        persistent = store.list(category="persistent")
        assert len(persistent) == 1
        assert persistent[0].key == "p1"

        session = store.list(category="session")
        assert len(session) == 1
        assert session[0].key == "s1"

        ephemeral = store.list(category="ephemeral")
        assert len(ephemeral) == 1
        assert ephemeral[0].key == "e1"

    def test_list_no_filter_returns_all(self, store) -> None:
        store.set(Memory(key="a", value="v", category="persistent"))
        store.set(Memory(key="b", value="v", category="session"))
        all_mems = store.list()
        assert len(all_mems) == 2


class TestCategoryStats:
    def test_stats_correct_counts(self, store) -> None:
        store.set(Memory(key="p1", value="v", category="persistent"))
        store.set(Memory(key="p2", value="v", category="persistent"))
        store.set(Memory(key="s1", value="v", category="session"))
        store.set(Memory(key="e1", value="v", category="ephemeral"))

        stats = store.category_stats()
        assert stats["persistent"] == 2
        assert stats["session"] == 1
        assert stats["ephemeral"] == 1

    def test_stats_empty(self, store) -> None:
        stats = store.category_stats()
        assert stats == {"persistent": 0, "session": 0, "ephemeral": 0}


class TestMigration:
    def test_migration_adds_category_column(self) -> None:
        db = Database(path=None)
        row = db.conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        assert "category" in row["sql"]

    def test_category_default_value(self) -> None:
        db = Database(path=None)
        db.conn.execute(
            "INSERT INTO memories (key, value, tags, metadata, created_at, updated_at) "
            "VALUES ('test', 'val', '[]', '{}', 0, 0)"
        )
        db.conn.commit()
        row = db.conn.execute("SELECT category FROM memories WHERE key='test'").fetchone()
        assert row["category"] == "persistent"


class TestAPICategory:
    def test_create_with_category(self, client) -> None:
        r = client.post("/api/memories", json={
            "key": "cat-test", "value": "hello", "category": "session"
        })
        assert r.status_code == 201

        r = client.get("/api/memories/cat-test")
        assert r.status_code == 200
        assert r.json()["category"] == "session"

    def test_create_default_category(self, client) -> None:
        r = client.post("/api/memories", json={"key": "def-test", "value": "data"})
        assert r.status_code == 201

        r = client.get("/api/memories/def-test")
        assert r.json()["category"] == "persistent"

    def test_list_with_category_filter(self, client) -> None:
        client.post("/api/memories", json={"key": "p1", "value": "v", "category": "persistent"})
        client.post("/api/memories", json={"key": "s1", "value": "v", "category": "session"})

        r = client.get("/api/memories?category=session")
        assert r.status_code == 200
        data = r.json()
        assert len(data["memories"]) == 1
        assert data["memories"][0]["key"] == "s1"

    def test_category_stats_endpoint(self, client) -> None:
        client.post("/api/memories", json={"key": "a", "value": "v", "category": "persistent"})
        client.post("/api/memories", json={"key": "b", "value": "v", "category": "session"})
        client.post("/api/memories", json={"key": "c", "value": "v", "category": "ephemeral"})

        r = client.get("/api/memories/category-stats")
        assert r.status_code == 200
        stats = r.json()
        assert stats["persistent"] == 1
        assert stats["session"] == 1
        assert stats["ephemeral"] == 1
