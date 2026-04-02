"""Tests for async endpoint wrappers (asyncio.to_thread usage)."""
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


class TestConnectorAsyncEndpoints:
    def test_connectors_health(self, client):
        r = client.get("/api/connectors/health")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_connector_sync_not_found(self, client):
        r = client.post("/api/connectors/nonexistent/sync")
        assert r.status_code == 404


class TestFolderAsyncEndpoints:
    def test_scan_folder_not_found(self, client):
        r = client.post("/api/folders/nonexistent/scan")
        assert r.status_code == 404

    def test_scan_all_folders_empty(self, client):
        r = client.post("/api/folders/scan-all")
        assert r.status_code == 200
        assert r.json() == {}


class TestSystemAsyncEndpoints:
    def test_db_vacuum(self, client):
        r = client.post("/api/maintenance/vacuum")
        assert r.status_code == 200
        assert r.json()["status"] == "vacuumed"


class TestMemoryAsyncEndpoints:
    def test_bulk_delete_empty(self, client):
        r = client.post("/api/memories/bulk-delete", json=[])
        assert r.status_code == 200
        assert r.json() == {"status": "deleted", "count": 0}

    def test_bulk_delete_with_memories(self, client):
        client.post("/api/memories", json={"key": "async-test-1", "value": "v1", "tags": []})
        client.post("/api/memories", json={"key": "async-test-2", "value": "v2", "tags": []})
        r = client.post("/api/memories/bulk-delete", json=["async-test-1", "async-test-2", "nonexistent"])
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_bulk_tags_empty(self, client):
        r = client.post("/api/memories/bulk-tags", json={"keys": [], "add": ["x"], "remove": []})
        assert r.status_code == 200
        assert r.json() == {"status": "ok", "updated": 0}

    def test_bulk_tags_with_memories(self, client):
        client.post("/api/memories", json={"key": "tag-test-1", "value": "v1", "tags": ["old"]})
        r = client.post("/api/memories/bulk-tags", json={"keys": ["tag-test-1"], "add": ["new"], "remove": ["old"]})
        assert r.status_code == 200
        assert r.json()["updated"] == 1
        m = client.get("/api/memories/tag-test-1").json()
        assert "new" in m["tags"]
        assert "old" not in m["tags"]


class TestAnalyticsAsyncEndpoints:
    def test_dashboard_stats(self, client):
        r = client.get("/api/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "size_distribution" in data

    def test_find_duplicates(self, client):
        r = client.get("/api/duplicates?threshold=0.8&limit=10")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
