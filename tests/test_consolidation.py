"""Tests for src.core.consolidation — confidence, contradictions, merge."""
from __future__ import annotations

import time

import pytest

from src.core.consolidation import (
    Contradiction,
    confidence_score,
    consolidation_report,
    find_contradictions,
    merge_group,
)
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore(Database(None))


class TestConfidence:
    def test_baseline(self) -> None:
        now = time.time()
        m = Memory(key="k", value="v", updated_at=now)
        c = confidence_score(m, now=now)
        assert 0.6 <= c <= 0.7  # 0.5 + recency≈0.15

    def test_pinned_higher(self) -> None:
        now = time.time()
        plain = Memory(key="a", value="v", updated_at=now)
        pinned = Memory(key="b", value="v", updated_at=now, pinned=True)
        assert confidence_score(pinned, now=now) > confidence_score(plain, now=now)

    def test_source_tag_boosts(self) -> None:
        now = time.time()
        m = Memory(key="a", value="v", tags=["source:github"], updated_at=now)
        plain = Memory(key="b", value="v", updated_at=now)
        assert confidence_score(m, now=now) > confidence_score(plain, now=now)

    def test_expired_penalised(self) -> None:
        now = time.time()
        expired = Memory(key="a", value="v", updated_at=now, expires_at=now - 10)
        assert confidence_score(expired, now=now) < 0.6

    def test_corroboration_boosts(self) -> None:
        now = time.time()
        m = Memory(key="a", value="v", updated_at=now)
        assert confidence_score(m, corroboration=3, now=now) > confidence_score(m, now=now)

    def test_clamped(self) -> None:
        now = time.time()
        m = Memory(key="a", value="v", tags=["source:x"], updated_at=now, pinned=True)
        assert 0.0 <= confidence_score(m, corroboration=99, now=now) <= 1.0


class TestContradictions:
    def test_numeric_conflict_same_tag(self) -> None:
        mems = [
            Memory(key="a", value="The monthly server cost is 50 euro per month total", tags=["cost"]),
            Memory(key="b", value="The monthly server cost is 90 euro per month total", tags=["cost"]),
        ]
        out = find_contradictions(mems)
        assert len(out) == 1
        assert "numeric" in out[0].reason

    def test_polarity_conflict(self) -> None:
        mems = [
            Memory(key="x/a", value="The backup feature is currently enabled on the server"),
            Memory(key="x/b", value="The backup feature is currently disabled on the server"),
        ]
        out = find_contradictions(mems)
        assert len(out) == 1
        assert "polarity" in out[0].reason

    def test_unrelated_not_flagged(self) -> None:
        mems = [
            Memory(key="a", value="The cat sat quietly on the warm windowsill all day", tags=["x"]),
            Memory(key="b", value="Kubernetes pods restart when the liveness probe fails", tags=["y"]),
        ]
        assert find_contradictions(mems) == []

    def test_identical_not_flagged(self) -> None:
        # identical values are duplicates, not contradictions (sim >= 0.95 gate)
        v = "The server runs at 50 percent utilisation on average during the week"
        mems = [Memory(key="a", value=v, tags=["t"]), Memory(key="b", value=v, tags=["t"])]
        assert find_contradictions(mems) == []

    def test_short_values_skipped(self) -> None:
        mems = [Memory(key="a", value="5", tags=["t"]), Memory(key="b", value="9", tags=["t"])]
        assert find_contradictions(mems) == []


class TestMerge:
    def test_merge_unions_and_deletes(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="alpha", tags=["t1"]))
        time.sleep(0.01)
        store.set(Memory(key="b", value="beta", tags=["t2"], pinned=True))
        survivor = merge_group(store, ["a", "b"])
        assert survivor == "b"  # newest
        m = store.get("b")
        assert "alpha" in m.value and "beta" in m.value
        assert set(m.tags) == {"t1", "t2"}
        assert m.pinned is True
        assert m.metadata["merged_from"] == ["a"]
        with pytest.raises(KeyError):
            store.get("a")

    def test_merge_explicit_survivor(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="alpha"))
        store.set(Memory(key="b", value="beta"))
        survivor = merge_group(store, ["a", "b"], into="a")
        assert survivor == "a"
        assert store.get("a")

    def test_merge_needs_two(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="alpha"))
        with pytest.raises(ValueError):
            merge_group(store, ["a", "ghost"])

    def test_merge_duplicate_keys_rejected(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="alpha"))
        with pytest.raises(ValueError):
            merge_group(store, ["a", "a"])

    def test_merge_invalid_into_rejected(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="alpha"))
        store.set(Memory(key="b", value="beta"))
        with pytest.raises(ValueError):
            merge_group(store, ["a", "b"], into="c")


class TestReport:
    def test_report_shape(self, store: MemoryStore) -> None:
        store.set(Memory(key="x/a", value="The backup feature is currently enabled on the server"))
        store.set(Memory(key="x/b", value="The backup feature is currently disabled on the server"))
        rep = consolidation_report(store.list())
        assert rep["total"] == 2
        assert rep["contradictions"] >= 1
        assert "low_confidence_samples" in rep
