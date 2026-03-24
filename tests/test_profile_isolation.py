"""Integration tests — verify profile switch isolates ALL data."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
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


def _create_and_switch(client, name):
    """Helper: create profile and switch to it, return profile ID."""
    r = client.post("/api/profiles", json={"name": name})
    pid = r.json()["id"]
    client.post(f"/api/profiles/{pid}/switch")
    return pid


class TestMemoryIsolation:
    def test_different_memories_per_profile(self, client):
        client.post("/api/memories", json={"key": "default-mem", "value": "from default", "tags": []})

        pid = _create_and_switch(client, "other")
        r = client.get("/api/memories")
        assert r.json()["total"] == 0

        client.post("/api/memories", json={"key": "other-mem", "value": "from other", "tags": []})

        client.post("/api/profiles/default/switch")
        r = client.get("/api/memories")
        assert r.json()["total"] == 1
        assert r.json()["memories"][0]["key"] == "default-mem"

    def test_search_is_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "findme", "value": "secret data", "tags": []})

        _create_and_switch(client, "empty")
        r = client.get("/api/memories/search?q=secret")
        assert r.json()["total"] == 0

    def test_tags_are_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "t", "value": "v", "tags": ["alpha"]})

        _create_and_switch(client, "no-tags")
        r = client.get("/api/memory-tags")
        assert r.json() == []

    def test_sources_are_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "paperless/1", "value": "doc", "tags": ["paperless"]})

        _create_and_switch(client, "clean")
        r = client.get("/api/memories/sources")
        assert r.json() == []


class TestAssemblyIsolation:
    def test_preview_context_uses_active_profile(self, client):
        for i in range(5):
            client.post("/api/memories", json={"key": f"doc/{i}", "value": f"content {i} " * 50, "tags": []})

        _create_and_switch(client, "sparse")
        client.post("/api/memories", json={"key": "only/one", "value": "just this", "tags": []})
        r = client.post("/api/preview-context?budget=5000")
        assert r.json()["input_count"] == 1

    def test_templates_are_profile_scoped(self, client):
        client.post("/api/templates", json={"name": "tpl", "description": "test", "budget": 1000})

        _create_and_switch(client, "no-tpl")
        r = client.get("/api/templates")
        assert len(r.json()) == 0


class TestConnectorIsolation:
    def test_connectors_have_separate_configs(self, client):
        client.post("/api/connectors/paperless/setup", json={"url": "http://default:8000", "token": "t"})

        _create_and_switch(client, "isolated")
        r = client.get("/api/connectors/paperless")
        assert r.json()["configured"] is False


class TestFolderIsolation:
    def test_folders_are_profile_scoped(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        client.post("/api/folders", json={"name": "my-docs", "path": str(folder)})

        _create_and_switch(client, "no-folders")
        r = client.get("/api/folders")
        assert len(r.json()) == 0


class TestWebhookIsolation:
    def test_webhooks_are_profile_scoped(self, client):
        client.post("/api/webhooks", json={"name": "wh1", "type": "generic", "url": "http://example.com"})

        _create_and_switch(client, "no-hooks")
        r = client.get("/api/webhooks")
        assert len(r.json()) == 0


class TestDashboardIsolation:
    def test_dashboard_reflects_active_profile(self, client):
        client.post("/api/memories", json={"key": "m1", "value": "v", "tags": []})

        _create_and_switch(client, "empty-dash")
        r = client.get("/api/dashboard")
        assert r.json()["memory_count"] == 0

    def test_health_reflects_active_profile(self, client):
        client.post("/api/memories", json={"key": "h", "value": "data", "tags": []})

        _create_and_switch(client, "empty-health")
        r = client.get("/health")
        assert r.json()["memories"]["count"] == 0


class TestSecretsIsolation:
    def test_secrets_scan_is_profile_scoped(self, client):
        client.post("/api/memories", json={"key": "cred", "value": "password=S3cret123!", "tags": []})

        _create_and_switch(client, "no-secrets")
        r = client.get("/api/sensitivity")
        assert r.json()["total"] == 0
