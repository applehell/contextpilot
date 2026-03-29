"""Tests for src.storage.usage — UsageStore."""
from __future__ import annotations

import time

import pytest

from src.storage.db import Database
from src.storage.usage import (
    UsageStore, UsageRecord, FeedbackRecord, BlockWeight,
    block_hash,
)


@pytest.fixture
def store() -> UsageStore:
    db = Database(None)
    return UsageStore(db)


class TestBlockHash:
    def test_deterministic(self) -> None:
        assert block_hash("hello") == block_hash("hello")

    def test_different_content(self) -> None:
        assert block_hash("hello") != block_hash("world")

    def test_length(self) -> None:
        assert len(block_hash("test")) == 16


class TestUsageRecording:
    def test_record_and_count(self, store: UsageStore) -> None:
        bh = block_hash("content A")
        store.record_usage([
            UsageRecord(block_hash=bh, included=True, token_count=10),
            UsageRecord(block_hash=bh, included=True, token_count=10),
            UsageRecord(block_hash=block_hash("content B"), included=False, token_count=5),
        ])
        counts = store.get_usage_counts()
        assert counts[bh] == 2
        assert block_hash("content B") not in counts  # not included

    def test_count_by_project(self, store: UsageStore) -> None:
        bh = block_hash("content")
        store.record_usage([
            UsageRecord(block_hash=bh, project_name="proj1", included=True, token_count=10),
            UsageRecord(block_hash=bh, project_name="proj2", included=True, token_count=10),
        ])
        assert store.get_usage_counts("proj1")[bh] == 1
        assert store.get_usage_counts()[bh] == 2

    def test_inclusion_rate(self, store: UsageStore) -> None:
        bh = block_hash("x")
        store.record_usage([
            UsageRecord(block_hash=bh, included=True, token_count=1),
            UsageRecord(block_hash=bh, included=False, token_count=1),
            UsageRecord(block_hash=bh, included=True, token_count=1),
            UsageRecord(block_hash=bh, included=False, token_count=1),
        ])
        rate = store.get_inclusion_rate(bh)
        assert rate == pytest.approx(0.5)

    def test_inclusion_rate_no_data(self, store: UsageStore) -> None:
        assert store.get_inclusion_rate("nonexistent") == 1.0


class TestFeedback:
    def test_record_and_score(self, store: UsageStore) -> None:
        bh = block_hash("block1")
        store.record_feedback(FeedbackRecord(assembly_id="a1", block_hash=bh, helpful=True))
        store.record_feedback(FeedbackRecord(assembly_id="a1", block_hash=bh, helpful=True))
        store.record_feedback(FeedbackRecord(assembly_id="a2", block_hash=bh, helpful=False))
        # 2/3 positive → score = (2/3)*2 - 1 = 0.333...
        score = store.get_feedback_score(bh)
        assert score == pytest.approx(1 / 3, abs=0.01)

    def test_no_feedback(self, store: UsageStore) -> None:
        assert store.get_feedback_score("none") == 0.0

    def test_all_negative(self, store: UsageStore) -> None:
        bh = block_hash("bad")
        store.record_feedback(FeedbackRecord(assembly_id="a1", block_hash=bh, helpful=False))
        assert store.get_feedback_score(bh) == pytest.approx(-1.0)

    def test_all_positive(self, store: UsageStore) -> None:
        bh = block_hash("good")
        store.record_feedback(FeedbackRecord(assembly_id="a1", block_hash=bh, helpful=True))
        assert store.get_feedback_score(bh) == pytest.approx(1.0)

    def test_get_assembly_feedback(self, store: UsageStore) -> None:
        store.record_feedback(FeedbackRecord(assembly_id="a1", block_hash="h1", helpful=True))
        store.record_feedback(FeedbackRecord(assembly_id="a1", block_hash="h2", helpful=False))
        store.record_feedback(FeedbackRecord(assembly_id="a2", block_hash="h3", helpful=True))
        items = store.get_assembly_feedback("a1")
        assert len(items) == 2


class TestBlockWeights:
    def test_save_and_get(self, store: UsageStore) -> None:
        w = BlockWeight(block_hash="abc", project_name=None, weight=1.5, usage_count=10)
        store.save_weight(w)
        loaded = store.get_weight("abc", None)
        assert loaded is not None
        assert loaded.weight == pytest.approx(1.5)
        assert loaded.usage_count == 10

    def test_upsert(self, store: UsageStore) -> None:
        w1 = BlockWeight(block_hash="abc", project_name=None, weight=1.0)
        store.save_weight(w1)
        w2 = BlockWeight(block_hash="abc", project_name=None, weight=2.0)
        store.save_weight(w2)
        loaded = store.get_weight("abc", None)
        assert loaded.weight == pytest.approx(2.0)

    def test_project_scoped(self, store: UsageStore) -> None:
        store.save_weight(BlockWeight(block_hash="x", project_name="p1", weight=1.0))
        store.save_weight(BlockWeight(block_hash="x", project_name="p2", weight=2.0))
        assert store.get_weight("x", "p1").weight == pytest.approx(1.0)
        assert store.get_weight("x", "p2").weight == pytest.approx(2.0)

    def test_upsert_none_project(self, store: UsageStore) -> None:
        """Regression: NULL project_name must not create duplicates (CON-23)."""
        w1 = BlockWeight(block_hash="dup", project_name=None, weight=1.0)
        store.save_weight(w1)
        w2 = BlockWeight(block_hash="dup", project_name=None, weight=3.0)
        store.save_weight(w2)
        loaded = store.get_weight("dup", None)
        assert loaded.weight == pytest.approx(3.0)
        # Verify exactly one row exists
        rows = store._db.conn.execute(
            "SELECT COUNT(*) as cnt FROM block_weights WHERE block_hash = 'dup'"
        ).fetchone()
        assert rows["cnt"] == 1

    def test_not_found(self, store: UsageStore) -> None:
        assert store.get_weight("missing", None) is None


