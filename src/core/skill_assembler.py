"""Skill Assembler — per-skill adaptive context injection.

Orchestrates the full pipeline:
1. Allocate token budgets across enabled skills
2. Score blocks for relevance per skill
3. Select + compress blocks per skill's context window
4. Inject context into skills before they generate
5. Record outcomes for iterative adaptation
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .assembler import Assembler
from .block import Block, Priority
from .compressors.base import BaseCompressor
from .relevance import RelevanceEngine, RelevanceScore, SkillRelevanceProfile
from .skill_connector import BaseSkill, SkillConfig, SkillConnector
from .token_budget import TokenBudget


@dataclass
class SkillContextWindow:
    """The assembled context window for one skill."""
    skill_name: str
    injected_blocks: List[Block] = field(default_factory=list)
    dropped_blocks: List[Block] = field(default_factory=list)
    generated_blocks: List[Block] = field(default_factory=list)
    token_budget: int = 0
    tokens_used: int = 0
    relevance_scores: List[RelevanceScore] = field(default_factory=list)

    @property
    def efficiency(self) -> float:
        if self.token_budget == 0:
            return 0.0
        return self.tokens_used / self.token_budget


@dataclass
class SkillAssemblyResult:
    """Result of a full skill-aware assembly."""
    windows: Dict[str, SkillContextWindow] = field(default_factory=dict)
    final_blocks: List[Block] = field(default_factory=list)
    total_tokens: int = 0
    total_budget: int = 0

    @property
    def skill_count(self) -> int:
        return len(self.windows)


@dataclass
class BudgetAllocation:
    """Token budget allocated to a skill."""
    skill_name: str
    tokens: int
    efficiency: float = 1.0


class SkillAssembler:
    """Per-skill adaptive context assembler.

    For each enabled skill:
    1. Allocates a portion of the total token budget
    2. Scores all available blocks for relevance to the skill
    3. Selects the most relevant blocks that fit the budget
    4. Compresses blocks as needed
    5. Injects the context window into the skill via receive_context()
    6. Collects the skill's generated blocks

    After assembly, call record_outcomes() to update the DB for iterative learning.
    """

    def __init__(
        self,
        connector: SkillConnector,
        compressors: Optional[List[BaseCompressor]] = None,
        relevance_engine: Optional[RelevanceEngine] = None,
        min_relevance: float = 0.2,
    ) -> None:
        self._connector = connector
        self._compressors = compressors or []
        self._assembler = Assembler(compressors=compressors)
        self._relevance = relevance_engine or RelevanceEngine()
        self._min_relevance = min_relevance

    def allocate_budgets(
        self,
        configs: List[SkillConfig],
        total_budget: int,
        history: Optional[Dict[str, BudgetAllocation]] = None,
    ) -> Dict[str, BudgetAllocation]:
        """Allocate token budgets across enabled skills.

        Strategy:
        - Base: equal share per skill
        - Adapted: skills with higher historical efficiency get more
        - Reserve 30% for generated blocks (skills output)
        """
        enabled = [c for c in configs if c.enabled]
        if not enabled:
            return {}

        context_budget = int(total_budget * 0.7)  # 70% for injected context
        history = history or {}

        # Compute weights from historical efficiency
        weights: Dict[str, float] = {}
        for cfg in enabled:
            prev = history.get(cfg.skill_name)
            if prev and prev.efficiency > 0:
                weights[cfg.skill_name] = prev.efficiency
            else:
                weights[cfg.skill_name] = 1.0

        total_weight = sum(weights.values()) or 1.0

        allocations: Dict[str, BudgetAllocation] = {}
        for cfg in enabled:
            share = weights[cfg.skill_name] / total_weight
            tokens = max(100, int(context_budget * share))
            allocations[cfg.skill_name] = BudgetAllocation(
                skill_name=cfg.skill_name,
                tokens=tokens,
                efficiency=weights[cfg.skill_name],
            )

        return allocations

    def assemble(
        self,
        block_pool: List[Block],
        configs: List[SkillConfig],
        total_budget: int,
        relevance_history: Optional[Dict[str, Dict[str, SkillRelevanceProfile]]] = None,
        budget_history: Optional[Dict[str, BudgetAllocation]] = None,
    ) -> SkillAssemblyResult:
        """Run the full per-skill adaptive assembly pipeline.

        Args:
            block_pool: All available blocks (manual + imported)
            configs: Skill configurations
            total_budget: Total token budget
            relevance_history: {skill_name: {block_hash: SkillRelevanceProfile}}
            budget_history: Previous budget allocations for adaptation
        """
        relevance_history = relevance_history or {}
        result = SkillAssemblyResult(total_budget=total_budget)

        # Step 1: Allocate budgets
        allocations = self.allocate_budgets(configs, total_budget, budget_history)

        # Step 2: For each skill, score → select → compress → inject
        for cfg in configs:
            if not cfg.enabled:
                continue
            skill = self._connector.get_skill(cfg.skill_name)
            if skill is None:
                continue

            alloc = allocations.get(cfg.skill_name)
            if alloc is None:
                continue

            window = self._assemble_for_skill(
                skill=skill,
                config=cfg,
                block_pool=block_pool,
                token_budget=alloc.tokens,
                skill_history=relevance_history.get(cfg.skill_name, {}),
            )
            result.windows[cfg.skill_name] = window
            result.final_blocks.extend(window.generated_blocks)

        result.total_tokens = sum(b.token_count for b in result.final_blocks)
        return result

    def _assemble_for_skill(
        self,
        skill: BaseSkill,
        config: SkillConfig,
        block_pool: List[Block],
        token_budget: int,
        skill_history: Dict[str, SkillRelevanceProfile],
    ) -> SkillContextWindow:
        """Assemble a context window for one skill."""
        window = SkillContextWindow(
            skill_name=skill.name,
            token_budget=token_budget,
        )

        if not block_pool:
            # No blocks to inject — just generate
            window.generated_blocks = skill.generate_blocks(config)
            return window

        # Score blocks for relevance
        scores = self._relevance.score_blocks(
            blocks=block_pool,
            skill_name=skill.name,
            context_hints=skill.context_hints,
            history=skill_history,
        )
        window.relevance_scores = scores

        # Select blocks that fit budget
        selected, dropped = self._relevance.select_blocks(
            blocks=block_pool,
            scores=scores,
            token_budget=token_budget,
            min_relevance=self._min_relevance,
        )

        # Compress selected blocks using the standard assembler
        if selected:
            compressed = self._assembler.assemble(selected, token_budget)
            window.injected_blocks = compressed
        else:
            window.injected_blocks = []

        window.dropped_blocks = dropped
        window.tokens_used = sum(b.token_count for b in window.injected_blocks)

        # Inject context into skill and generate
        skill.receive_context(window.injected_blocks)
        window.generated_blocks = skill.generate_blocks(config)

        return window

    def record_outcomes(
        self,
        result: SkillAssemblyResult,
        usage_store: Any,
    ) -> None:
        """Record assembly outcomes for iterative learning.

        Updates skill_block_relevance table with inclusion/drop data.
        Updates skill_budget_allocation with efficiency data.
        """
        now = time.time()

        for skill_name, window in result.windows.items():
            from ..storage.usage import block_hash as compute_hash

            # Record included blocks
            for block in window.injected_blocks:
                bh = compute_hash(block.content)
                usage_store.record_skill_relevance(
                    skill_name=skill_name,
                    block_hash=bh,
                    included=True,
                )

            # Record dropped blocks
            for block in window.dropped_blocks:
                bh = compute_hash(block.content)
                usage_store.record_skill_relevance(
                    skill_name=skill_name,
                    block_hash=bh,
                    included=False,
                )

            # Record budget efficiency
            usage_store.save_skill_budget(
                skill_name=skill_name,
                project_name="",
                token_budget=window.token_budget,
                efficiency=window.efficiency,
            )
