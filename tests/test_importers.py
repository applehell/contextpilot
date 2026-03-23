"""Tests for src.importers — Claude and Copilot memory importers."""
from __future__ import annotations

from pathlib import Path

import pytest

from src.importers.claude import parse_claude_md, import_claude_file
from src.importers.copilot import parse_copilot_md, import_copilot_file


class TestClaudeImporter:
    def test_parse_sections(self) -> None:
        md = "## Sprache\nDeutsch bitte.\n\n## Tools\n- Read\n- Edit\n"
        memories = parse_claude_md(md)
        assert len(memories) == 2
        assert memories[0].key == "claude/sprache"
        assert "Deutsch" in memories[0].value
        assert memories[1].key == "claude/tools"
        assert "claude" in memories[0].tags
        assert "imported" in memories[0].tags

    def test_parse_preamble(self) -> None:
        md = "Top-level content before any heading.\n\n## Section\nBody."
        memories = parse_claude_md(md)
        assert len(memories) == 2
        assert memories[0].key == "claude/_preamble"
        assert "Top-level" in memories[0].value

    def test_empty_sections_skipped(self) -> None:
        md = "## Empty\n\n## HasContent\nSome text."
        memories = parse_claude_md(md)
        assert len(memories) == 1
        assert memories[0].key == "claude/hascontent"

    def test_empty_input(self) -> None:
        assert parse_claude_md("") == []

    def test_metadata_source(self) -> None:
        md = "## Test\nContent."
        memories = parse_claude_md(md, source_path="/home/user/.claude/CLAUDE.md")
        assert memories[0].metadata["source"] == "/home/user/.claude/CLAUDE.md"
        assert memories[0].metadata["heading"] == "Test"

    def test_import_file(self, tmp_path: Path) -> None:
        f = tmp_path / "CLAUDE.md"
        f.write_text("## A\nContent A.\n## B\nContent B.", encoding="utf-8")
        memories = import_claude_file(f)
        assert len(memories) == 2
        assert memories[0].key == "claude/a"
        assert memories[1].key == "claude/b"

    def test_slug_special_chars(self) -> None:
        md = "## Sprache & Kommunikation\nDetails here."
        memories = parse_claude_md(md)
        assert memories[0].key == "claude/sprache-kommunikation"


class TestCopilotImporter:
    def test_parse_sections(self) -> None:
        md = "## Code Style\nUse 4 spaces.\n\n## Testing\nPytest preferred.\n"
        memories = parse_copilot_md(md)
        assert len(memories) == 2
        assert memories[0].key == "copilot/code-style"
        assert "copilot" in memories[0].tags

    def test_parse_preamble(self) -> None:
        md = "General instructions.\n\n## Details\nMore info."
        memories = parse_copilot_md(md)
        assert len(memories) == 2
        assert memories[0].key == "copilot/_preamble"

    def test_empty_sections_skipped(self) -> None:
        md = "## Empty\n\n## Real\nStuff here."
        memories = parse_copilot_md(md)
        assert len(memories) == 1

    def test_empty_input(self) -> None:
        assert parse_copilot_md("") == []

    def test_import_file(self, tmp_path: Path) -> None:
        f = tmp_path / "copilot-instructions.md"
        f.write_text("## Style\nClean code.\n## Deps\nnumpy only.", encoding="utf-8")
        memories = import_copilot_file(f)
        assert len(memories) == 2
        assert memories[0].key == "copilot/style"
        assert memories[1].key == "copilot/deps"

    def test_metadata_source(self) -> None:
        md = "## Test\nContent."
        memories = parse_copilot_md(md, source_path=".github/copilot-instructions.md")
        assert memories[0].metadata["source"] == ".github/copilot-instructions.md"
