"""Tests for src.core.weight_adjuster — WeightAdjuster."""
from __future__ import annotations

import pytest

from src.core.block import Block, Priority
from src.core.weight_adjuster import WeightAdjuster, HIGH_THRESHOLD, LOW_THRESHOLD
from src.storage.db import Database
from src.storage.usage import UsageStore, UsageRecord, FeedbackRecord, block_hash


@pytest.fixture
def store() -> UsageStore:
    db = Database(None)
    return UsageStore(db)


@pytest.fixture
def adjuster(store: UsageStore) -> WeightAdjuster:
    return WeightAdjuster(store)


class TestComputeWeight:
    def test_no_data_returns_baseline(self, adjuster: WeightAdjuster) -> None:
        w = adjuster.compute_weight("brand new content")
        assert w.usage_count == 0
        assert w.feedback_score == 0.0
        assert w.weight > 0

    def test_high_usage_increases_weight(self, adjuster: WeightAdjuster, store: UsageStore) -> None:
        bh = block_hash("popular")
        records = [UsageRecord(block_hash=bh, included=True, token_count=10) for _ in range(20)]
        # Add some other blocks for median reference
        for i in range(5):
            records.append(UsageRecord(block_hash=block_hash(f"other{i}"), included=True, token_count=10))
        store.record_usage(records)
        w = adjuster.compute_weight("popular")
        assert w.usage_count == 20
        assert w.weight > 1.0

    def test_positive_feedback_increases_weight(self, adjuster: WeightAdjuster, store: UsageStore) -> None:
        bh = block_hash("good block")
        store.record_usage([UsageRecord(block_hash=bh, included=True, token_count=10)])
        for _ in range(5):
            store.record_feedback(FeedbackRecord(assembly_id="a", block_hash=bh, helpful=True))
        w = adjuster.compute_weight("good block")
        assert w.feedback_score == pytest.approx(1.0)

    def test_negative_feedback_decreases_weight(self, adjuster: WeightAdjuster, store: UsageStore) -> None:
        bh = block_hash("bad block")
        store.record_usage([UsageRecord(block_hash=bh, included=True, token_count=10)])
        for _ in range(5):
            store.record_feedback(FeedbackRecord(assembly_id="a", block_hash=bh, helpful=False))
        w = adjuster.compute_weight("bad block")
        assert w.feedback_score == pytest.approx(-1.0)

    def test_weight_saved_to_store(self, adjuster: WeightAdjuster, store: UsageStore) -> None:
        adjuster.compute_weight("saved")
        w = store.get_weight(block_hash("saved"), None)
        assert w is not None


class TestAdjustPriority:
    def test_high_weight_promotes(self, adjuster: WeightAdjuster) -> None:
        from src.storage.usage import BlockWeight
        block = Block(content="test", priority=Priority.MEDIUM)
        w = BlockWeight(block_hash="x", project_name=None, weight=HIGH_THRESHOLD + 0.1)
        result = adjuster.adjust_priority(block, w)
        assert result.priority == Priority.HIGH

    def test_low_weight_demotes(self, adjuster: WeightAdjuster) -> None:
        from src.storage.usage import BlockWeight
        block = Block(content="test", priority=Priority.MEDIUM)
        w = BlockWeight(block_hash="x", project_name=None, weight=LOW_THRESHOLD - 0.1)
        result = adjuster.adjust_priority(block, w)
        assert result.priority == Priority.LOW

    def test_normal_weight_keeps_medium(self, adjuster: WeightAdjuster) -> None:
        from src.storage.usage import BlockWeight
        block = Block(content="test", priority=Priority.MEDIUM)
        w = BlockWeight(block_hash="x", project_name=None, weight=1.0)
        result = adjuster.adjust_priority(block, w)
        assert result.priority == Priority.MEDIUM

    def test_high_priority_not_changed(self, adjuster: WeightAdjuster) -> None:
        from src.storage.usage import BlockWeight
        block = Block(content="test", priority=Priority.HIGH)
        w = BlockWeight(block_hash="x", project_name=None, weight=LOW_THRESHOLD - 0.1)
        result = adjuster.adjust_priority(block, w)
        assert result.priority == Priority.HIGH  # HIGH blocks not demoted

    def test_does_not_mutate_original(self, adjuster: WeightAdjuster) -> None:
        from src.storage.usage import BlockWeight
        block = Block(content="test", priority=Priority.MEDIUM)
        w = BlockWeight(block_hash="x", project_name=None, weight=HIGH_THRESHOLD + 0.1)
        adjuster.adjust_priority(block, w)
        assert block.priority == Priority.MEDIUM


class TestAdjustBlocks:
    def test_adjusts_all(self, adjuster: WeightAdjuster) -> None:
        blocks = [
            Block(content="a", priority=Priority.MEDIUM),
            Block(content="b", priority=Priority.MEDIUM),
        ]
        result = adjuster.adjust_blocks(blocks)
        assert len(result) == 2

    def test_project_scoped(self, adjuster: WeightAdjuster, store: UsageStore) -> None:
        bh = block_hash("scoped")
        records = [UsageRecord(block_hash=bh, project_name="p1", included=True, token_count=10)
                    for _ in range(10)]
        store.record_usage(records)
        blocks = [Block(content="scoped", priority=Priority.MEDIUM)]
        result = adjuster.adjust_blocks(blocks, project_name="p1")
        assert len(result) == 1


class TestRecomputeAll:
    def test_recompute(self, adjuster: WeightAdjuster, store: UsageStore) -> None:
        bh1 = block_hash("a")
        bh2 = block_hash("b")
        store.record_usage([
            UsageRecord(block_hash=bh1, included=True, token_count=10),
            UsageRecord(block_hash=bh2, included=True, token_count=20),
        ])
        count = adjuster.recompute_all_weights()
        assert count == 2
        assert store.get_weight(bh1, None) is not None
        assert store.get_weight(bh2, None) is not None
