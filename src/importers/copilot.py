"""Import GitHub Copilot copilot-instructions.md files into Context Pilot."""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import List

from src.storage.memory import Memory


def parse_copilot_md(text: str, source_path: str = "copilot-instructions.md") -> List[Memory]:
    """Parse a copilot-instructions.md file into Memory objects.

    Splits on ## headings. Each section becomes one Memory with:
    - key: slugified heading prefixed with 'copilot/'
    - value: section content
    - tags: ['copilot', 'imported']
    - metadata: {'source': source_path, 'heading': original heading}

    Content before the first heading is stored as 'copilot/_preamble'.
    """
    lines = text.split("\n")
    sections: List[tuple] = []
    current_heading = None
    current_lines: List[str] = []

    for line in lines:
        match = re.match(r"^##\s+(.+)$", line)
        if match:
            if current_heading is not None or current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading is not None or current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    now = time.time()
    memories: List[Memory] = []
    for heading, body in sections:
        if not body:
            continue
        if heading is None:
            key = "copilot/_preamble"
            heading_str = "(preamble)"
        else:
            slug = _slugify(heading)
            key = f"copilot/{slug}"
            heading_str = heading
        memories.append(Memory(
            key=key,
            value=body,
            tags=["copilot", "imported"],
            metadata={"source": source_path, "heading": heading_str},
            created_at=now,
            updated_at=now,
        ))
    return memories


def import_copilot_file(path: Path) -> List[Memory]:
    """Read a copilot-instructions.md file from disk and parse it into Memory objects."""
    text = path.read_text(encoding="utf-8")
    return parse_copilot_md(text, source_path=str(path))


def _slugify(text: str) -> str:
    """Convert heading text to a URL-safe slug."""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    return s.strip("-")
