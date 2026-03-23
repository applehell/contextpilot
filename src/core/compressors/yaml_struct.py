from __future__ import annotations

import copy
import re

from ..block import Block
from .base import BaseCompressor


_KV_PATTERN = re.compile(r"^([A-Za-z][^:=\n]{0,40})(?::[ \t]*|[ \t]*=[ \t]*)(.+)$")
_STRIP_FILLER = re.compile(
    r"\b(the|a|an|is|are|was|were|has|have|had|this|that|these|those|it|its)\b",
    re.IGNORECASE,
)


class YamlStructCompressor(BaseCompressor):
    """Converts structured text into compact YAML-like key-value notation.

    Detects ``Key: Value`` / ``Key = Value`` lines and rewrites them as YAML.
    Prose-only lines are kept as comments (prefixed with ``#``).
    Empty lines are dropped.  No LLM required.
    """

    @property
    def name(self) -> str:
        return "yaml_struct"

    def compress(self, block: Block) -> Block:
        lines = block.content.splitlines()
        yaml_lines: list[str] = []

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            m = _KV_PATTERN.match(line)
            if m:
                key_raw = m.group(1).strip()
                value = m.group(2).strip()
                key = re.sub(r"\s+", "_", key_raw.lower())
                key = re.sub(r"[^\w]", "", key)
                yaml_lines.append(f"{key}: {value}")
            else:
                # Keep short prose lines as compact comments
                short = _STRIP_FILLER.sub("", line).strip()
                short = re.sub(r"\s{2,}", " ", short)
                if short:
                    yaml_lines.append(f"# {short}")

        compressed = "\n".join(yaml_lines) if yaml_lines else block.content
        result = copy.copy(block)
        result.content = compressed
        result.invalidate_token_count()
        return result
