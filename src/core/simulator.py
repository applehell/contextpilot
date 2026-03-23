"""Simulations-Engine — runs context assembly under varying budgets and strategies."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .assembler import Assembler, AssemblyResult
from .block import Block, Priority
from .compressors.base import BaseCompressor
from .token_budget import TokenBudget


@dataclass
class SimulationScenario:
    """A single simulation configuration."""
    name: str
    budget: int
    compressors: Optional[List[BaseCompressor]] = None
    block_overrides: Optional[List[Block]] = None


@dataclass
class ScenarioResult:
    """Result of running one scenario."""
    scenario_name: str
    budget: int
    used_tokens: int
    block_count: int
    dropped_count: int
    compression_savings: Dict[str, int] = field(default_factory=dict)
    blocks: List[Block] = field(default_factory=list)
    dropped_blocks: List[Block] = field(default_factory=list)

    @property
    def utilization(self) -> float:
        return self.used_tokens / self.budget if self.budget > 0 else 0.0

    @property
    def drop_rate(self) -> float:
        total = self.block_count + self.dropped_count
        return self.dropped_count / total if total > 0 else 0.0


@dataclass
class CompressionDelta:
    """Before/after comparison for a single block's compression."""
    block_index: int
    original_tokens: int
    compressed_tokens: int
    compressor_name: str

    @property
    def savings(self) -> int:
        return self.original_tokens - self.compressed_tokens

    @property
    def ratio(self) -> float:
        return self.compressed_tokens / self.original_tokens if self.original_tokens > 0 else 1.0


@dataclass
class SimulationReport:
    """Full report across all scenarios."""
    scenarios: List[ScenarioResult] = field(default_factory=list)
    compression_deltas: List[CompressionDelta] = field(default_factory=list)

    @property
    def best_utilization(self) -> Optional[ScenarioResult]:
        if not self.scenarios:
            return None
        return max(self.scenarios, key=lambda s: s.utilization)

    @property
    def lowest_drop_rate(self) -> Optional[ScenarioResult]:
        if not self.scenarios:
            return None
        return min(self.scenarios, key=lambda s: s.drop_rate)


class Simulator:
    """Runs assembly simulations across multiple budgets and compressor configurations."""

    def __init__(self, base_compressors: Optional[List[BaseCompressor]] = None) -> None:
        self._base_compressors = base_compressors or []

    def run_scenario(self, blocks: List[Block], scenario: SimulationScenario) -> ScenarioResult:
        input_blocks = scenario.block_overrides if scenario.block_overrides is not None else blocks
        input_blocks = [copy.copy(b) for b in input_blocks]

        compressors = scenario.compressors if scenario.compressors is not None else self._base_compressors
        assembler = Assembler(compressors=compressors)
        result = assembler.assemble_tracked(input_blocks, scenario.budget)

        compression_savings = self._compute_compression_savings(
            result.input_blocks, result.blocks, compressors
        )

        return ScenarioResult(
            scenario_name=scenario.name,
            budget=scenario.budget,
            used_tokens=result.used_tokens,
            block_count=len(result.blocks),
            dropped_count=len(result.dropped_blocks),
            compression_savings=compression_savings,
            blocks=result.blocks,
            dropped_blocks=result.dropped_blocks,
        )

    def run_budget_sweep(
        self,
        blocks: List[Block],
        budgets: List[int],
        compressors: Optional[List[BaseCompressor]] = None,
    ) -> SimulationReport:
        scenarios = [
            SimulationScenario(name=f"budget_{b}", budget=b, compressors=compressors)
            for b in budgets
        ]
        return self.run_scenarios(blocks, scenarios)

    def run_scenarios(self, blocks: List[Block], scenarios: List[SimulationScenario]) -> SimulationReport:
        report = SimulationReport()
        for scenario in scenarios:
            result = self.run_scenario(blocks, scenario)
            report.scenarios.append(result)
        return report

    def analyze_compression(
        self,
        blocks: List[Block],
        compressors: Optional[List[BaseCompressor]] = None,
    ) -> List[CompressionDelta]:
        compressors = compressors if compressors is not None else self._base_compressors
        registry = {c.name: c for c in compressors}
        deltas: List[CompressionDelta] = []

        for i, block in enumerate(blocks):
            if not block.compress_hint:
                continue
            compressor = registry.get(block.compress_hint)
            if compressor is None:
                continue

            original_tokens = block.token_count
            compressed = compressor.compress(copy.copy(block))
            compressed_tokens = compressed.token_count

            deltas.append(CompressionDelta(
                block_index=i,
                original_tokens=original_tokens,
                compressed_tokens=compressed_tokens,
                compressor_name=block.compress_hint,
            ))

        return deltas

    def _compute_compression_savings(
        self,
        input_blocks: List[Block],
        output_blocks: List[Block],
        compressors: List[BaseCompressor],
    ) -> Dict[str, int]:
        from ..storage.usage import block_hash
        input_map = {block_hash(b.content): b for b in input_blocks}
        output_map = {block_hash(b.content): b for b in output_blocks}

        savings: Dict[str, int] = {}
        for bh, inp in input_map.items():
            if not inp.compress_hint:
                continue
            if bh in output_map:
                continue
            for out_b in output_blocks:
                if out_b.compress_hint == inp.compress_hint or out_b.priority == inp.priority:
                    saved = inp.token_count - out_b.token_count
                    if saved > 0:
                        name = inp.compress_hint
                        savings[name] = savings.get(name, 0) + saved
                    break
        return savings
