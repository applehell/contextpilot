from __future__ import annotations

import copy
import re

from ..block import Block
from .base import BaseCompressor


_STEP_PATTERN = re.compile(r"^(?:\d+[.)]\s*|[-*•]\s*)(.+)$")
_CONNECTOR_WORDS = re.compile(
    r"\b(then|next|after|subsequently|finally|first|second|third|"
    r"afterwards|following|and then|once|when)\b",
    re.IGNORECASE,
)
_MAX_LABEL_LEN = 20


class MermaidCompressor(BaseCompressor):
    """Converts sequential descriptions or numbered steps into a Mermaid flowchart.

    Detects numbered lists, bullet lists, and connector words to infer
    step sequences.  Falls back to treating each non-empty line as a step.
    No LLM required.
    """

    @property
    def name(self) -> str:
        return "mermaid"

    def compress(self, block: Block) -> Block:
        steps = self._extract_steps(block.content)

        if len(steps) < 2:
            # Not enough structure to build a diagram; return unchanged.
            return copy.copy(block)

        lines = ["flowchart TD"]
        prev_id: str | None = None
        for i, step in enumerate(steps):
            node_id = f"N{i}"
            label = step[:_MAX_LABEL_LEN].replace('"', "'")
            lines.append(f'    {node_id}["{label}"]')
            if prev_id is not None:
                lines.append(f"    {prev_id} --> {node_id}")
            prev_id = node_id

        result = copy.copy(block)
        result.content = "\n".join(lines)
        result.invalidate_token_count()
        return result

    # ------------------------------------------------------------------

    def _extract_steps(self, text: str) -> list[str]:
        lines = text.splitlines()
        steps: list[str] = []

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            m = _STEP_PATTERN.match(line)
            if m:
                steps.append(m.group(1).strip())
                continue

            # Split on connector words to get implicit steps from prose
            parts = _CONNECTOR_WORDS.split(line)
            for part in parts:
                part = part.strip()
                if part and not _CONNECTOR_WORDS.fullmatch(part):
                    steps.append(part)

        return [s for s in steps if s]
