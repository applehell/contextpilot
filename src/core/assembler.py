from __future__ import annotations

import copy
import uuid
from typing import Dict, List, Optional

from .block import Block, Priority
from .compressors.base import BaseCompressor
from .token_budget import TokenBudget


_PRIORITY_ORDER: Dict[Priority, int] = {
    Priority.HIGH: 0,
    Priority.MEDIUM: 1,
    Priority.LOW: 2,
}


class AssemblyResult:
    """Result of an assembly operation, including metadata for tracking."""

    def __init__(
        self,
        blocks: List[Block],
        assembly_id: str,
        budget: int,
        input_blocks: List[Block],
        dropped_blocks: List[Block],
    ) -> None:
        self.blocks = blocks
        self.assembly_id = assembly_id
        self.budget = budget
        self.input_blocks = input_blocks
        self.dropped_blocks = dropped_blocks

    @property
    def used_tokens(self) -> int:
        return sum(b.token_count for b in self.blocks)


class Assembler:
    """Token-budget assembler.

    Accepts a list of Blocks and a token budget, then returns an ordered
    list of blocks that fits within the budget.  When the budget is exceeded
    the following reduction strategy is applied in order:

    1. Drop LOW-priority blocks (cheapest loss).
    2. Compress MEDIUM-priority blocks that carry a compress_hint pointing to
       a registered compressor.
    3. Truncate HIGH-priority blocks as a last resort (content is cut).
    """

    def __init__(self, compressors: Optional[List[BaseCompressor]] = None) -> None:
        self._registry: Dict[str, BaseCompressor] = {}
        for c in compressors or []:
            self._registry[c.name] = c

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, compressor: BaseCompressor) -> None:
        self._registry[compressor.name] = compressor

    def assemble(self, blocks: List[Block], budget: int) -> List[Block]:
        """Return the optimised block list within *budget* tokens."""
        working: List[Block] = [copy.copy(b) for b in blocks]

        def total() -> int:
            return sum(b.token_count for b in working)

        # Fast path: everything fits already.
        if total() <= budget:
            return self._sorted(working)

        # Phase 1 — drop LOW-priority blocks one at a time.
        for b in [x for x in working if x.priority == Priority.LOW]:
            working.remove(b)
            if total() <= budget:
                return self._sorted(working)

        # Phase 2 — compress MEDIUM-priority blocks that have a compress_hint.
        for b in [x for x in working if x.priority == Priority.MEDIUM and x.compress_hint]:
            compressor = self._registry.get(b.compress_hint)  # type: ignore[arg-type]
            if compressor is None:
                continue
            idx = working.index(b)
            working[idx] = compressor.compress(b)
            if total() <= budget:
                return self._sorted(working)

        # Phase 3 — truncate HIGH-priority blocks as a last resort.
        high_indices = [i for i, x in enumerate(working) if x.priority == Priority.HIGH]
        for idx in high_indices:
            other_tokens = sum(x.token_count for i, x in enumerate(working) if i != idx)
            tokens_for_block = budget - other_tokens
            working[idx] = self._truncate(working[idx], tokens_for_block)
            if total() <= budget:
                break

        # Remove blocks that were truncated to empty content
        working = [b for b in working if b.content]

        return self._sorted(working)

    def assemble_tracked(self, blocks: List[Block], budget: int) -> AssemblyResult:
        """Assemble blocks and return an AssemblyResult with tracking metadata."""
        assembly_id = uuid.uuid4().hex[:12]
        input_blocks = [copy.deepcopy(b) for b in blocks]
        result_blocks = self.assemble(blocks, budget)

        # Determine which blocks were dropped
        from ..storage.usage import block_hash
        included_hashes = {block_hash(b.content) for b in result_blocks}
        dropped = [b for b in input_blocks if block_hash(b.content) not in included_hashes]

        return AssemblyResult(
            blocks=result_blocks,
            assembly_id=assembly_id,
            budget=budget,
            input_blocks=input_blocks,
            dropped_blocks=dropped,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sorted(self, blocks: List[Block]) -> List[Block]:
        return sorted(blocks, key=lambda b: _PRIORITY_ORDER[b.priority])

    @staticmethod
    def _truncate(block: Block, token_limit: int) -> Block:
        """Return a copy of *block* whose content fits within *token_limit* tokens."""
        result = copy.copy(block)
        if token_limit <= 0:
            result.content = ""
            result.invalidate_token_count()
            return result

        content = block.content
        if TokenBudget.estimate(content) <= token_limit:
            return result  # Already fits; return shallow copy unchanged.

        # Binary search for the longest prefix that still fits.
        lo, hi = 0, len(content)
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if TokenBudget.estimate(content[:mid]) <= token_limit:
                lo = mid
            else:
                hi = mid

        result.content = content[:lo]
        result.invalidate_token_count()
        return result
