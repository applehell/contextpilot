"""Relevance scoring — computes how relevant a block is for a specific skill."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .block import Block
from .token_budget import TokenBudget


@dataclass
class RelevanceScore:
    """Score for a block-skill pair."""
    block_hash: str
    skill_name: str
    content_score: float = 0.0
    history_score: float = 0.0
    combined: float = 0.0

    def compute_combined(self, content_weight: float = 0.4, history_weight: float = 0.6) -> None:
        self.combined = content_weight * self.content_score + history_weight * self.history_score


@dataclass
class SkillRelevanceProfile:
    """Historical relevance data for a skill-block pair from the DB."""
    skill_name: str
    block_hash: str
    score: float = 0.5
    included_count: int = 0
    dropped_count: int = 0
    feedback_sum: float = 0.0

    @property
    def total_uses(self) -> int:
        return self.included_count + self.dropped_count

    @property
    def inclusion_rate(self) -> float:
        if self.total_uses == 0:
            return 0.5
        return self.included_count / self.total_uses

    @property
    def feedback_avg(self) -> float:
        if self.included_count == 0:
            return 0.0
        return self.feedback_sum / self.included_count


def _extract_keywords(text: str) -> Set[str]:
    """Extract normalized keywords from text."""
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]{2,}", text.lower())
    return set(words)


def score_content_relevance(block: Block, context_hints: List[str]) -> float:
    """Score how well a block's content matches a skill's context hints.

    Returns a value in [0.0, 1.0].
    - 1.0 = perfect match (all hints found in block)
    - 0.0 = no overlap
    - If hints is empty, returns 0.5 (neutral — no preference declared)
    """
    if not context_hints:
        return 0.5

    block_keywords = _extract_keywords(block.content)
    if not block_keywords:
        return 0.0

    hint_keywords: Set[str] = set()
    for hint in context_hints:
        hint_keywords.update(_extract_keywords(hint))

    if not hint_keywords:
        return 0.5

    overlap = len(block_keywords & hint_keywords)
    max_possible = len(hint_keywords)
    raw = overlap / max_possible

    # Boost: if block is short and focused, that's more relevant
    token_count = block.token_count
    if token_count < 200:
        raw = min(1.0, raw * 1.2)

    return min(1.0, raw)


def score_history_relevance(profile: Optional[SkillRelevanceProfile]) -> float:
    """Score based on historical inclusion/feedback data.

    Returns [0.0, 1.0]:
    - New blocks with no history get 0.5 (neutral)
    - High inclusion + positive feedback → high score
    - Low inclusion + negative feedback → low score
    """
    if profile is None or profile.total_uses == 0:
        return 0.5

    inclusion_signal = profile.inclusion_rate

    feedback_signal = 0.5
    if profile.included_count > 0:
        # Map feedback_avg from [-1, 1] to [0, 1]
        feedback_signal = (profile.feedback_avg + 1.0) / 2.0

    # More history = more confidence in the score
    confidence = min(1.0, math.log2(profile.total_uses + 1) / 5.0)

    # Blend: with low confidence, stay near 0.5 (neutral)
    raw = inclusion_signal * 0.6 + feedback_signal * 0.4
    return 0.5 + (raw - 0.5) * confidence


class RelevanceEngine:
    """Scores blocks for relevance to a specific skill, combining content matching
    and historical adaptation."""

    def __init__(self, content_weight: float = 0.4, history_weight: float = 0.6) -> None:
        self._content_weight = content_weight
        self._history_weight = history_weight

    def score_blocks(
        self,
        blocks: List[Block],
        skill_name: str,
        context_hints: List[str],
        history: Optional[Dict[str, SkillRelevanceProfile]] = None,
    ) -> List[RelevanceScore]:
        """Score all blocks for relevance to a skill.

        Args:
            blocks: Pool of available blocks
            skill_name: Target skill name
            context_hints: Keywords/tags from the skill's context_hints property
            history: Dict of block_hash → SkillRelevanceProfile from DB

        Returns:
            List of RelevanceScore sorted by combined score (highest first)
        """
        from ..storage.usage import block_hash as compute_hash

        history = history or {}
        scores: List[RelevanceScore] = []

        for block in blocks:
            bh = compute_hash(block.content)
            content_score = score_content_relevance(block, context_hints)
            profile = history.get(bh)
            history_score = score_history_relevance(profile)

            rs = RelevanceScore(
                block_hash=bh,
                skill_name=skill_name,
                content_score=content_score,
                history_score=history_score,
            )
            rs.compute_combined(self._content_weight, self._history_weight)
            scores.append(rs)

        scores.sort(key=lambda s: s.combined, reverse=True)
        return scores

    def select_blocks(
        self,
        blocks: List[Block],
        scores: List[RelevanceScore],
        token_budget: int,
        min_relevance: float = 0.2,
    ) -> tuple[List[Block], List[Block]]:
        """Select blocks that fit within token_budget, ordered by relevance.

        Returns:
            (selected_blocks, dropped_blocks)
        """
        from ..storage.usage import block_hash as compute_hash

        score_map = {s.block_hash: s for s in scores}
        block_with_scores = []
        for b in blocks:
            bh = compute_hash(b.content)
            sc = score_map.get(bh)
            combined = sc.combined if sc else 0.5
            block_with_scores.append((b, bh, combined))

        # Sort by relevance (highest first)
        block_with_scores.sort(key=lambda x: x[2], reverse=True)

        selected: List[Block] = []
        dropped: List[Block] = []
        remaining = token_budget

        for block, bh, score in block_with_scores:
            if score < min_relevance:
                dropped.append(block)
                continue
            if block.token_count <= remaining:
                selected.append(block)
                remaining -= block.token_count
            else:
                dropped.append(block)

        return selected, dropped
