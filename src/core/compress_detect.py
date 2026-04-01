"""Shared compress-hint detection for memory content."""
from __future__ import annotations

import re
from typing import Optional

_CODE_INDICATORS = re.compile(
    r"(```|def |class |function |import |from |curl |export |const |let |var )"
)
_STEP_INDICATORS = re.compile(
    r"^(\d+[.)]\s|[-*]\s|#{1,3}\s)", re.MULTILINE
)
_KV_INDICATORS = re.compile(
    r"^[A-Za-z][^:=\n]{0,40}(?::[ \t]|[ \t]*=[ \t])", re.MULTILINE
)


def detect_compress_hint(text: str) -> Optional[str]:
    """Auto-detect the best compressor for a memory's content."""
    code_matches = len(_CODE_INDICATORS.findall(text))
    step_matches = len(_STEP_INDICATORS.findall(text))
    kv_matches = len(_KV_INDICATORS.findall(text))

    if code_matches >= 3:
        return "code_compact"
    if step_matches >= 3:
        return "mermaid"
    if kv_matches >= 3:
        return "yaml_struct"
    if len(text) > 200:
        return "bullet_extract"
    return None
