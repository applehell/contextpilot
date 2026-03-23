"""Tests for skill_block_relevance and skill_budget_allocation in UsageStore."""
from __future__ import annotations

import pytest

from src.storage.db import Database
from src.storage.usage import UsageStore


@pytest.fixture()
def usage_store() -> UsageStore:
    db = Database(None)  # in-memory
    return UsageStore(db)


class TestSkillBlockRelevance:
    def test_record_included(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True)
        rel = usage_store.get_skill_relevance("git")
        assert "hash1" in rel
        assert rel["hash1"].included_count == 1
        assert rel["hash1"].dropped_count == 0

    def test_record_dropped(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=False)
        rel = usage_store.get_skill_relevance("git")
        assert rel["hash1"].included_count == 0
        assert rel["hash1"].dropped_count == 1

    def test_accumulates(self, usage_store: UsageStore) -> None:
        for _ in range(5):
            usage_store.record_skill_relevance("git", "hash1", included=True)
        for _ in range(3):
            usage_store.record_skill_relevance("git", "hash1", included=False)
        rel = usage_store.get_skill_relevance("git")
        assert rel["hash1"].included_count == 5
        assert rel["hash1"].dropped_count == 3

    def test_multiple_blocks(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True)
        usage_store.record_skill_relevance("git", "hash2", included=False)
        rel = usage_store.get_skill_relevance("git")
        assert len(rel) == 2

    def test_different_skills_isolated(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True)
        usage_store.record_skill_relevance("db", "hash1", included=False)
        git_rel = usage_store.get_skill_relevance("git")
        db_rel = usage_store.get_skill_relevance("db")
        assert git_rel["hash1"].included_count == 1
        assert db_rel["hash1"].dropped_count == 1

    def test_record_with_feedback(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True, feedback=1.0)
        usage_store.record_skill_relevance("git", "hash1", included=True, feedback=0.5)
        rel = usage_store.get_skill_relevance("git")
        assert abs(rel["hash1"].feedback_sum - 1.5) < 0.01


class TestSkillFeedback:
    def test_record_positive_feedback(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True)
        usage_store.record_skill_feedback("git", "hash1", helpful=True)
        rel = usage_store.get_skill_relevance("git")
        assert rel["hash1"].feedback_sum == 1.0

    def test_record_negative_feedback(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True)
        usage_store.record_skill_feedback("git", "hash1", helpful=False)
        rel = usage_store.get_skill_relevance("git")
        assert rel["hash1"].feedback_sum == -1.0

    def test_feedback_accumulates(self, usage_store: UsageStore) -> None:
        usage_store.record_skill_relevance("git", "hash1", included=True)
        usage_store.record_skill_feedback("git", "hash1", helpful=True)
        usage_store.record_skill_feedback("git", "hash1", helpful=True)
        usage_store.record_skill_feedback("git", "hash1", helpful=False)
        rel = usage_store.get_skill_relevance("git")
        assert abs(rel["hash1"].feedback_sum - 1.0) < 0.01  # +1 +1 -1 = 1


class TestUpdateRelevanceScores:
    def test_recomputes_scores(self, usage_store: UsageStore) -> None:
        for _ in range(8):
            usage_store.record_skill_relevance("git", "hash1", included=True, feedback=0.5)
        for _ in range(2):
            usage_store.record_skill_relevance("git", "hash1", included=False)
        usage_store.update_skill_relevance_scores("git")
        rel = usage_store.get_skill_relevance("git")
        # inclusion_rate = 8/10 = 0.8, feedback_avg = 4.0/8 = 0.5
        assert rel["hash1"].score > 0.5


class TestSkillBudgetAllocation:
    def test_save_and_get(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_budget("git", "", 3000, 0.85)
        budgets = usage_store.get_skill_budgets("")
        assert "git" in budgets
        assert budgets["git"]["tokens"] == 3000
        assert abs(budgets["git"]["efficiency"] - 0.85) < 0.01

    def test_upsert(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_budget("git", "", 3000, 0.85)
        usage_store.save_skill_budget("git", "", 4000, 0.92)
        budgets = usage_store.get_skill_budgets("")
        assert budgets["git"]["tokens"] == 4000

    def test_multiple_skills(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_budget("git", "", 3000, 0.85)
        usage_store.save_skill_budget("db", "", 5000, 0.70)
        budgets = usage_store.get_skill_budgets("")
        assert len(budgets) == 2

    def test_project_isolation(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_budget("git", "project_a", 3000, 0.85)
        usage_store.save_skill_budget("git", "project_b", 5000, 0.70)
        a = usage_store.get_skill_budgets("project_a")
        b = usage_store.get_skill_budgets("project_b")
        assert a["git"]["tokens"] == 3000
        assert b["git"]["tokens"] == 5000
