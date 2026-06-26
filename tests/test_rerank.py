"""Tests for src.core.rerank — signal-fusion reranking."""
from __future__ import annotations

import time

from src.core.rerank import DEFAULT_WEIGHTS, _coverage, _recency_score, rerank, rerank_candidates
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore

import pytest


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore(Database(None))


def _cand(key: str, score: float, value: str = "x", tags=None) -> dict:
    return {"key": key, "value": value, "score": score, "tags": tags or [], "method": "hybrid"}


class TestHelpers:
    def test_recency_now_is_one(self) -> None:
        now = time.time()
        assert _recency_score(now, now) == pytest.approx(1.0)

    def test_recency_halflife(self) -> None:
        now = time.time()
        from src.core.rerank import RECENCY_HALF_LIFE_DAYS
        old = now - RECENCY_HALF_LIFE_DAYS * 86400
        assert _recency_score(old, now) == pytest.approx(0.5, abs=1e-6)

    def test_coverage(self) -> None:
        assert _coverage({"a", "b"}, {"a"}) == pytest.approx(0.5)
        assert _coverage(set(), {"a"}) == 0.0
        assert _coverage({"a"}, set()) == 0.0


class TestRerank:
    def test_empty(self) -> None:
        assert rerank("q", [], {}) == []

    def test_preserves_fields_and_annotates(self) -> None:
        cands = [_cand("k1", 0.9)]
        out = rerank("hello", cands, {})
        assert out[0]["key"] == "k1"
        assert out[0]["base_score"] == 0.9
        assert "rerank_score" in out[0]
        # input untouched
        assert "rerank_score" not in cands[0]

    def test_pinned_boosts_rank(self) -> None:
        now = time.time()
        cands = [_cand("a", 0.5), _cand("b", 0.5)]
        mems = {
            "a": Memory(key="a", value="x", updated_at=now),
            "b": Memory(key="b", value="x", updated_at=now, pinned=True),
        }
        out = rerank("q", cands, mems, now=now)
        assert out[0]["key"] == "b"

    def test_recency_breaks_tie(self) -> None:
        now = time.time()
        cands = [_cand("old", 0.5), _cand("new", 0.5)]
        mems = {
            "old": Memory(key="old", value="x", updated_at=now - 365 * 86400),
            "new": Memory(key="new", value="x", updated_at=now),
        }
        out = rerank("q", cands, mems, now=now)
        assert out[0]["key"] == "new"

    def test_tag_overlap_boosts(self) -> None:
        now = time.time()
        cands = [_cand("a", 0.5, tags=["unrelated"]), _cand("b", 0.5, tags=["docker"])]
        mems = {
            "a": Memory(key="a", value="x", tags=["unrelated"], updated_at=now),
            "b": Memory(key="b", value="x", tags=["docker"], updated_at=now),
        }
        out = rerank("docker deployment", cands, mems, now=now)
        assert out[0]["key"] == "b"

    def test_relevance_dominates(self) -> None:
        now = time.time()
        cands = [_cand("low", 0.1), _cand("high", 0.95)]
        mems = {
            "low": Memory(key="low", value="x", updated_at=now, pinned=True),
            "high": Memory(key="high", value="x", updated_at=now),
        }
        out = rerank("q", cands, mems, now=now, weights=DEFAULT_WEIGHTS)
        assert out[0]["key"] == "high"


class TestRerankCandidates:
    def test_loads_metadata_from_store(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="alpha doc", tags=["t"], pinned=True))
        store.set(Memory(key="b", value="beta doc", tags=["t"]))
        cands = [_cand("a", 0.5), _cand("b", 0.5)]
        out = rerank_candidates("q", cands, store)
        assert out[0]["key"] == "a"  # pinned wins

    def test_missing_key_tolerated(self, store: MemoryStore) -> None:
        cands = [_cand("ghost", 0.5)]
        out = rerank_candidates("q", cands, store)
        assert out[0]["key"] == "ghost"
