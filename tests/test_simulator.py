"""Tests for the Simulator engine."""
from __future__ import annotations

import pytest
from src.core.block import Block, Priority
from src.core.simulator import (
    CompressionDelta,
    ScenarioResult,
    SimulationReport,
    SimulationScenario,
    Simulator,
)
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.code_compact import CodeCompactCompressor


def _make_blocks():
    return [
        Block("High priority system prompt with important instructions.", Priority.HIGH),
        Block(
            "This is a medium block with some content that could be compressed. "
            "It contains multiple sentences. Each sentence adds tokens. "
            "The compressor should reduce this to bullet points.",
            Priority.MEDIUM,
            compress_hint="bullet_extract",
        ),
        Block("Low priority debug info", Priority.LOW),
        Block("Another medium block with code:\ndef foo():\n    return 42", Priority.MEDIUM),
    ]


class TestSimulationScenario:
    def test_run_single_scenario_within_budget(self):
        blocks = _make_blocks()
        sim = Simulator()
        scenario = SimulationScenario(name="large", budget=50_000)
        result = sim.run_scenario(blocks, scenario)
        assert result.scenario_name == "large"
        assert result.budget == 50_000
        assert result.block_count == 4
        assert result.dropped_count == 0
        assert result.used_tokens > 0
        assert result.utilization < 1.0

    def test_run_scenario_drops_low(self):
        blocks = _make_blocks()
        sim = Simulator()
        total_tokens = sum(b.token_count for b in blocks)
        tight_budget = total_tokens - 1
        scenario = SimulationScenario(name="tight", budget=tight_budget)
        result = sim.run_scenario(blocks, scenario)
        assert result.dropped_count >= 1

    def test_run_scenario_with_compressors(self):
        blocks = _make_blocks()
        compressors = [BulletExtractCompressor()]
        sim = Simulator(base_compressors=compressors)
        scenario = SimulationScenario(name="compressed", budget=30)
        result = sim.run_scenario(blocks, scenario)
        assert result.used_tokens <= 30 or result.block_count < 4

    def test_run_scenario_with_overrides(self):
        blocks = _make_blocks()
        override = [Block("Only this block", Priority.HIGH)]
        sim = Simulator()
        scenario = SimulationScenario(name="override", budget=50_000, block_overrides=override)
        result = sim.run_scenario(blocks, scenario)
        assert result.block_count == 1

    def test_empty_blocks(self):
        sim = Simulator()
        scenario = SimulationScenario(name="empty", budget=1000)
        result = sim.run_scenario([], scenario)
        assert result.block_count == 0
        assert result.used_tokens == 0


class TestBudgetSweep:
    def test_sweep_returns_multiple_scenarios(self):
        blocks = _make_blocks()
        sim = Simulator()
        report = sim.run_budget_sweep(blocks, [500, 2000, 5000, 50000])
        assert len(report.scenarios) == 4

    def test_sweep_utilization_decreases_with_budget(self):
        blocks = _make_blocks()
        sim = Simulator()
        report = sim.run_budget_sweep(blocks, [100, 1000, 50000])
        utils = [s.utilization for s in report.scenarios]
        assert utils[-1] <= utils[0]

    def test_sweep_more_blocks_kept_at_higher_budget(self):
        blocks = _make_blocks()
        sim = Simulator()
        report = sim.run_budget_sweep(blocks, [10, 50000])
        assert report.scenarios[-1].block_count >= report.scenarios[0].block_count


class TestCompressionAnalysis:
    def test_analyze_finds_compressible_blocks(self):
        blocks = _make_blocks()
        compressors = [BulletExtractCompressor()]
        sim = Simulator(base_compressors=compressors)
        deltas = sim.analyze_compression(blocks)
        assert len(deltas) >= 1
        for d in deltas:
            assert d.original_tokens > 0
            assert d.compressor_name == "bullet_extract"

    def test_analyze_empty_blocks(self):
        sim = Simulator()
        deltas = sim.analyze_compression([])
        assert deltas == []

    def test_no_compressible_blocks(self):
        blocks = [Block("plain text", Priority.HIGH)]
        sim = Simulator(base_compressors=[BulletExtractCompressor()])
        deltas = sim.analyze_compression(blocks)
        assert deltas == []


class TestScenarioResult:
    def test_utilization_zero_budget(self):
        r = ScenarioResult(scenario_name="x", budget=0, used_tokens=0, block_count=0, dropped_count=0)
        assert r.utilization == 0.0

    def test_drop_rate(self):
        r = ScenarioResult(scenario_name="x", budget=100, used_tokens=50, block_count=3, dropped_count=1)
        assert r.drop_rate == pytest.approx(0.25)

    def test_drop_rate_zero(self):
        r = ScenarioResult(scenario_name="x", budget=100, used_tokens=50, block_count=0, dropped_count=0)
        assert r.drop_rate == 0.0


class TestSimulationReport:
    def test_best_utilization(self):
        r = SimulationReport(scenarios=[
            ScenarioResult("a", budget=100, used_tokens=90, block_count=2, dropped_count=0),
            ScenarioResult("b", budget=100, used_tokens=50, block_count=2, dropped_count=0),
        ])
        assert r.best_utilization.scenario_name == "a"

    def test_lowest_drop_rate(self):
        r = SimulationReport(scenarios=[
            ScenarioResult("a", budget=100, used_tokens=90, block_count=2, dropped_count=2),
            ScenarioResult("b", budget=100, used_tokens=50, block_count=3, dropped_count=0),
        ])
        assert r.lowest_drop_rate.scenario_name == "b"

    def test_empty_report(self):
        r = SimulationReport()
        assert r.best_utilization is None
        assert r.lowest_drop_rate is None


class TestCompressionDelta:
    def test_savings(self):
        d = CompressionDelta(block_index=0, original_tokens=100, compressed_tokens=60, compressor_name="x")
        assert d.savings == 40
        assert d.ratio == pytest.approx(0.6)

    def test_zero_original(self):
        d = CompressionDelta(block_index=0, original_tokens=0, compressed_tokens=0, compressor_name="x")
        assert d.ratio == 1.0
