from __future__ import annotations
from typing import List
from .block import Block


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

    def __len__(self) -> int:
        return len(self._blocks)

    def __iter__(self):
        return iter(self._blocks)
