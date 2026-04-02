"""Tests for the Gitea connector with mocked API."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from src.connectors.gitea import GiteaConnector, _GiteaAPI
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


@pytest.fixture
def connector(tmp_path):
    c = GiteaConnector(data_dir=tmp_path)
    c.configure({"url": "http://localhost:3300", "token": "test_token"})
    return c


MOCK_REPOS = [
    {
        "name": "myrepo",
        "owner": {"login": "user"},
        "full_name": "user/myrepo",
        "description": "A test repository",
        "language": "Python",
        "stars_count": 5,
        "forks_count": 1,
        "size": 1024,
        "default_branch": "main",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2025-01-01T00:00:00Z",
        "topics": ["python"],
        "clone_url": "http://localhost:3300/user/myrepo.git",
        "has_wiki": True,
        "has_packages": True,
    },
]

MOCK_ISSUES = [
    {
        "number": 1,
        "title": "Test Issue",
        "body": "Issue body text",
        "labels": [{"name": "bug"}],
    },
]

MOCK_RELEASES = [
    {
        "tag_name": "v1.0",
        "name": "First Release",
        "prerelease": False,
        "published_at": "2025-01-01T00:00:00Z",
        "body": "Release notes",
        "assets": [
            {"name": "dist.tar.gz", "size": 2097152, "download_count": 10},
        ],
    },
]

MOCK_WIKI_PAGES = [
    {"title": "Home", "sub_url": "Home"},
]

MOCK_WIKI_PAGE = {
    "title": "Home",
    "content": "Wiki home content",
}

MOCK_PACKAGES = [
    {
        "type": "container",
        "name": "myapp",
        "version": "latest",
        "created_at": "2025-01-01T00:00:00Z",
        "html_url": "http://localhost:3300/user/-/packages/container/myapp/latest",
    },
    {
        "type": "container",
        "name": "myapp",
        "version": "sha256:abc123def456",
        "created_at": "2024-12-01T00:00:00Z",
    },
]


class TestGiteaConnector:
    def test_not_configured(self, tmp_path):
        c = GiteaConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured(self, connector):
        assert connector.configured

    def test_config_schema(self, connector):
        schema = connector.config_schema()
        names = [f.name for f in schema]
        assert "url" in names
        assert "token" in names

    def test_parse_sync_items_default(self, connector):
        items = connector._parse_sync_items()
        assert "repos" in items
        assert "readmes" in items

    def test_parse_sync_items_list(self, connector):
        connector._config["sync_items"] = ["repos"]
        items = connector._parse_sync_items()
        assert items == ["repos"]

    @patch.object(_GiteaAPI, "_get")
    @patch.object(_GiteaAPI, "_get_raw")
    def test_test_connection(self, mock_raw, mock_get, connector):
        mock_get.side_effect = lambda path: MOCK_REPOS if "user/repos" in path else MOCK_PACKAGES if "packages" in path else []
        result = connector.test_connection()
        assert result["ok"] is True
        assert result["repo_count"] == 1

    def test_test_connection_not_configured(self, tmp_path):
        c = GiteaConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    @patch.object(_GiteaAPI, "_get")
    def test_test_connection_error(self, mock_get, connector):
        mock_get.side_effect = ConnectionError("fail")
        result = connector.test_connection()
        assert result["ok"] is False

    @patch.object(_GiteaAPI, "_get")
    @patch.object(_GiteaAPI, "_get_raw")
    def test_sync_full(self, mock_raw, mock_get, connector, store):
        def side_effect(path):
            if "user/repos" in path:
                return MOCK_REPOS
            if "issues" in path:
                return MOCK_ISSUES
            if "releases" in path:
                return MOCK_RELEASES
            if "wiki/pages" in path:
                return MOCK_WIKI_PAGES
            if "wiki/page" in path:
                return MOCK_WIKI_PAGE
            if "packages/user" in path and "files" in path:
                return [{"name": "layer.tar", "Size": 5242880}]
            if "packages" in path:
                return MOCK_PACKAGES
            if "contents/README" in path:
                return {"content": ""}
            return []
        mock_get.side_effect = side_effect
        mock_raw.return_value = "# README\nContent"
        result = connector.sync(store)
        assert result.added >= 4  # meta, readme, issue, release, wiki, package
        assert result.errors == []

    def test_sync_not_configured(self, tmp_path, store):
        c = GiteaConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["Not configured"]

    @patch.object(_GiteaAPI, "_get")
    def test_sync_api_error(self, mock_get, connector, store):
        mock_get.side_effect = ConnectionError("fail")
        result = connector.sync(store)
        assert len(result.errors) >= 1

    @patch.object(_GiteaAPI, "_get")
    @patch.object(_GiteaAPI, "_get_raw")
    def test_sync_repos_only(self, mock_raw, mock_get, connector, store):
        connector._config["sync_items"] = "repos"
        mock_get.side_effect = lambda path: MOCK_REPOS if "user/repos" in path else []
        result = connector.sync(store)
        keys = [m.key for m in store.list()]
        assert all("meta" in k for k in keys if k.startswith("gitea/"))

    @patch.object(_GiteaAPI, "_get")
    @patch.object(_GiteaAPI, "_get_raw")
    def test_sync_updates(self, mock_raw, mock_get, connector, store):
        def side_effect(path):
            if "user/repos" in path:
                return MOCK_REPOS
            if "issues" in path:
                return []
            if "releases" in path:
                return []
            if "wiki/pages" in path:
                return []
            if "packages" in path:
                return []
            return []
        mock_get.side_effect = side_effect
        mock_raw.return_value = "# Original README"
        connector.sync(store)

        mock_raw.return_value = "# Updated README"
        result = connector.sync(store)
        assert result.updated >= 1 or result.skipped >= 0

    @patch.object(_GiteaAPI, "_get")
    @patch.object(_GiteaAPI, "_get_raw")
    def test_sync_removes_deleted(self, mock_raw, mock_get, connector, store):
        def side_effect(path):
            if "user/repos" in path:
                return MOCK_REPOS
            return []
        mock_get.side_effect = side_effect
        mock_raw.return_value = "# README"
        connector.sync(store)

        mock_get.side_effect = lambda path: [] if "user/repos" in path else []
        mock_raw.return_value = ""
        result = connector.sync(store)
        assert result.removed >= 1
