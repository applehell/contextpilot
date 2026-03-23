from __future__ import annotations
import tiktoken


_DEFAULT_ENCODING = "cl100k_base"


class TokenBudget:
    def __init__(self, total: int, encoding_name: str = _DEFAULT_ENCODING) -> None:
        self.total = total
        self._encoding = tiktoken.get_encoding(encoding_name)
        self._used = 0

    @classmethod
    def estimate(cls, text: str, encoding_name: str = _DEFAULT_ENCODING) -> int:
        enc = tiktoken.get_encoding(encoding_name)
        return len(enc.encode(text))

    @property
    def used(self) -> int:
        return self._used

    @property
    def available(self) -> int:
        return max(0, self.total - self._used)

    @property
    def is_exhausted(self) -> bool:
        return self._used >= self.total

    def consume(self, tokens: int) -> bool:
        if tokens > self.available:
            return False
        self._used += tokens
        return True

    def release(self, tokens: int) -> None:
        self._used = max(0, self._used - tokens)

    def reset(self) -> None:
        self._used = 0

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text))
