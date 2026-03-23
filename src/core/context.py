from __future__ import annotations
from typing import List, Optional
from .block import Block, Priority


class Context:
    def __init__(self) -> None:
        self._blocks: List[Block] = []

    def add(self, block: Block) -> None:
        self._blocks.append(block)

    def remove(self, block: Block) -> None:
        self._blocks.remove(block)

    def clear(self) -> None:
        self._blocks.clear()

    @property
    def blocks(self) -> List[Block]:
        return list(self._blocks)

    @property
    def total_tokens(self) -> int:
        return sum(b.token_count for b in self._blocks)

    def blocks_by_priority(self) -> List[Block]:
        order = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
        return sorted(self._blocks, key=lambda b: order[b.priority])

    def __len__(self) -> int:
        return len(self._blocks)

    def __iter__(self):
        return iter(self._blocks)
