#!/usr/bin/env python3
"""Generate Context Pilot-backed skill stubs for all imported skills.

Creates stub .md files that instruct Claude to fetch knowledge from
Context Pilot via MCP instead of hardcoding it in the skill file.

Usage:
    python scripts/generate_skill_stubs.py                    # preview
    python scripts/generate_skill_stubs.py --write             # write stubs
    python scripts/generate_skill_stubs.py --write --backup    # backup originals first
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.storage.db import Database
from src.storage.memory import MemoryStore
from src.core.skill_registry import _DB_PATH

SKILLS_DIR = Path.home() / ".claude" / "skills"

STUB_TEMPLATE = """---
name: {name}
description: >
  {description}
  Knowledge is managed by Context Pilot — fetched live via MCP.
version: 2.0.0
---

# {title} Skill (Context Pilot)

This skill's knowledge is stored in **Context Pilot**.
Before answering questions about {name}, fetch the current knowledge:

## Step 1: Get skill context
```
Use MCP tool: mcp__context-pilot__get_skill_context
  skill_name: "{name}"
  token_budget: 4000
```

## Step 2: Search specific topics
```
Use MCP tool: mcp__context-pilot__memory_search
  query: "<your specific question>"
  tags: ["{name}"]
```

## Step 3: Read full skill knowledge
```
Use MCP tool: mcp__context-pilot__memory_get
  key: "skill/{name}"
```

## Available memory keys
{memory_keys}

## Important
- Always fetch from Context Pilot before answering — the data may have been updated
- Use `memory_set` to store new learnings back into Context Pilot
- Send `heartbeat("{name}")` to keep the connection alive
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Write stub files")
    parser.add_argument("--backup", action="store_true", help="Backup originals before writing")
    args = parser.parse_args()

    db = Database(_DB_PATH)
    store = MemoryStore(db)
    memories = store.list()
    db.close()

    # Group memories by skill
    by_skill: dict = {}
    for m in memories:
        if not m.key.startswith("skill/"):
            continue
        parts = m.key.split("/")
        if len(parts) < 2:
            continue
        skill_name = parts[1]
        by_skill.setdefault(skill_name, []).append(m)

    print(f"Found {len(by_skill)} skills with memories\n")

    for skill_name, mems in sorted(by_skill.items()):
        skill_dir = SKILLS_DIR / skill_name
        md_file = skill_dir / f"{skill_name}.md"

        if not md_file.exists():
            print(f"  SKIP {skill_name}: {md_file} not found")
            continue

        # Extract description from frontmatter
        text = md_file.read_text(encoding="utf-8")
        description = ""
        for line in text.splitlines():
            if line.strip().startswith("description:"):
                description = line.split(":", 1)[1].strip().strip(">").strip()
                break

        # Build memory keys list
        key_lines = []
        for m in sorted(mems, key=lambda x: x.key):
            tags = ", ".join(m.tags) if m.tags else ""
            key_lines.append(f"- `{m.key}` ({tags})")

        stub = STUB_TEMPLATE.format(
            name=skill_name,
            title=skill_name.capitalize(),
            description=description or f"{skill_name} skill",
            memory_keys="\n".join(key_lines),
        )

        if args.write:
            if args.backup:
                backup = md_file.with_suffix(".md.bak")
                if not backup.exists():
                    shutil.copy2(md_file, backup)
                    print(f"  BACKUP {md_file} → {backup}")

            md_file.write_text(stub, encoding="utf-8")
            print(f"  WROTE {md_file} ({len(mems)} memory keys)")
        else:
            print(f"  {skill_name}: {len(mems)} memories, would write to {md_file}")
            print(f"    Keys: {', '.join(m.key for m in mems[:3])}...")

    if not args.write:
        print("\nDry run — use --write to actually write stubs (--backup to keep originals)")


if __name__ == "__main__":
    main()
