"""Tests for the Skill Connectivity Graph."""
from __future__ import annotations

import pytest
from src.core.block import Block, Priority
from src.core.skill_connector import BaseSkill, SkillConfig, SkillConnector
from src.core.skill_graph import (
    BlockNode,
    Edge,
    SkillGraph,
    SkillNode,
    build_skill_graph,
)


class MockSkillA(BaseSkill):
    @property
    def name(self) -> str:
        return "skill_a"

    @property
    def description(self) -> str:
        return "Produces two blocks"

    def generate_blocks(self, config):
        return [
            Block("Block from skill A number one", Priority.HIGH),
            Block("Block from skill A number two", Priority.MEDIUM),
        ]


class MockSkillB(BaseSkill):
    @property
    def name(self) -> str:
        return "skill_b"

    @property
    def description(self) -> str:
        return "Produces one block"

    def generate_blocks(self, config):
        return [Block("Block from skill B", Priority.LOW)]


class EmptySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "empty_skill"

    @property
    def description(self) -> str:
        return "Produces nothing"

    def generate_blocks(self, config):
        return []


class TestBuildSkillGraph:
    def test_basic_graph(self):
        connector = SkillConnector([MockSkillA(), MockSkillB()])
        configs = [SkillConfig("skill_a"), SkillConfig("skill_b")]
        graph = build_skill_graph(connector, configs)

        assert graph.skill_count == 2
        assert graph.block_count == 3
        assert len(graph.edges) == 3

    def test_disabled_skill_excluded(self):
        connector = SkillConnector([MockSkillA(), MockSkillB()])
        configs = [SkillConfig("skill_a"), SkillConfig("skill_b", enabled=False)]
        graph = build_skill_graph(connector, configs)

        assert graph.skill_count == 1
        assert "skill_b" not in graph.skill_nodes

    def test_empty_skill(self):
        connector = SkillConnector([EmptySkill()])
        configs = [SkillConfig("empty_skill")]
        graph = build_skill_graph(connector, configs)

        assert graph.skill_count == 1
        assert graph.block_count == 0

    def test_unknown_skill_ignored(self):
        connector = SkillConnector([MockSkillA()])
        configs = [SkillConfig("nonexistent")]
        graph = build_skill_graph(connector, configs)

        assert graph.skill_count == 0

    def test_blocks_for_skill(self):
        connector = SkillConnector([MockSkillA(), MockSkillB()])
        configs = [SkillConfig("skill_a"), SkillConfig("skill_b")]
        graph = build_skill_graph(connector, configs)

        blocks_a = graph.blocks_for_skill("skill_a")
        assert len(blocks_a) == 2
        blocks_b = graph.blocks_for_skill("skill_b")
        assert len(blocks_b) == 1

    def test_skill_for_block(self):
        connector = SkillConnector([MockSkillA()])
        configs = [SkillConfig("skill_a")]
        graph = build_skill_graph(connector, configs)

        for bh in graph.block_nodes:
            assert graph.skill_for_block(bh) == "skill_a"
        assert graph.skill_for_block("nonexistent") is None

    def test_token_budget_by_skill(self):
        connector = SkillConnector([MockSkillA(), MockSkillB()])
        configs = [SkillConfig("skill_a"), SkillConfig("skill_b")]
        graph = build_skill_graph(connector, configs)

        budgets = graph.token_budget_by_skill()
        assert "skill_a" in budgets
        assert "skill_b" in budgets
        assert all(v > 0 for v in budgets.values())


class TestSkillGraph:
    def test_empty_graph(self):
        graph = SkillGraph()
        assert graph.skill_count == 0
        assert graph.block_count == 0

    def test_blocks_for_nonexistent_skill(self):
        graph = SkillGraph()
        assert graph.blocks_for_skill("nope") == []
