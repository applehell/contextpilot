"""Tests for the Obsidian vault connector."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from src.connectors.obsidian import ObsidianConnector, _parse_frontmatter, _parse_csv
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


@pytest.fixture
def vault(tmp_path):
    notes = tmp_path / "notes"
    notes.mkdir()
    (notes / "hello.md").write_text("---\ntitle: Hello\ntags: [python, test]\n---\nHello World content")
    (notes / "plain.md").write_text("Just a plain note without frontmatter")
    (notes / "empty.md").write_text("---\ntitle: Empty\n---\n")
    (notes / ".hidden.md").write_text("This is hidden")
    sub = notes / "projects"
    sub.mkdir()
    (sub / "alpha.md").write_text("---\ntitle: Alpha Project\ntags: work\n---\nAlpha project details")
    return notes


@pytest.fixture
def connector(tmp_path, vault):
    c = ObsidianConnector(data_dir=tmp_path)
    c.configure({"vault_path": str(vault)})
    return c


class TestParseFrontmatter:
    def test_no_frontmatter(self):
        fm, content = _parse_frontmatter("Just text")
        assert fm == {}
        assert content == "Just text"

    def test_with_frontmatter(self):
        text = "---\ntitle: Test\ntags: [a, b]\n---\nBody content"
        fm, content = _parse_frontmatter(text)
        assert fm["title"] == "Test"
        assert fm["tags"] == ["a", "b"]
        assert content == "Body content"

    def test_no_closing_delim(self):
        text = "---\ntitle: Test\nNo closing"
        fm, content = _parse_frontmatter(text)
        assert fm == {}
        assert content == text


class TestParseCsv:
    def test_string(self):
        assert _parse_csv("a, b, c") == ["a", "b", "c"]

    def test_list(self):
        assert _parse_csv(["a", "b"]) == ["a", "b"]

    def test_empty(self):
        assert _parse_csv("") == []
        assert _parse_csv(None) == []


class TestObsidianConnector:
    def test_not_configured_initially(self, tmp_path):
        c = ObsidianConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured_with_vault(self, connector):
        assert connector.configured

    def test_config_schema(self, connector):
        schema = connector.config_schema()
        assert len(schema) >= 1
        assert schema[0].name == "vault_path"

    def test_test_connection_no_path(self, tmp_path):
        c = ObsidianConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    def test_test_connection_bad_path(self, tmp_path):
        c = ObsidianConnector(data_dir=tmp_path)
        c._config["vault_path"] = "/nonexistent/path"
        result = c.test_connection()
        assert result["ok"] is False

    def test_test_connection_ok(self, connector):
        result = connector.test_connection()
        assert result["ok"] is True
        assert result["file_count"] >= 2

    def test_sync(self, connector, store):
        result = connector.sync(store)
        assert result.added >= 2  # hello.md and alpha.md (empty skipped, hidden skipped)
        assert result.errors == []

    def test_sync_skips_empty(self, connector, store):
        result = connector.sync(store)
        assert result.skipped >= 1  # empty.md has no content after frontmatter

    def test_sync_skips_hidden(self, connector, store, vault):
        result = connector.sync(store)
        hidden_keys = [m.key for m in store.list() if ".hidden" in m.key]
        assert len(hidden_keys) == 0

    def test_sync_updates(self, connector, store, vault):
        connector.sync(store)
        (vault / "hello.md").write_text("---\ntitle: Hello Updated\ntags: [python]\n---\nUpdated content")
        result = connector.sync(store)
        assert result.updated >= 1

    def test_sync_removes_deleted(self, connector, store, vault):
        connector.sync(store)
        (vault / "plain.md").unlink()
        result = connector.sync(store)
        assert result.removed >= 1

    def test_sync_not_configured(self, tmp_path, store):
        c = ObsidianConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["Not configured"]

    def test_sync_folder_filter(self, tmp_path, vault, store):
        c = ObsidianConnector(data_dir=tmp_path)
        c.configure({"vault_path": str(vault), "folder_filter": "projects"})
        result = c.sync(store)
        assert result.added >= 1
        keys = [m.key for m in store.list()]
        assert any("alpha" in k for k in keys)

    def test_sync_tag_filter(self, tmp_path, vault, store):
        c = ObsidianConnector(data_dir=tmp_path)
        c.configure({"vault_path": str(vault), "tag_filter": "work"})
        result = c.sync(store)
        assert result.added >= 1

    def test_sync_large_file_skipped(self, connector, store, vault):
        large = vault / "large.md"
        large.write_text("x" * (3 * 1024 * 1024))
        result = connector.sync(store)
        assert result.skipped >= 1

    def test_sync_string_tags(self, connector, store, vault):
        (vault / "strtags.md").write_text("---\ntitle: StrTag\ntags: alpha, beta\n---\nContent with string tags")
        result = connector.sync(store)
        mem = store.get("obsidian/strtags.md")
        assert "alpha" in mem.tags or "beta" in mem.tags
