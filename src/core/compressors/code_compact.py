from __future__ import annotations

import copy
import re

from ..block import Block
from .base import BaseCompressor


_COMMENT_LINE = re.compile(r"^\s*(#|//|/\*|\*|<!--)")
_BLANK_LINE = re.compile(r"^\s*$")
_FUNC_PATTERN = re.compile(
    r"^(\s*)(def |async def |function |export function |export default function )"
    r"([^\n]+)"
)
_CLASS_PATTERN = re.compile(r"^(\s*)(class )([^\n]+)")
_DOCSTRING_OPEN = re.compile(r'^\s*("""|\'\'\'|/\*\*)')
_DOCSTRING_CLOSE = re.compile(r'("""|\'\'\'|\*/)\s*$')


class CodeCompactCompressor(BaseCompressor):
    """Compresses source code by stripping comments, blank lines, and collapsing bodies.

    Strategy:
    - Removes single-line comments and blank lines.
    - Keeps function/class signatures and their first docstring line.
    - Collapses function bodies to ``...`` placeholder.
    - Class bodies are recursively compacted (methods are preserved as signatures).
    No LLM required.
    """

    @property
    def name(self) -> str:
        return "code_compact"

    def compress(self, block: Block) -> Block:
        lines = block.content.splitlines()
        out = self._compact(lines)
        compressed = "\n".join(out) if out else block.content
        result = copy.copy(block)
        result.content = compressed
        result.invalidate_token_count()
        return result

    def _compact(self, lines: list[str]) -> list[str]:
        result: list[str] = []
        i = 0
        in_multiline_comment = False

        while i < len(lines):
            line = lines[i]

            # Skip multi-line comment blocks.
            if in_multiline_comment:
                if re.search(r"\*/", line):
                    in_multiline_comment = False
                i += 1
                continue
            if re.match(r"^\s*/\*", line) and not re.search(r"\*/", line):
                in_multiline_comment = True
                i += 1
                continue

            # Skip blank lines and single-line comments.
            if _BLANK_LINE.match(line) or _COMMENT_LINE.match(line):
                i += 1
                continue

            # Detect class definitions — keep signature+docstring, recurse into body.
            mc = _CLASS_PATTERN.match(line)
            if mc:
                indent = mc.group(1)
                result.append(line.rstrip())
                i += 1
                i = self._skip_docstring(lines, i, result)
                # Collect body lines and recursively compact them.
                body_indent = len(indent) + 1
                body_lines: list[str] = []
                while i < len(lines):
                    next_line = lines[i]
                    if _BLANK_LINE.match(next_line):
                        body_lines.append(next_line)
                        i += 1
                        continue
                    current_indent = len(next_line) - len(next_line.lstrip())
                    if current_indent < body_indent:
                        break
                    body_lines.append(next_line)
                    i += 1
                result.extend(self._compact(body_lines))
                continue

            # Detect function definitions — keep signature+docstring, collapse body.
            mf = _FUNC_PATTERN.match(line)
            if mf:
                indent = mf.group(1)
                result.append(line.rstrip())
                i += 1
                i = self._skip_docstring(lines, i, result)
                result.append(f"{indent}    ...")
                # Skip the body.
                body_indent = len(indent) + 1
                while i < len(lines):
                    next_line = lines[i]
                    if _BLANK_LINE.match(next_line):
                        i += 1
                        continue
                    current_indent = len(next_line) - len(next_line.lstrip())
                    if current_indent < body_indent:
                        break
                    i += 1
                continue

            result.append(line.rstrip())
            i += 1

        return result

    @staticmethod
    def _skip_docstring(lines: list[str], i: int, result: list[str]) -> int:
        if i < len(lines) and _DOCSTRING_OPEN.search(lines[i]):
            doc_line = lines[i].strip()
            if _DOCSTRING_CLOSE.search(doc_line) and len(doc_line) > 3:
                result.append(lines[i].rstrip())
                i += 1
            else:
                result.append(lines[i].rstrip())
                i += 1
                while i < len(lines):
                    if _DOCSTRING_CLOSE.search(lines[i]):
                        i += 1
                        break
                    i += 1
        return i
