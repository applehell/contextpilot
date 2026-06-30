from __future__ import annotations
import tiktoken


_DEFAULT_ENCODING = "cl100k_base"
_ENCODING_CACHE: dict = {}


class TokenBudget:
    @classmethod
    def estimate(cls, text: str, encoding_name: str = _DEFAULT_ENCODING) -> int:
        if encoding_name not in _ENCODING_CACHE:
            _ENCODING_CACHE[encoding_name] = tiktoken.get_encoding(encoding_name)
        return len(_ENCODING_CACHE[encoding_name].encode(text))
