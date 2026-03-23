from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .token_budget import TokenBudget


class Priority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Block:
    content: str
    priority: Priority = Priority.MEDIUM
    compress_hint: Optional[str] = None
    _token_count: Optional[int] = field(default=None, repr=False, compare=False)

    @property
    def token_count(self) -> int:
        if self._token_count is None:
            from .token_budget import TokenBudget
            self._token_count = TokenBudget.estimate(self.content)
        return self._token_count

    def invalidate_token_count(self) -> None:
        self._token_count = None
