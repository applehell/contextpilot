from __future__ import annotations

import copy
import re

from ..block import Block
from .base import BaseCompressor


_SEPARATOR_RE = re.compile(r"^[\s|:+-]+$")
_PIPE_ROW_RE = re.compile(r"^\|(.+)\|$")


class TableCompressor(BaseCompressor):
    """Compresses tabular data (Markdown/CSV/TSV) into compact key-value rows.

    Strategy:
    - Detects Markdown pipe tables, TSV, and CSV formats.
    - Removes separator rows and redundant whitespace.
    - If all values in a column are identical, drops that column.
    - Rewrites remaining data as compact ``header: value`` lines per row.
    No LLM required.
    """

    @property
    def name(self) -> str:
        return "table"

    def compress(self, block: Block) -> Block:
        lines = block.content.strip().splitlines()
        if not lines:
            return copy.copy(block)

        rows = self._parse_rows(lines)
        if len(rows) < 2:
            return copy.copy(block)

        headers = rows[0]
        data = rows[1:]

        # Drop columns where every data cell is identical.
        keep = []
        for col_idx in range(len(headers)):
            col_vals = {r[col_idx] for r in data if col_idx < len(r)}
            if len(col_vals) > 1 or not col_vals:
                keep.append(col_idx)
            elif len(data) <= 1:
                keep.append(col_idx)

        if not keep:
            keep = list(range(len(headers)))

        out: list[str] = []
        for row in data:
            parts = []
            for ci in keep:
                h = headers[ci] if ci < len(headers) else f"col{ci}"
                v = row[ci] if ci < len(row) else ""
                if v:
                    parts.append(f"{h}: {v}")
            if parts:
                out.append(" | ".join(parts))

        compressed = "\n".join(out) if out else block.content
        result = copy.copy(block)
        result.content = compressed
        result.invalidate_token_count()
        return result

    def _parse_rows(self, lines: list[str]) -> list[list[str]]:
        rows: list[list[str]] = []
        fmt = self._detect_format(lines)

        for line in lines:
            stripped = line.strip()
            if not stripped or _SEPARATOR_RE.match(stripped):
                continue
            if fmt == "pipe":
                m = _PIPE_ROW_RE.match(stripped)
                if m:
                    cells = [c.strip() for c in m.group(1).split("|")]
                else:
                    cells = [c.strip() for c in stripped.split("|") if c.strip()]
            elif fmt == "tsv":
                cells = [c.strip() for c in stripped.split("\t")]
            else:
                cells = [c.strip() for c in stripped.split(",")]
            if cells:
                rows.append(cells)
        return rows

    def _detect_format(self, lines: list[str]) -> str:
        for line in lines:
            if "|" in line:
                return "pipe"
            if "\t" in line:
                return "tsv"
        return "csv"
