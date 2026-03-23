from __future__ import annotations
from abc import ABC, abstractmethod

from ..block import Block


class BaseCompressor(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier used in compress_hint and the assembler registry."""
        ...

    @abstractmethod
    def compress(self, block: Block) -> Block:
        """Return a new Block with reduced content. Must not mutate the input."""
        ...
