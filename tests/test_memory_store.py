"""Tests for src.storage.memory — MemoryStore (SQLite-backed)."""
from __future__ import annotations

import json
import pytest

from src.storage.db import Database
from src.storage.memory import MemoryStore, Memory


@pytest.fixture
def db():
    database = Database(None)  # in-memory
    yield database
    database.close()


@pytest.fixture
def store(db: Database) -> MemoryStore:
    return MemoryStore(db)


class TestMemoryStore:
    def test_list_empty(self, store: MemoryStore) -> None:
        assert store.list() == []

    def test_set_and_get(self, store: MemoryStore) -> None:
        store.set(Memory(key="greeting", value="hello world", tags=["test"]))
        m = store.get("greeting")
        assert m.key == "greeting"
        assert m.value == "hello world"
        assert m.tags == ["test"]

    def test_get_nonexistent_raises(self, store: MemoryStore) -> None:
        with pytest.raises(KeyError):
            store.get("nope")

    def test_update_preserves_created_at(self, store: MemoryStore) -> None:
        store.set(Memory(key="k", value="v1", created_at=1.0))
        store.set(Memory(key="k", value="v2", created_at=999.0))
        m = store.get("k")
        assert m.value == "v2"
        assert m.created_at == 1.0

    def test_delete(self, store: MemoryStore) -> None:
        store.set(Memory(key="del_me", value="x"))
        store.delete("del_me")
        assert store.list() == []

    def test_delete_nonexistent_raises(self, store: MemoryStore) -> None:
        with pytest.raises(KeyError):
            store.delete("ghost")

    def test_search_by_query(self, store: MemoryStore) -> None:
        store.set(Memory(key="api-key", value="secret123"))
        store.set(Memory(key="notes", value="remember the api"))
        results = store.search("api")
        assert len(results) == 2

    def test_search_by_tags(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="x", tags=["config", "prod"]))
        store.set(Memory(key="b", value="y", tags=["config"]))
        store.set(Memory(key="c", value="z", tags=["debug"]))
        results = store.search("", tags=["config"])
        assert len(results) == 2
        keys = {m.key for m in results}
        assert keys == {"a", "b"}

    def test_search_by_query_and_tags(self, store: MemoryStore) -> None:
        store.set(Memory(key="db-host", value="localhost", tags=["config"]))
        store.set(Memory(key="db-port", value="5432", tags=["config"]))
        store.set(Memory(key="note", value="localhost info", tags=["notes"]))
        results = store.search("localhost", tags=["config"])
        assert len(results) == 1
        assert results[0].key == "db-host"

    def test_tags(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="x", tags=["beta", "alpha"]))
        store.set(Memory(key="b", value="y", tags=["alpha", "gamma"]))
        assert store.tags() == ["alpha", "beta", "gamma"]

    def test_export_import_merge(self, store: MemoryStore) -> None:
        store.set(Memory(key="existing", value="keep"))
        store.set(Memory(key="overwrite", value="old"))
        exported = json.dumps({"memories": [
            {"key": "overwrite", "value": "new"},
            {"key": "imported", "value": "fresh"},
        ]})
        count = store.import_json(exported, merge=True)
        assert count == 2
        assert store.get("existing").value == "keep"
        assert store.get("overwrite").value == "new"
        assert store.get("imported").value == "fresh"

    def test_export_import_replace(self, store: MemoryStore) -> None:
        store.set(Memory(key="old", value="gone"))
        exported = json.dumps({"memories": [
            {"key": "new", "value": "only"},
        ]})
        store.import_json(exported, merge=False)
        assert len(store.list()) == 1
        assert store.list()[0].key == "new"

    def test_export_roundtrip(self, store: MemoryStore, db: Database) -> None:
        store.set(Memory(key="rt", value="data", tags=["t1"]))
        exported = store.export_json()
        db2 = Database(None)
        try:
            store2 = MemoryStore(db2)
            store2.import_json(exported)
            m = store2.get("rt")
            assert m.value == "data"
            assert m.tags == ["t1"]
        finally:
            db2.close()

    def test_search_empty_query_no_tags(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="x"))
        store.set(Memory(key="b", value="y"))
        results = store.search("")
        assert len(results) == 2

    def test_fts_search(self, store: MemoryStore) -> None:
        store.set(Memory(key="doc1", value="the quick brown fox"))
        store.set(Memory(key="doc2", value="lazy dog"))
        results = store.search("quick")
        assert len(results) == 1
        assert results[0].key == "doc1"


class TestMemory:
    def test_roundtrip(self) -> None:
        m = Memory(key="k", value="v", tags=["a"], metadata={"x": 1}, created_at=10.0, updated_at=20.0)
        d = m.to_dict()
        m2 = Memory.from_dict(d)
        assert m2.key == m.key
        assert m2.value == m.value
        assert m2.tags == m.tags
        assert m2.metadata == m.metadata
        assert m2.created_at == m.created_at
        assert m2.updated_at == m.updated_at
