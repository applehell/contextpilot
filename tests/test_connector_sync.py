"""Tests for connector sync() methods with mocked HTTP/filesystem responses."""
from __future__ import annotations

import hashlib
import json
import textwrap
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.connectors.base import SyncResult
from src.connectors.registry import ConnectorRegistry
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    return MemoryStore(db)


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    return ConnectorRegistry(data_dir=tmp_path)


# ═══════════════════════════════════════════════════════════════
# RSS Connector
# ═══════════════════════════════════════════════════════════════

SAMPLE_RSS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Article One</title>
          <link>https://example.com/1</link>
          <guid>guid-1</guid>
          <description>First article content</description>
          <pubDate>Mon, 01 Jan 2025 12:00:00 GMT</pubDate>
        </item>
        <item>
          <title>Article Two</title>
          <link>https://example.com/2</link>
          <guid>guid-2</guid>
          <description>Second article content</description>
          <pubDate>Tue, 02 Jan 2025 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
""")

EMPTY_RSS_XML = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Empty Feed</title>
      </channel>
    </rss>
""")


class TestRSSSync:
    def _get_connector(self, registry):
        c = registry.get("rss")
        assert c is not None
        return c

    def test_rss_sync_adds_items(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"feed_urls": "https://example.com/feed.xml"})

        mock_resp = MagicMock()
        mock_resp.text = SAMPLE_RSS_XML
        mock_resp.raise_for_status = MagicMock()

        with patch("src.connectors.rss.requests.get", return_value=mock_resp):
            result = c.sync(store)

        assert result.added == 2
        assert result.total_remote == 2
        assert result.errors == []

        memories = store.list()
        assert len(memories) == 2
        values = [m.value for m in memories]
        assert any("Article One" in v for v in values)
        assert any("Article Two" in v for v in values)

    def test_rss_sync_empty_feed(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"feed_urls": "https://example.com/feed.xml"})

        mock_resp = MagicMock()
        mock_resp.text = EMPTY_RSS_XML
        mock_resp.raise_for_status = MagicMock()

        with patch("src.connectors.rss.requests.get", return_value=mock_resp):
            result = c.sync(store)

        assert result.added == 0
        assert result.total_remote == 0
        assert len(store.list()) == 0

    def test_rss_sync_not_configured(self, registry, store):
        c = self._get_connector(registry)
        result = c.sync(store)
        assert len(result.errors) > 0
        assert "No feed URLs configured" in result.errors[0]


# ═══════════════════════════════════════════════════════════════
# Bookmarks Connector
# ═══════════════════════════════════════════════════════════════

class TestBookmarksSync:
    def _get_connector(self, registry):
        c = registry.get("bookmarks")
        assert c is not None
        return c

    def test_bookmarks_sync_fetches_urls(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"urls": "https://example.com/page1"})

        html = "<html><head><title>Test Page</title></head><body><p>Hello world</p></body></html>"

        import io
        mock_resp = MagicMock()
        mock_resp.read.return_value = html.encode()
        mock_resp.headers = {"Content-Type": "text/html"}
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("src.connectors.bookmarks.urllib.request.urlopen", return_value=mock_resp):
            result = c.sync(store)

        assert result.added == 1
        assert result.total_remote == 1
        memories = store.list()
        assert len(memories) == 1
        assert "Hello world" in memories[0].value

    def test_bookmarks_sync_error_handling(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"urls": "https://example.com/missing"})

        import urllib.error
        with patch("src.connectors.bookmarks.urllib.request.urlopen",
                   side_effect=urllib.error.HTTPError("https://example.com/missing", 404, "Not Found", {}, None)):
            result = c.sync(store)

        assert result.added == 0
        assert len(result.errors) == 1
        assert "404" in result.errors[0]


# ═══════════════════════════════════════════════════════════════
# GitHub Connector
# ═══════════════════════════════════════════════════════════════

MOCK_GH_REPO = {
    "full_name": "owner/testrepo",
    "description": "A test repo",
    "language": "Python",
    "stargazers_count": 42,
    "forks_count": 5,
    "open_issues_count": 3,
    "default_branch": "main",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:00Z",
    "pushed_at": "2025-01-01T00:00:00Z",
    "html_url": "https://github.com/owner/testrepo",
    "topics": ["python", "testing"],
    "license": {"spdx_id": "MIT"},
    "homepage": "",
}


class TestGitHubSync:
    def _get_connector(self, registry):
        c = registry.get("github")
        assert c is not None
        return c

    def test_github_sync_repos(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"repos": "owner/testrepo", "token": "ghp_fake123",
                      "sync_items": "repos"})

        mock_api = MagicMock()
        mock_api.repo.return_value = MOCK_GH_REPO
        mock_api.readme.return_value = None
        mock_api.releases.return_value = []
        mock_api.issues.return_value = []

        with patch.object(c, "_api", return_value=mock_api):
            result = c.sync(store)

        assert result.added == 1
        assert result.total_remote == 1
        memories = store.list()
        assert len(memories) == 1
        assert "owner/testrepo" in memories[0].value
        assert "Python" in memories[0].value

    def test_github_not_configured(self, registry, store):
        c = self._get_connector(registry)
        result = c.sync(store)
        assert len(result.errors) > 0
        assert "Not configured" in result.errors[0]


# ═══════════════════════════════════════════════════════════════
# Gitea Connector
# ═══════════════════════════════════════════════════════════════

MOCK_GITEA_REPOS = [
    {
        "name": "myrepo",
        "full_name": "user/myrepo",
        "owner": {"login": "user"},
        "description": "My Gitea repo",
        "language": "Go",
        "stars_count": 10,
        "forks_count": 2,
        "size": 1024,
        "default_branch": "main",
        "created_at": "2024-06-01T00:00:00Z",
        "updated_at": "2025-03-01T00:00:00Z",
        "topics": [],
        "has_wiki": False,
        "has_packages": False,
        "clone_url": "http://gitea:3300/user/myrepo.git",
    }
]


class TestGiteaSync:
    def _get_connector(self, registry):
        c = registry.get("gitea")
        assert c is not None
        return c

    def test_gitea_sync_repos(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"url": "http://gitea:3300", "token": "fake-token",
                      "sync_items": "repos"})

        mock_api = MagicMock()
        mock_api.repos.return_value = MOCK_GITEA_REPOS
        mock_api.readme.return_value = None
        mock_api.issues.return_value = []
        mock_api.releases.return_value = []
        mock_api.wiki_pages.return_value = []
        mock_api.packages.return_value = []

        with patch.object(c, "_api", return_value=mock_api):
            result = c.sync(store)

        assert result.added == 1
        assert result.total_remote == 1
        memories = store.list()
        assert len(memories) == 1
        assert "user/myrepo" in memories[0].value


# ═══════════════════════════════════════════════════════════════
# Home Assistant Connector
# ═══════════════════════════════════════════════════════════════

MOCK_HA_STATES = [
    {
        "entity_id": "automation.morning_lights",
        "state": "on",
        "attributes": {
            "friendly_name": "Morning Lights",
            "last_triggered": "2025-03-15T07:00:00Z",
        },
    },
    {
        "entity_id": "scene.movie_night",
        "state": "scening",
        "attributes": {
            "friendly_name": "Movie Night",
        },
    },
    {
        "entity_id": "script.restart_server",
        "state": "off",
        "attributes": {
            "friendly_name": "Restart Server",
        },
    },
]


class TestHomeAssistantSync:
    def _get_connector(self, registry):
        c = registry.get("homeassistant")
        assert c is not None
        return c

    def test_ha_sync_entities(self, registry, store):
        c = self._get_connector(registry)
        c.configure({"url": "http://ha:8123", "token": "eyJfake",
                      "sync_types": "automations, scenes, scripts"})

        mock_api = MagicMock()
        mock_api.automations.return_value = [s for s in MOCK_HA_STATES if s["entity_id"].startswith("automation.")]
        mock_api.scenes.return_value = [s for s in MOCK_HA_STATES if s["entity_id"].startswith("scene.")]
        mock_api.scripts.return_value = [s for s in MOCK_HA_STATES if s["entity_id"].startswith("script.")]

        with patch.object(c, "_api", return_value=mock_api):
            result = c.sync(store)

        assert result.added == 3
        assert result.total_remote == 3
        assert result.errors == []

        keys = [m.key for m in store.list()]
        assert "homeassistant/automation.morning_lights" in keys
        assert "homeassistant/scene.movie_night" in keys
        assert "homeassistant/script.restart_server" in keys

        auto_mem = store.get("homeassistant/automation.morning_lights")
        assert "Morning Lights" in auto_mem.value


# ═══════════════════════════════════════════════════════════════
# Dockge Connector
# ═══════════════════════════════════════════════════════════════

SAMPLE_COMPOSE = """\
services:
  web:
    image: nginx:latest
    ports:
      - "8080:80"
    environment:
      SECRET_KEY: supersecret
      DEBUG: "true"
    restart: always
"""


class TestDockgeSync:
    def _get_connector(self, registry):
        c = registry.get("dockge")
        assert c is not None
        return c

    def test_dockge_sync_stacks(self, registry, store, tmp_path):
        stacks_dir = tmp_path / "stacks"
        stack1 = stacks_dir / "myapp"
        stack1.mkdir(parents=True)
        (stack1 / "compose.yml").write_text(SAMPLE_COMPOSE)

        c = self._get_connector(registry)
        c.configure({"stacks_dir": str(stacks_dir)})

        result = c.sync(store)

        assert result.added == 1
        assert result.total_remote == 1
        assert result.errors == []

        memories = store.list()
        assert len(memories) == 1
        mem = memories[0]
        assert "myapp" in mem.key
        assert "nginx:latest" in mem.value
        # env values should be redacted by default (include_env=False)
        assert "supersecret" not in mem.value
        assert "***" in mem.value


# ═══════════════════════════════════════════════════════════════
# Obsidian Connector
# ═══════════════════════════════════════════════════════════════

class TestObsidianSync:
    def _get_connector(self, registry):
        c = registry.get("obsidian")
        assert c is not None
        return c

    def test_obsidian_sync_notes(self, registry, store, tmp_path):
        vault = tmp_path / "vault"
        vault.mkdir()

        note1 = vault / "hello.md"
        note1.write_text(textwrap.dedent("""\
            ---
            title: Hello World
            tags: [greeting, test]
            ---
            This is a test note with frontmatter.
        """))

        note2 = vault / "plain.md"
        note2.write_text("Just a plain note without frontmatter.\n")

        c = self._get_connector(registry)
        c.configure({"vault_path": str(vault)})

        result = c.sync(store)

        assert result.added == 2
        assert result.total_remote == 2
        assert result.errors == []

        keys = sorted([m.key for m in store.list()])
        assert "obsidian/hello.md" in keys
        assert "obsidian/plain.md" in keys

        hello_mem = store.get("obsidian/hello.md")
        assert "Hello World" in hello_mem.value
        assert "greeting" in hello_mem.tags
        assert "test" in hello_mem.tags
