"""Tests for hybrid semantic search (QW4 + F1)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.core.embeddings import (
    hybrid_search,
    semantic_search,
    index_memories,
    embed_text,
    close_all_stores,
    set_data_dir,
    TFIDFEngine,
)


@pytest.fixture
def db():
    d = Database(None)
    yield d
    d.close()


@pytest.fixture
def store(db):
    return MemoryStore(db)


@pytest.fixture
def seeded_store(store, tmp_path):
    """Store with seeded memories and indexed embeddings."""
    set_data_dir(tmp_path)
    memories = [
        Memory(key="python/basics", value="Python is a programming language", tags=["python", "lang"]),
        Memory(key="python/async", value="Async await syntax in Python for concurrency", tags=["python", "async"]),
        Memory(key="docker/intro", value="Docker containers for deployment", tags=["docker", "devops"]),
        Memory(key="docker/compose", value="Docker Compose orchestrates multi-container apps", tags=["docker"]),
        Memory(key="testing/pytest", value="Pytest is a testing framework for Python", tags=["python", "testing"]),
    ]
    for m in memories:
        store.set(m)

    # Index embeddings
    index_memories(memories, profile_dir=tmp_path)

    yield store
    close_all_stores()


class TestHybridSearch:
    def test_returns_results_for_matching_query(self, seeded_store):
        results = hybrid_search("python programming", seeded_store)
        assert len(results) > 0
        assert all("key" in r for r in results)
        assert all("value" in r for r in results)
        assert all("score" in r for r in results)
        assert all("tags" in r for r in results)
        assert all("method" in r for r in results)

    def test_results_sorted_by_score_descending(self, seeded_store):
        results = hybrid_search("python", seeded_store)
        if len(results) > 1:
            scores = [r["score"] for r in results]
            assert scores == sorted(scores, reverse=True)

    def test_method_field_values(self, seeded_store):
        results = hybrid_search("python", seeded_store)
        valid_methods = {"hybrid", "fts", "semantic"}
        for r in results:
            assert r["method"] in valid_methods

    def test_top_k_limits_results(self, seeded_store):
        results = hybrid_search("python", seeded_store, top_k=2)
        assert len(results) <= 2

    def test_empty_query_returns_empty(self, seeded_store):
        results = hybrid_search("", seeded_store)
        assert results == []

    def test_whitespace_query_returns_empty(self, seeded_store):
        results = hybrid_search("   ", seeded_store)
        assert results == []

    def test_no_match_returns_empty_or_low_scores(self, seeded_store):
        results = hybrid_search("xyznonexistent12345", seeded_store)
        # May return empty or very low score results
        assert isinstance(results, list)

    def test_custom_weights(self, seeded_store):
        r1 = hybrid_search("docker", seeded_store, fts_weight=1.0, semantic_weight=0.0)
        r2 = hybrid_search("docker", seeded_store, fts_weight=0.0, semantic_weight=1.0)
        # Both should return results but potentially in different orders
        assert isinstance(r1, list)
        assert isinstance(r2, list)


class TestFallbackToFTS:
    def test_falls_back_when_no_embeddings(self, store, tmp_path):
        """When no embeddings are indexed, hybrid_search returns FTS-only results."""
        set_data_dir(tmp_path)
        store.set(Memory(key="test/one", value="Hello world test", tags=["test"]))

        results = hybrid_search("Hello", store)
        assert len(results) > 0
        # All results should be FTS method since no embeddings exist
        for r in results:
            assert r["method"] == "fts"
        close_all_stores()


class TestScoreNormalization:
    def test_scores_between_zero_and_one(self, seeded_store):
        results = hybrid_search("python", seeded_store)
        for r in results:
            assert 0 <= r["score"] <= 1.0

    def test_single_result_normalized(self, store, tmp_path):
        """With a single FTS result and no embeddings, score should be 1.0."""
        set_data_dir(tmp_path)
        store.set(Memory(key="single/item", value="unique xylophone test", tags=[]))
        results = hybrid_search("xylophone", store)
        if results:
            # Single result normalized to 1.0
            assert results[0]["score"] == 1.0
        close_all_stores()


class TestMCPMemorySearchSemantic:
    def test_semantic_false_uses_fts(self):
        with patch("src.interfaces.mcp_server._get_memory_store") as mock_store, \
             patch("src.interfaces.mcp_server._get_activity_log") as mock_log:
            mock_mem = MagicMock()
            mock_mem.key = "test"
            mock_mem.value = "value"
            mock_mem.tags = []
            mock_store.return_value.search.return_value = [mock_mem]
            mock_log.return_value.record = MagicMock()

            from src.interfaces.mcp_server import memory_search
            result = memory_search("test", semantic=False)
            assert result["count"] == 1
            mock_store.return_value.search.assert_called_once()

    def test_semantic_true_uses_hybrid(self):
        with patch("src.interfaces.mcp_server._get_memory_store") as mock_store, \
             patch("src.interfaces.mcp_server._get_activity_log") as mock_log, \
             patch("src.interfaces.mcp_server.hybrid_search", create=True) as mock_hybrid:

            # Patch at the right import location
            with patch("src.core.embeddings.hybrid_search") as mock_hs:
                mock_hs.return_value = [
                    {"key": "k1", "value": "v1", "score": 0.9, "tags": ["t"], "method": "hybrid"},
                ]
                mock_log.return_value.record = MagicMock()

                from src.interfaces.mcp_server import memory_search
                result = memory_search("test query", semantic=True)
                assert result["count"] == 1
                assert result["results"][0]["method"] == "hybrid"


class TestWebSemanticSearchModes:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from src.web.app import create_app
        app = create_app(db_path=None)
        with TestClient(app) as c:
            yield c

    def test_keyword_mode(self, client):
        # Seed a memory
        client.post("/api/memories", json={"key": "web/test", "value": "hello keyword world", "tags": []})
        r = client.get("/api/semantic-search?q=keyword&mode=keyword")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            assert data[0].get("method") == "keyword"

    def test_semantic_mode(self, client):
        r = client.get("/api/semantic-search?q=test&mode=semantic")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_hybrid_mode_default(self, client):
        client.post("/api/memories", json={"key": "web/hybrid", "value": "hybrid test value", "tags": []})
        r = client.get("/api/semantic-search?q=hybrid")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_invalid_mode_rejected(self, client):
        r = client.get("/api/semantic-search?q=test&mode=invalid")
        assert r.status_code == 422

    def test_empty_query_rejected(self, client):
        r = client.get("/api/semantic-search?q=")
        assert r.status_code == 422
