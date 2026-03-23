"""Tests for src.core.skill_assembler — SkillAssembler and adaptive assembly pipeline."""
from __future__ import annotations

from typing import List

import pytest

from src.core.block import Block, Priority
from src.core.skill_assembler import (
    BudgetAllocation,
    SkillAssembler,
    SkillAssemblyResult,
    SkillContextWindow,
)
from src.core.skill_connector import BaseSkill, SkillConfig, SkillConnector
from src.storage.db import Database
from src.storage.usage import UsageStore


class _GitSkill(BaseSkill):
    """Test skill with context hints for git-related content."""

    def __init__(self) -> None:
        self._context: List[Block] = []

    @property
    def name(self) -> str:
        return "git_test"

    @property
    def description(self) -> str:
        return "Test git skill"

    @property
    def context_hints(self) -> List[str]:
        return ["git", "commit", "branch", "modified"]

    def receive_context(self, blocks: List[Block]) -> None:
        self._context = blocks

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        ctx_count = len(self._context)
        return [Block(
            content=f"Git output with {ctx_count} context blocks",
            priority=Priority.LOW,
        )]


class _DbSkill(BaseSkill):
    """Test skill with context hints for database content."""

    def __init__(self) -> None:
        self._context: List[Block] = []

    @property
    def name(self) -> str:
        return "db_test"

    @property
    def description(self) -> str:
        return "Test database skill"

    @property
    def context_hints(self) -> List[str]:
        return ["database", "schema", "migration", "table", "SQL"]

    def receive_context(self, blocks: List[Block]) -> None:
        self._context = blocks

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        ctx_count = len(self._context)
        return [Block(
            content=f"DB output with {ctx_count} context blocks",
            priority=Priority.MEDIUM,
        )]


class _NeutralSkill(BaseSkill):
    """Test skill with no context hints."""

    @property
    def name(self) -> str:
        return "neutral_test"

    @property
    def description(self) -> str:
        return "Test neutral skill"

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        return [Block(content="neutral output", priority=Priority.MEDIUM)]


def _make_block_pool() -> List[Block]:
    return [
        Block(content="git status shows modified python files in the main branch", priority=Priority.LOW),
        Block(content="database schema migration adds user table with email column", priority=Priority.MEDIUM),
        Block(content="API documentation for REST endpoints and authentication", priority=Priority.HIGH),
        Block(content="git commit history for the last two weeks of development", priority=Priority.LOW),
        Block(content="SQL query optimization for database join performance", priority=Priority.MEDIUM),
    ]


class TestBudgetAllocation:
    def test_equal_allocation_two_skills(self) -> None:
        connector = SkillConnector([_GitSkill(), _DbSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [
            SkillConfig(skill_name="git_test"),
            SkillConfig(skill_name="db_test"),
        ]
        allocs = assembler.allocate_budgets(configs, total_budget=10000)
        assert len(allocs) == 2
        assert "git_test" in allocs
        assert "db_test" in allocs
        # Each should get roughly equal share of 70% of 10000
        for a in allocs.values():
            assert a.tokens > 0
            assert a.tokens <= 7000

    def test_no_enabled_skills(self) -> None:
        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        allocs = assembler.allocate_budgets([], total_budget=10000)
        assert allocs == {}

    def test_disabled_skills_excluded(self) -> None:
        connector = SkillConnector([_GitSkill(), _DbSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [
            SkillConfig(skill_name="git_test", enabled=True),
            SkillConfig(skill_name="db_test", enabled=False),
        ]
        allocs = assembler.allocate_budgets(configs, total_budget=10000)
        assert len(allocs) == 1
        assert "git_test" in allocs

    def test_history_adapts_allocation(self) -> None:
        connector = SkillConnector([_GitSkill(), _DbSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [
            SkillConfig(skill_name="git_test"),
            SkillConfig(skill_name="db_test"),
        ]
        history = {
            "git_test": BudgetAllocation(skill_name="git_test", tokens=3000, efficiency=2.0),
            "db_test": BudgetAllocation(skill_name="db_test", tokens=3000, efficiency=0.5),
        }
        allocs = assembler.allocate_budgets(configs, total_budget=10000, history=history)
        assert allocs["git_test"].tokens > allocs["db_test"].tokens


class TestSkillAssembler:
    def test_basic_assembly(self) -> None:
        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=10000)

        assert isinstance(result, SkillAssemblyResult)
        assert result.skill_count == 1
        assert "git_test" in result.windows
        assert len(result.final_blocks) > 0

    def test_multi_skill_assembly(self) -> None:
        connector = SkillConnector([_GitSkill(), _DbSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [
            SkillConfig(skill_name="git_test"),
            SkillConfig(skill_name="db_test"),
        ]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=10000)

        assert result.skill_count == 2
        assert len(result.final_blocks) == 2

    def test_context_injection(self) -> None:
        git_skill = _GitSkill()
        connector = SkillConnector([git_skill])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=10000)

        window = result.windows["git_test"]
        assert len(window.injected_blocks) > 0
        # Git-related blocks should be injected
        assert "context blocks" in result.final_blocks[0].content

    def test_empty_pool(self) -> None:
        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]

        result = assembler.assemble([], configs, total_budget=10000)

        assert result.skill_count == 1
        assert len(result.final_blocks) == 1
        # Should still generate, just with 0 context
        assert "0 context blocks" in result.final_blocks[0].content

    def test_no_skills_enabled(self) -> None:
        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test", enabled=False)]

        result = assembler.assemble(_make_block_pool(), configs, total_budget=10000)

        assert result.skill_count == 0
        assert result.final_blocks == []

    def test_neutral_skill_gets_all_blocks(self) -> None:
        connector = SkillConnector([_NeutralSkill()])
        assembler = SkillAssembler(connector=connector, min_relevance=0.0)
        configs = [SkillConfig(skill_name="neutral_test")]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=100000)

        window = result.windows["neutral_test"]
        # Neutral skill has no hints → all blocks get 0.5 score → all included
        assert len(window.injected_blocks) == len(pool)

    def test_skill_window_efficiency(self) -> None:
        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=10000)

        window = result.windows["git_test"]
        assert 0.0 <= window.efficiency <= 1.0

    def test_tight_budget_drops_blocks(self) -> None:
        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]
        # Create large blocks that won't all fit in a tiny budget
        pool = [
            Block(content="git " + "word " * 200, priority=Priority.LOW),
            Block(content="git " + "data " * 200, priority=Priority.MEDIUM),
            Block(content="other " + "text " * 200, priority=Priority.HIGH),
        ]

        # 70% of 100 = 70 tokens → can't fit ~600 token blocks
        result = assembler.assemble(pool, configs, total_budget=100)

        window = result.windows["git_test"]
        assert len(window.injected_blocks) < len(pool)


class TestRecordOutcomes:
    def test_records_to_usage_store(self) -> None:
        db = Database(None)
        usage_store = UsageStore(db)

        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=10000)
        assembler.record_outcomes(result, usage_store)

        # Check that relevance was recorded
        relevance = usage_store.get_skill_relevance("git_test")
        assert len(relevance) > 0

    def test_records_budget_allocation(self) -> None:
        db = Database(None)
        usage_store = UsageStore(db)

        connector = SkillConnector([_GitSkill()])
        assembler = SkillAssembler(connector=connector)
        configs = [SkillConfig(skill_name="git_test")]
        pool = _make_block_pool()

        result = assembler.assemble(pool, configs, total_budget=10000)
        assembler.record_outcomes(result, usage_store)

        budgets = usage_store.get_skill_budgets()
        assert "git_test" in budgets
