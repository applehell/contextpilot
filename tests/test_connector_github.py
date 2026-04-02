"""Tests for the GitHub connector with mocked API."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.connectors.github import GitHubConnector, _GitHubAPI
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


@pytest.fixture
def connector(tmp_path):
    c = GitHubConnector(data_dir=tmp_path)
    c.configure({"repos": "owner/repo1, owner/repo2", "token": "ghp_test"})
    return c


MOCK_REPO = {
    "full_name": "owner/repo1",
    "description": "A test repo",
    "homepage": "https://example.com",
    "language": "Python",
    "stargazers_count": 100,
    "forks_count": 10,
    "open_issues_count": 5,
    "default_branch": "main",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:00Z",
    "pushed_at": "2025-01-01T00:00:00Z",
    "html_url": "https://github.com/owner/repo1",
    "topics": ["python", "tool"],
    "license": {"spdx_id": "MIT"},
}

MOCK_RELEASES = [
    {
        "tag_name": "v1.0.0",
        "name": "Release 1.0",
        "prerelease": False,
        "draft": False,
        "published_at": "2025-01-01T00:00:00Z",
        "author": {"login": "developer"},
        "body": "Initial release notes",
        "html_url": "https://github.com/owner/repo1/releases/v1.0.0",
        "assets": [
            {"name": "app.zip", "browser_download_url": "https://example.com/app.zip",
             "size": 5242880, "download_count": 50},
        ],
    },
]

MOCK_ISSUES = [
    {
        "number": 1,
        "title": "Bug report",
        "state": "open",
        "created_at": "2025-01-02T00:00:00Z",
        "updated_at": "2025-01-03T00:00:00Z",
        "user": {"login": "reporter"},
        "labels": [{"name": "bug"}],
        "body": "Something is broken",
        "html_url": "https://github.com/owner/repo1/issues/1",
    },
    {
        "number": 2,
        "title": "PR Title",
        "state": "open",
        "pull_request": {"url": "..."},  # This is a PR, should be filtered
        "created_at": "2025-01-04T00:00:00Z",
        "updated_at": "2025-01-04T00:00:00Z",
        "user": {"login": "dev"},
        "labels": [],
        "body": "",
        "html_url": "https://github.com/owner/repo1/pull/2",
    },
]


class TestGitHubConnector:
    def test_not_configured(self, tmp_path):
        c = GitHubConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured(self, connector):
        assert connector.configured

    def test_parse_repos(self, connector):
        repos = connector._parse_repos()
        assert len(repos) == 2
        assert repos[0] == ("owner", "repo1")

    def test_parse_sync_items_default(self, connector):
        items = connector._parse_sync_items()
        assert "readmes" in items
        assert "releases" in items

    def test_parse_sync_items_list(self, connector):
        connector._config["sync_items"] = ["repos", "readmes"]
        items = connector._parse_sync_items()
        assert items == ["repos", "readmes"]

    @patch.object(_GitHubAPI, "_get")
    @patch.object(_GitHubAPI, "_get_raw")
    def test_sync_full(self, mock_raw, mock_get, connector, store):
        def side_effect(path):
            if "readme" in path:
                return {"download_url": "https://raw.github.com/README.md"}
            if "releases" in path:
                return MOCK_RELEASES
            if "issues" in path:
                return MOCK_ISSUES
            if "/repos/" in path:
                return MOCK_REPO
            if "rate_limit" in path:
                return {"rate": {"remaining": 4999}}
            return {}
        mock_get.side_effect = side_effect
        mock_raw.return_value = "# README\nContent here"

        result = connector.sync(store)
        assert result.added >= 3  # meta, readme, release, issue (x2 repos possible)
        assert result.errors == []

    @patch.object(_GitHubAPI, "_get")
    def test_sync_repo_error(self, mock_get, connector, store):
        mock_get.side_effect = ConnectionError("network fail")
        result = connector.sync(store)
        assert len(result.errors) >= 1

    def test_sync_not_configured(self, tmp_path, store):
        c = GitHubConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["Not configured"]

    @patch.object(_GitHubAPI, "_get")
    def test_test_connection(self, mock_get, connector):
        def side_effect(path):
            if "/repos/" in path:
                return MOCK_REPO
            if "rate_limit" in path:
                return {"rate": {"remaining": 4999}}
            return {}
        mock_get.side_effect = side_effect
        result = connector.test_connection()
        assert result["ok"] is True
        assert len(result["repos"]) >= 1

    def test_test_connection_not_configured(self, tmp_path):
        c = GitHubConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    @patch.object(_GitHubAPI, "_get")
    def test_test_connection_error(self, mock_get, connector):
        mock_get.side_effect = Exception("API down")
        result = connector.test_connection()
        assert result["ok"] is False

    @patch.object(_GitHubAPI, "_get")
    @patch.object(_GitHubAPI, "_get_raw")
    def test_sync_updates(self, mock_raw, mock_get, connector, store):
        def side_effect(path):
            if "readme" in path:
                return {"download_url": "https://raw.github.com/README.md"}
            if "releases" in path:
                return []
            if "issues" in path:
                return []
            if "/repos/" in path:
                return MOCK_REPO
            return {}
        mock_get.side_effect = side_effect
        mock_raw.return_value = "# README\nOriginal"
        connector.sync(store)

        mock_raw.return_value = "# README\nUpdated content"
        result = connector.sync(store)
        assert result.updated >= 1 or result.skipped >= 1

    @patch.object(_GitHubAPI, "_get")
    @patch.object(_GitHubAPI, "_get_raw")
    def test_sync_items_filter(self, mock_raw, mock_get, connector, store):
        connector._config["sync_items"] = "repos"
        def side_effect(path):
            if "/repos/" in path:
                return MOCK_REPO
            return {}
        mock_get.side_effect = side_effect
        result = connector.sync(store)
        keys = [m.key for m in store.list()]
        assert all("meta" in k for k in keys if k.startswith("github/"))
