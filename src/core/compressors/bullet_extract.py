from __future__ import annotations

import copy
import re

from ..block import Block
from .base import BaseCompressor


class BulletExtractCompressor(BaseCompressor):
    """Converts prose text to bullet points by extracting sentences.

    Each sentence becomes a bullet.  No LLM required — pure rule-based.
    Reduces token count by stripping transitional filler between sentences.
    """

    @property
    def name(self) -> str:
        return "bullet_extract"

    _MAX_WORDS_PER_BULLET = 12

    def compress(self, block: Block) -> Block:
        text = block.content.strip()
        sentences = re.split(r"(?<=[.!?])\s+", text)
        bullets = []
        for s in sentences:
            s = s.strip().rstrip(".")
            if not s:
                continue
            words = s.split()
            if len(words) > self._MAX_WORDS_PER_BULLET:
                s = " ".join(words[: self._MAX_WORDS_PER_BULLET]) + "…"
            bullets.append(f"- {s}")

        compressed = "\n".join(bullets) if bullets else text
        result = copy.copy(block)
        result.content = compressed
        result.invalidate_token_count()
        return result
