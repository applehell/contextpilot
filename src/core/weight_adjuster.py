"""Weight Adjuster — automatically adjusts block priorities based on usage data and feedback."""
from __future__ import annotations

import copy
import time
from typing import List, Optional

from .block import Block, Priority
from ..storage.usage import BlockWeight, UsageStore, block_hash


# Weight thresholds for priority promotion/demotion
HIGH_THRESHOLD = 1.5
LOW_THRESHOLD = 0.5

# Blending factors
USAGE_FACTOR = 0.6
FEEDBACK_FACTOR = 0.4


class WeightAdjuster:
    """Computes and applies block weights from usage history and feedback scores.

    Weight formula:
        base_weight = 1.0
        usage_signal  = log2(usage_count + 1) / log2(median_usage + 1)  [clamped 0.2–3.0]
        feedback_signal = feedback_score  [-1.0 to 1.0]
        weight = base_weight * (USAGE_FACTOR * usage_signal + FEEDBACK_FACTOR * (1 + feedback_signal))

    Priority adjustment:
        weight >= HIGH_THRESHOLD  → promote to HIGH
        weight <= LOW_THRESHOLD   → demote to LOW
        otherwise                 → keep MEDIUM
    """

    def __init__(self, usage_store: UsageStore) -> None:
        self._store = usage_store

    def compute_weight(
        self,
        content: str,
        project_name: Optional[str] = None,
    ) -> BlockWeight:
        bh = block_hash(content)
        counts = self._store.get_usage_counts(project_name)
        usage_count = counts.get(bh, 0)

        # Compute median usage for normalization
        all_counts = sorted(counts.values()) if counts else [0]
        mid = len(all_counts) // 2
        median_usage = all_counts[mid] if all_counts else 1

        import math
        usage_signal = math.log2(usage_count + 1) / math.log2(median_usage + 2)
        usage_signal = max(0.2, min(3.0, usage_signal))

        feedback_score = self._store.get_feedback_score(bh)

        weight = USAGE_FACTOR * usage_signal + FEEDBACK_FACTOR * (1.0 + feedback_score)

        bw = BlockWeight(
            block_hash=bh,
            project_name=project_name,
            weight=weight,
            usage_count=usage_count,
            feedback_score=feedback_score,
            updated_at=time.time(),
        )
        self._store.save_weight(bw)
        return bw

    def adjust_priority(self, block: Block, weight: BlockWeight) -> Block:
        """Return a copy of the block with priority adjusted based on weight."""
        adjusted = copy.copy(block)
        if block.priority == Priority.MEDIUM:
            if weight.weight >= HIGH_THRESHOLD:
                adjusted.priority = Priority.HIGH
            elif weight.weight <= LOW_THRESHOLD:
                adjusted.priority = Priority.LOW
        return adjusted

    def adjust_blocks(
        self,
        blocks: List[Block],
        project_name: Optional[str] = None,
    ) -> List[Block]:
        """Compute weights and adjust priorities for all blocks."""
        result: List[Block] = []
        for b in blocks:
            w = self.compute_weight(b.content, project_name)
            result.append(self.adjust_priority(b, w))
        return result

    def recompute_all_weights(self, project_name: Optional[str] = None) -> int:
        """Recompute weights for all known block hashes. Returns count updated."""
        counts = self._store.get_usage_counts(project_name)
        updated = 0
        for bh, usage_count in counts.items():
            import math
            all_counts = sorted(counts.values())
            mid = len(all_counts) // 2
            median_usage = all_counts[mid] if all_counts else 1

            usage_signal = math.log2(usage_count + 1) / math.log2(median_usage + 2)
            usage_signal = max(0.2, min(3.0, usage_signal))

            feedback_score = self._store.get_feedback_score(bh)
            weight = USAGE_FACTOR * usage_signal + FEEDBACK_FACTOR * (1.0 + feedback_score)

            bw = BlockWeight(
                block_hash=bh,
                project_name=project_name,
                weight=weight,
                usage_count=usage_count,
                feedback_score=feedback_score,
                updated_at=time.time(),
            )
            self._store.save_weight(bw)
            updated += 1
        return updated
