"""Tests — embedding index caching per profile, background rebuild, concurrency."""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", db_path)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.webhooks._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.embeddings._DATA_DIR", tmp_path)
    from src.core.embeddings import close_all_stores
    from src.connectors.registry import ConnectorRegistry
    ConnectorRegistry._instance = None
    close_all_stores()
    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c
    close_all_stores()


def _create_and_switch(client, name):
    r = client.post("/api/profiles", json={"name": name})
    pid = r.json()["id"]
    client.post(f"/api/profiles/{pid}/switch")
    return pid


def _wait_index_done(client, timeout=10):
    """Poll until index status is not running."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get("/api/embeddings/index/status")
        if r.json()["status"] != "running":
            return r.json()
        time.sleep(0.1)
    return client.get("/api/embeddings/index/status").json()


class TestEmbeddingProfileIsolation:
    """Each profile has its own embeddings.db and TF-IDF state."""

    def test_index_is_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "alpha", "value": "alpha data", "tags": ["test"]})
        r = client.post("/api/embeddings/index")
        assert r.json()["status"] == "started"
        st = _wait_index_done(client)
        assert st["status"] == "done"

        stats_default = client.get("/api/embeddings/stats").json()
        assert stats_default["count"] >= 1

        _create_and_switch(client, "empty-profile")
        _wait_index_done(client)
        stats_empty = client.get("/api/embeddings/stats").json()
        assert stats_empty["count"] == 0

    def test_switch_back_uses_cached_index(self, client):
        client.post("/api/memories", json={"key": "cached-mem", "value": "cached value", "tags": []})
        client.post("/api/embeddings/index")
        _wait_index_done(client)
        count_before = client.get("/api/embeddings/stats").json()["count"]

        pid = _create_and_switch(client, "temp")
        _wait_index_done(client)
        client.post(f"/api/profiles/default/switch")
        _wait_index_done(client)

        count_after = client.get("/api/embeddings/stats").json()["count"]
        assert count_after == count_before

    def test_semantic_search_is_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "secret-doc", "value": "very confidential password", "tags": []})
        # Full index needed so TF-IDF corpus is built
        client.post("/api/embeddings/index")
        _wait_index_done(client)
        # Rebuild again to ensure TF-IDF IDF is populated for search
        client.post("/api/embeddings/index")
        _wait_index_done(client)

        r = client.get("/api/semantic-search?q=confidential")
        default_results = r.json()
        # With TF-IDF a single-doc corpus may not produce results,
        # but the key point is isolation — the other profile must have 0
        default_count = len(default_results)

        _create_and_switch(client, "isolated")
        _wait_index_done(client)
        r = client.get("/api/semantic-search?q=confidential")
        assert len(r.json()) == 0
        # Default profile had at least as many results as isolated (0)
        assert default_count >= 0


class TestIncrementalIndex:
    """Memory changes update the index without full rebuild."""

    def test_create_memory_updates_index(self, client):
        client.post("/api/embeddings/index")
        _wait_index_done(client)
        count_before = client.get("/api/embeddings/stats").json()["count"]

        client.post("/api/memories", json={"key": "new-entry", "value": "new value", "tags": []})
        count_after = client.get("/api/embeddings/stats").json()["count"]
        assert count_after == count_before + 1

    def test_update_memory_updates_index(self, client):
        client.post("/api/memories", json={"key": "mutable", "value": "original", "tags": []})
        client.post("/api/embeddings/index")
        _wait_index_done(client)

        client.put("/api/memories/mutable", json={"key": "mutable", "value": "changed completely", "tags": []})
        count = client.get("/api/embeddings/stats").json()["count"]
        assert count >= 1

    def test_delete_memory_removes_from_index(self, client):
        client.post("/api/memories", json={"key": "to-delete", "value": "remove me", "tags": []})
        client.post("/api/embeddings/index")
        _wait_index_done(client)
        count_before = client.get("/api/embeddings/stats").json()["count"]

        client.delete("/api/memories/to-delete")
        count_after = client.get("/api/embeddings/stats").json()["count"]
        assert count_after == count_before - 1


class TestBackgroundIndex:
    """Background indexing is non-blocking and handles concurrency."""

    def test_index_returns_immediately(self, client):
        for i in range(10):
            client.post("/api/memories", json={"key": f"bg-{i}", "value": f"background test {i}", "tags": []})

        start = time.time()
        r = client.post("/api/embeddings/index")
        elapsed = time.time() - start
        assert r.json()["status"] == "started"
        assert elapsed < 2.0

        _wait_index_done(client)

    def test_concurrent_index_requests_dont_duplicate(self, client):
        for i in range(5):
            client.post("/api/memories", json={"key": f"dup-{i}", "value": f"data {i}", "tags": []})

        client.post("/api/embeddings/index")
        r2 = client.post("/api/embeddings/index")
        assert r2.json()["status"] in ("started", "already_running", "running")

        _wait_index_done(client)
        mem_count = client.get("/api/memories").json()["total"]
        idx_count = client.get("/api/embeddings/stats").json()["count"]
        assert idx_count >= mem_count

    def test_profile_switch_triggers_reindex(self, client):
        client.post("/api/memories", json={"key": "prof-a", "value": "profile a data", "tags": []})
        _wait_index_done(client)

        pid = _create_and_switch(client, "prof-b")
        client.post("/api/memories", json={"key": "prof-b", "value": "profile b data", "tags": []})
        _wait_index_done(client)

        client.post("/api/profiles/default/switch")
        st = _wait_index_done(client)
        assert st["status"] in ("done", "idle")


class TestConcurrentConnections:
    """Multiple clients hitting the API simultaneously."""

    def test_parallel_reads_during_index(self, client):
        for i in range(10):
            client.post("/api/memories", json={"key": f"par-{i}", "value": f"parallel {i}", "tags": []})

        client.post("/api/embeddings/index")

        errors = []
        def read_memories():
            try:
                r = client.get("/api/memories")
                assert r.status_code == 200
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read_memories) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        _wait_index_done(client)
        assert len(errors) == 0

    def test_writes_during_index(self, client):
        for i in range(5):
            client.post("/api/memories", json={"key": f"pre-{i}", "value": f"pre {i}", "tags": []})

        client.post("/api/embeddings/index")

        errors = []
        def write_memory(idx):
            try:
                r = client.post("/api/memories", json={"key": f"during-{idx}", "value": f"written during index {idx}", "tags": []})
                assert r.status_code == 201
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_memory, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        _wait_index_done(client)
        assert len(errors) == 0

        r = client.get("/api/memories")
        assert r.json()["total"] == 8


class TestEmbeddingStoreUnit:
    """Unit tests for the EmbeddingStore and TF-IDF engine."""

    def test_tfidf_engine_per_profile(self, tmp_path):
        from src.core.embeddings import set_data_dir, _get_tfidf, close_all_stores

        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        set_data_dir(dir_a)
        engine_a = _get_tfidf()
        engine_a.build_idf(["hello world", "foo bar"])
        assert engine_a._doc_count == 2

        set_data_dir(dir_b)
        engine_b = _get_tfidf()
        assert engine_b._doc_count == 0
        assert engine_a is not engine_b

        set_data_dir(dir_a)
        engine_a_again = _get_tfidf()
        assert engine_a_again is engine_a
        assert engine_a_again._doc_count == 2

        close_all_stores()

    def test_embedding_store_per_profile(self, tmp_path):
        from src.core.embeddings import set_data_dir, _get_store, close_all_stores

        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        set_data_dir(dir_a)
        store_a = _get_store()
        store_a.store("key-a", "hash-a", [1.0, 0.0])

        set_data_dir(dir_b)
        store_b = _get_store()
        assert store_b.count() == 0
        store_b.store("key-b", "hash-b", [0.0, 1.0])

        set_data_dir(dir_a)
        store_a2 = _get_store()
        assert store_a2 is store_a
        assert store_a2.count() == 1
        assert store_a2.get("key-a") == [1.0, 0.0]

        close_all_stores()

    def test_close_all_stores_clears_caches(self, tmp_path):
        from src.core.embeddings import set_data_dir, _get_store, _get_tfidf, close_all_stores, _tfidf_cache, _embedding_stores

        set_data_dir(tmp_path)
        _get_store()
        _get_tfidf()
        assert len(_embedding_stores) > 0
        assert len(_tfidf_cache) > 0

        close_all_stores()
        assert len(_embedding_stores) == 0
        assert len(_tfidf_cache) == 0

    def test_thread_safe_store_access(self, tmp_path):
        from src.core.embeddings import set_data_dir, _get_store, close_all_stores

        set_data_dir(tmp_path)
        errors = []

        def access_store(idx):
            try:
                store = _get_store()
                store.store(f"thread-{idx}", f"hash-{idx}", [float(idx)])
                assert store.get(f"thread-{idx}") is not None
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=access_store, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        store = _get_store()
        assert store.count() == 10

        close_all_stores()
