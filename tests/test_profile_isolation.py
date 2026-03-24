"""Integration tests — verify profile switch isolates ALL data."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    profiles_dir = tmp_path / "profiles"
    config_file = tmp_path / "profiles.json"

    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", profiles_dir)
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", config_file)
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", db_path)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.webhooks._DATA_DIR", tmp_path)

    from src.connectors.registry import ConnectorRegistry
    ConnectorRegistry._instance = None

    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c


class TestMemoryIsolation:
    def test_different_memories_per_profile(self, client):
        # Add memory to default
        client.post("/api/memories", json={"key": "default-mem", "value": "from default", "tags": ["test"]})
        r = client.get("/api/memories")
        assert r.json()["total"] == 1
        assert r.json()["memories"][0]["key"] == "default-mem"

        # Create and switch to new profile
        client.post("/api/profiles", json={"name": "other"})
        client.post("/api/profiles/other/switch")

        # New profile should have 0 memories
        r = client.get("/api/memories")
        assert r.json()["total"] == 0

        # Add memory to other
        client.post("/api/memories", json={"key": "other-mem", "value": "from other", "tags": ["test"]})
        r = client.get("/api/memories")
        assert r.json()["total"] == 1
        assert r.json()["memories"][0]["key"] == "other-mem"

        # Switch back to default — should see original memory
        client.post("/api/profiles/default/switch")
        r = client.get("/api/memories")
        assert r.json()["total"] == 1
        assert r.json()["memories"][0]["key"] == "default-mem"

    def test_search_is_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "findme", "value": "secret data", "tags": []})
        r = client.get("/api/memories/search?q=secret")
        assert r.json()["total"] >= 1

        client.post("/api/profiles", json={"name": "empty"})
        client.post("/api/profiles/empty/switch")

        r = client.get("/api/memories/search?q=secret")
        assert r.json()["total"] == 0

    def test_tags_are_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "t", "value": "v", "tags": ["alpha", "beta"]})
        r = client.get("/api/memory-tags")
        assert "alpha" in r.json()

        client.post("/api/profiles", json={"name": "no-tags"})
        client.post("/api/profiles/no-tags/switch")

        r = client.get("/api/memory-tags")
        assert r.json() == []

    def test_sources_are_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "paperless/1", "value": "doc", "tags": ["paperless"]})
        r = client.get("/api/memories/sources")
        assert any(s["source"] == "paperless" for s in r.json())

        client.post("/api/profiles", json={"name": "clean"})
        client.post("/api/profiles/clean/switch")

        r = client.get("/api/memories/sources")
        assert r.json() == []


class TestAssemblyIsolation:
    def test_preview_context_uses_active_profile(self, client):
        # Add data to default
        for i in range(5):
            client.post("/api/memories", json={"key": f"doc/{i}", "value": f"content {i} " * 50, "tags": []})

        r = client.post("/api/preview-context?budget=5000")
        default_input = r.json()["input_count"]
        assert default_input == 5

        client.post("/api/profiles", json={"name": "sparse"})
        client.post("/api/profiles/sparse/switch")
        client.post("/api/memories", json={"key": "only/one", "value": "just this", "tags": []})

        r = client.post("/api/preview-context?budget=5000")
        assert r.json()["input_count"] == 1

    def test_templates_are_profile_scoped(self, client):
        client.post("/api/templates", json={"name": "default-tpl", "description": "test", "budget": 1000})
        r = client.get("/api/templates")
        assert len(r.json()) == 1

        client.post("/api/profiles", json={"name": "no-tpl"})
        client.post("/api/profiles/no-tpl/switch")

        r = client.get("/api/templates")
        assert len(r.json()) == 0


class TestConnectorIsolation:
    def test_connectors_have_separate_configs(self, client):
        # Setup paperless in default
        client.post("/api/connectors/paperless/setup", json={
            "url": "http://default-server:8000",
            "token": "default-token",
        })
        r = client.get("/api/connectors/paperless")
        assert r.json()["configured"] is True

        # Switch to new profile
        client.post("/api/profiles", json={"name": "isolated"})
        client.post("/api/profiles/isolated/switch")

        # Paperless should NOT be configured here
        r = client.get("/api/connectors/paperless")
        assert r.json()["configured"] is False

        # Setup different config
        client.post("/api/connectors/paperless/setup", json={
            "url": "http://isolated-server:9000",
            "token": "other-token",
        })

        # Switch back to default — should have original config
        client.post("/api/profiles/default/switch")
        r = client.get("/api/connectors/paperless")
        assert r.json()["configured"] is True
        assert "default-server" in r.json()["config"]["url"]


class TestFolderIsolation:
    def test_folders_are_profile_scoped(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.txt").write_text("hello")

        client.post("/api/folders", json={"name": "my-docs", "path": str(folder)})
        r = client.get("/api/folders")
        assert len(r.json()) == 1

        client.post("/api/profiles", json={"name": "no-folders"})
        client.post("/api/profiles/no-folders/switch")

        r = client.get("/api/folders")
        assert len(r.json()) == 0


class TestWebhookIsolation:
    def test_webhooks_are_profile_scoped(self, client):
        client.post("/api/webhooks", json={"name": "wh1", "type": "generic", "url": "http://example.com"})
        r = client.get("/api/webhooks")
        assert len(r.json()) == 1

        client.post("/api/profiles", json={"name": "no-hooks"})
        client.post("/api/profiles/no-hooks/switch")

        r = client.get("/api/webhooks")
        assert len(r.json()) == 0


class TestDashboardIsolation:
    def test_dashboard_reflects_active_profile(self, client):
        for i in range(3):
            client.post("/api/memories", json={"key": f"m{i}", "value": f"val{i}", "tags": []})

        r = client.get("/api/dashboard")
        assert r.json()["memory_count"] == 3

        client.post("/api/profiles", json={"name": "empty-dash"})
        client.post("/api/profiles/empty-dash/switch")

        r = client.get("/api/dashboard")
        assert r.json()["memory_count"] == 0

    def test_health_reflects_active_profile(self, client):
        client.post("/api/memories", json={"key": "h", "value": "data", "tags": []})

        r = client.get("/health")
        assert r.json()["memories"]["count"] == 1

        client.post("/api/profiles", json={"name": "empty-health"})
        client.post("/api/profiles/empty-health/switch")

        r = client.get("/health")
        assert r.json()["memories"]["count"] == 0


class TestDuplicatesIsolation:
    def test_duplicates_are_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "a", "value": "x " * 100, "tags": []})
        client.post("/api/memories", json={"key": "b", "value": "x " * 100, "tags": []})

        r = client.get("/api/duplicates?threshold=0.5")
        assert len(r.json()) >= 1

        client.post("/api/profiles", json={"name": "no-dupes"})
        client.post("/api/profiles/no-dupes/switch")

        r = client.get("/api/duplicates?threshold=0.5")
        assert len(r.json()) == 0


class TestSecretsIsolation:
    def test_secrets_scan_is_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "cred", "value": "password=S3cret123!", "tags": []})

        r = client.get("/api/sensitivity")
        assert r.json()["total"] >= 1

        client.post("/api/profiles", json={"name": "no-secrets"})
        client.post("/api/profiles/no-secrets/switch")

        r = client.get("/api/sensitivity")
        assert r.json()["total"] == 0
