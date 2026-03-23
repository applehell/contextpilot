"""Tests for src.core.relevance — RelevanceEngine, scoring functions."""
from __future__ import annotations

import pytest

from src.core.block import Block, Priority
from src.core.relevance import (
    RelevanceEngine,
    RelevanceScore,
    SkillRelevanceProfile,
    score_content_relevance,
    score_history_relevance,
)


class TestScoreContentRelevance:
    def test_empty_hints_returns_neutral(self) -> None:
        block = Block(content="some git status output", priority=Priority.LOW)
        assert score_content_relevance(block, []) == 0.5

    def test_matching_hints_returns_high(self) -> None:
        block = Block(content="git status shows modified files in branch main", priority=Priority.LOW)
        score = score_content_relevance(block, ["git", "modified", "branch"])
        assert score > 0.5

    def test_no_matching_hints_returns_low(self) -> None:
        block = Block(content="The weather today is sunny and warm", priority=Priority.LOW)
        score = score_content_relevance(block, ["git", "commit", "branch"])
        assert score < 0.3

    def test_partial_match(self) -> None:
        block = Block(content="git commit message for the new feature", priority=Priority.MEDIUM)
        score = score_content_relevance(block, ["git", "commit", "database", "migration"])
        assert 0.2 < score < 0.8

    def test_empty_block_returns_zero(self) -> None:
        block = Block(content="", priority=Priority.LOW)
        assert score_content_relevance(block, ["git"]) == 0.0


class TestScoreHistoryRelevance:
    def test_no_history_returns_neutral(self) -> None:
        assert score_history_relevance(None) == 0.5

    def test_zero_uses_returns_neutral(self) -> None:
        profile = SkillRelevanceProfile(
            skill_name="test", block_hash="abc",
            included_count=0, dropped_count=0,
        )
        assert score_history_relevance(profile) == 0.5

    def test_high_inclusion_returns_high(self) -> None:
        profile = SkillRelevanceProfile(
            skill_name="test", block_hash="abc",
            included_count=20, dropped_count=2,
            feedback_sum=15.0,
        )
        score = score_history_relevance(profile)
        assert score > 0.6

    def test_low_inclusion_returns_low(self) -> None:
        profile = SkillRelevanceProfile(
            skill_name="test", block_hash="abc",
            included_count=2, dropped_count=20,
            feedback_sum=-1.0,
        )
        score = score_history_relevance(profile)
        assert score < 0.5

    def test_negative_feedback_lowers_score(self) -> None:
        high_fb = SkillRelevanceProfile(
            skill_name="test", block_hash="abc",
            included_count=10, dropped_count=0,
            feedback_sum=10.0,
        )
        low_fb = SkillRelevanceProfile(
            skill_name="test", block_hash="abc",
            included_count=10, dropped_count=0,
            feedback_sum=-10.0,
        )
        assert score_history_relevance(high_fb) > score_history_relevance(low_fb)


class TestRelevanceScore:
    def test_compute_combined(self) -> None:
        rs = RelevanceScore(
            block_hash="abc", skill_name="test",
            content_score=0.8, history_score=0.6,
        )
        rs.compute_combined(content_weight=0.5, history_weight=0.5)
        assert abs(rs.combined - 0.7) < 0.01

    def test_default_weights(self) -> None:
        rs = RelevanceScore(
            block_hash="abc", skill_name="test",
            content_score=1.0, history_score=0.0,
        )
        rs.compute_combined()  # 0.4 * 1.0 + 0.6 * 0.0 = 0.4
        assert abs(rs.combined - 0.4) < 0.01


class TestRelevanceEngine:
    def _make_blocks(self) -> list[Block]:
        return [
            Block(content="git status shows modified python files", priority=Priority.LOW),
            Block(content="database schema migration for user table", priority=Priority.MEDIUM),
            Block(content="API endpoint documentation for REST service", priority=Priority.HIGH),
        ]

    def test_score_blocks_returns_sorted(self) -> None:
        engine = RelevanceEngine()
        blocks = self._make_blocks()
        scores = engine.score_blocks(blocks, "git_status", ["git", "modified", "files"])
        assert len(scores) == 3
        # Should be sorted by combined score descending
        for i in range(len(scores) - 1):
            assert scores[i].combined >= scores[i + 1].combined

    def test_score_blocks_with_history(self) -> None:
        engine = RelevanceEngine()
        blocks = self._make_blocks()
        from src.storage.usage import block_hash
        bh = block_hash(blocks[1].content)
        history = {
            bh: SkillRelevanceProfile(
                skill_name="test", block_hash=bh,
                included_count=50, dropped_count=0,
                feedback_sum=40.0,
            )
        }
        scores = engine.score_blocks(blocks, "test", ["database"], history)
        # The database block should score high due to both content match and history
        db_score = next(s for s in scores if s.block_hash == bh)
        assert db_score.combined > 0.6

    def test_score_blocks_empty_hints(self) -> None:
        engine = RelevanceEngine()
        blocks = self._make_blocks()
        scores = engine.score_blocks(blocks, "neutral_skill", [])
        # All should get neutral content score (0.5)
        for s in scores:
            assert abs(s.content_score - 0.5) < 0.01

    def test_select_blocks_fits_budget(self) -> None:
        engine = RelevanceEngine()
        blocks = self._make_blocks()
        scores = engine.score_blocks(blocks, "test", ["git"])
        selected, dropped = engine.select_blocks(blocks, scores, token_budget=50)
        total_tokens = sum(b.token_count for b in selected)
        assert total_tokens <= 50

    def test_select_blocks_drops_low_relevance(self) -> None:
        engine = RelevanceEngine()
        blocks = self._make_blocks()
        scores = engine.score_blocks(blocks, "test", ["git"])
        selected, dropped = engine.select_blocks(
            blocks, scores, token_budget=10000, min_relevance=0.9,
        )
        # With very high min_relevance, most blocks should be dropped
        assert len(dropped) >= len(selected)

    def test_select_blocks_all_fit(self) -> None:
        engine = RelevanceEngine()
        blocks = self._make_blocks()
        scores = engine.score_blocks(blocks, "test", ["git"])
        selected, dropped = engine.select_blocks(
            blocks, scores, token_budget=100000, min_relevance=0.0,
        )
        assert len(selected) == 3
        assert len(dropped) == 0
