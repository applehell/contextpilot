from __future__ import annotations

import copy
import hashlib
from typing import List

from ..block import Block
from .base import BaseCompressor


class DedupCrossCompressor(BaseCompressor):
    """Cross-block deduplication: removes duplicate paragraphs across blocks.

    This compressor is stateful. Call ``compress`` on each block in sequence;
    it tracks paragraph hashes across calls and removes paragraphs that have
    already been seen in a prior block.

    Call ``reset`` between independent assemblies to clear the seen set.
    No LLM required.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    @property
    def name(self) -> str:
        return "dedup_cross"

    def reset(self) -> None:
        self._seen.clear()

    def compress(self, block: Block) -> Block:
        paragraphs = self._split_paragraphs(block.content)
        kept: list[str] = []

        for para in paragraphs:
            h = self._hash(para)
            if h in self._seen:
                continue
            self._seen.add(h)
            kept.append(para)

        compressed = "\n\n".join(kept) if kept else ""
        result = copy.copy(block)
        result.content = compressed
        result.invalidate_token_count()
        return result

    def compress_blocks(self, blocks: List[Block]) -> List[Block]:
        """Convenience: deduplicate across a list of blocks in one call."""
        self.reset()
        return [self.compress(b) for b in blocks]

    @staticmethod
    def _split_paragraphs(text: str) -> list[str]:
        raw = text.split("\n\n")
        return [p.strip() for p in raw if p.strip()]

    @staticmethod
    def _hash(text: str) -> str:
        normalised = " ".join(text.split()).lower()
        return hashlib.md5(normalised.encode()).hexdigest()
