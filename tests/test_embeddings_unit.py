"""Unit tests for TFIDFEngine and EmbeddingStore."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from src.core.embeddings import TFIDFEngine, EmbeddingStore, _cosine_sim


# ═══════════════════════════════════════════════════════════════
# TFIDFEngine
# ═══════════════════════════════════════════════════════════════

class TestTFIDFEngine:
    def test_build_idf(self):
        engine = TFIDFEngine()
        docs = [
            "python programming language",
            "java programming language",
            "python data science",
        ]
        engine.build_idf(docs)

        assert engine._doc_count == 3
        assert len(engine._idf) > 0
        assert "python" in engine._idf
        assert "programming" in engine._idf
        # "python" appears in 2/3 docs, "data" in 1/3 -> data has higher IDF
        assert engine._idf["data"] > engine._idf["programming"]

    def test_vectorize(self):
        engine = TFIDFEngine()
        engine.build_idf(["python programming", "java programming"])
        vec = engine.vectorize("python programming")

        assert len(vec) > 0
        assert any(v != 0.0 for v in vec)
        # normalized vector should have unit length (approximately)
        norm = math.sqrt(sum(v * v for v in vec))
        assert abs(norm - 1.0) < 0.01 or norm == 0.0

    def test_cosine_sim_identical(self):
        vec = [0.5, 0.3, 0.8, 0.1]
        sim = _cosine_sim(vec, vec)
        assert abs(sim - 1.0) < 1e-6

    def test_cosine_sim_orthogonal(self):
        engine = TFIDFEngine()
        engine.build_idf([
            "python programming language",
            "cooking recipe kitchen food",
        ])
        vec_a = engine.vectorize("python programming language")
        vec_b = engine.vectorize("cooking recipe kitchen food")

        sim = _cosine_sim(vec_a, vec_b)
        assert sim < 1.0
        # These topics share no terms, so similarity should be 0 or very close
        assert sim < 0.1

    def test_cosine_sim_zero_vector(self):
        zero = [0.0, 0.0, 0.0]
        other = [1.0, 2.0, 3.0]
        assert _cosine_sim(zero, other) == 0.0
        assert _cosine_sim(other, zero) == 0.0
        assert _cosine_sim(zero, zero) == 0.0

    def test_search(self):
        engine = TFIDFEngine()
        docs = [
            "python web framework flask",
            "javascript react frontend",
            "python machine learning tensorflow",
            "cooking italian pasta recipe",
        ]
        engine.build_idf(docs)

        vectors = {i: engine.vectorize(doc) for i, doc in enumerate(docs)}
        query_vec = engine.vectorize("python programming")

        scores = []
        for i, vec in vectors.items():
            sim = _cosine_sim(query_vec, vec)
            scores.append((i, sim))
        scores.sort(key=lambda x: -x[1])

        # Python docs should rank higher than cooking
        python_indices = {0, 2}
        top_2 = {scores[0][0], scores[1][0]}
        assert top_2 == python_indices


# ═══════════════════════════════════════════════════════════════
# EmbeddingStore
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def emb_store(tmp_path):
    s = EmbeddingStore(tmp_path / "emb_test.db")
    yield s
    s.close()


class TestEmbeddingStore:
    def test_store_and_get(self, emb_store):
        vec = [0.1, 0.2, 0.3, 0.4]
        emb_store.store("key1", "hash1", vec)
        result = emb_store.get("key1")
        assert result is not None
        assert len(result) == 4
        assert abs(result[0] - 0.1) < 1e-5
        assert abs(result[3] - 0.4) < 1e-5

    def test_has(self, emb_store):
        assert emb_store.has("missing", "h") is False
        emb_store.store("key1", "hash1", [1.0, 2.0])
        assert emb_store.has("key1", "hash1") is True
        assert emb_store.has("key1", "different_hash") is False

    def test_remove(self, emb_store):
        emb_store.store("key1", "hash1", [1.0, 2.0])
        assert emb_store.get("key1") is not None
        emb_store.remove("key1")
        assert emb_store.get("key1") is None

    def test_search_similar(self, emb_store):
        emb_store.store("doc_python", "h1", [0.9, 0.1, 0.0])
        emb_store.store("doc_java", "h2", [0.7, 0.3, 0.0])
        emb_store.store("doc_cooking", "h3", [0.0, 0.1, 0.9])

        query = [0.8, 0.2, 0.0]
        all_vecs = emb_store.all_vectors()
        results = []
        for key, vec in all_vecs:
            sim = _cosine_sim(query, vec)
            results.append((key, sim))
        results.sort(key=lambda x: -x[1])

        assert results[0][0] == "doc_python"
        assert results[-1][0] == "doc_cooking"
        assert results[0][1] > results[-1][1]
