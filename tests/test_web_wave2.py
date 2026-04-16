"""Wave 2 tests: Trash, Maintenance, Analytics, TTL, MCP endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    """Create a test client with an in-memory database."""
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


def _create_memory(client, key="test/mem", value="hello", tags=None, ttl_seconds=None):
    payload = {"key": key, "value": value, "tags": tags or []}
    if ttl_seconds is not None:
        payload["ttl_seconds"] = ttl_seconds
    r = client.post("/api/memories", json=payload)
    assert r.status_code == 201
    return r.json()


# ── Trash Management ──────────────────────────────────────────────

class TestTrash:
    def test_list_trash_empty(self, client):
        r = client.get("/api/trash")
        assert r.status_code == 200
        assert r.json() == []

    def test_trash_and_restore(self, client):
        _create_memory(client, key="trash/item", value="recoverable")

        r = client.delete("/api/memories/trash/item")
        assert r.status_code == 200

        r = client.get("/api/trash")
        assert r.status_code == 200
        items = r.json()
        assert any(i["key"] == "trash/item" for i in items)

        r = client.post("/api/trash/trash/item/restore")
        assert r.status_code == 200
        assert r.json()["status"] == "restored"

        r = client.get("/api/memories/trash/item")
        assert r.status_code == 200
        assert r.json()["value"] == "recoverable"

    def test_purge_trash(self, client):
        _create_memory(client, key="trash/purge1", value="bye")
        client.delete("/api/memories/trash/purge1")

        r = client.get("/api/trash")
        assert len(r.json()) > 0

        r = client.delete("/api/trash")
        assert r.status_code == 200
        assert r.json()["status"] == "emptied"

        r = client.get("/api/trash")
        assert r.json() == []


# ── Maintenance ───────────────────────────────────────────────────

class TestMaintenance:
    def test_db_stats(self, client):
        r = client.get("/api/maintenance/db-stats")
        assert r.status_code == 200
        data = r.json()
        assert "page_count" in data
        assert "memory_count" in data
        assert "schema_version" in data

    def test_vacuum(self, client):
        r = client.post("/api/maintenance/vacuum")
        assert r.status_code == 200
        assert r.json()["status"] == "vacuumed"

    def test_rebuild_fts(self, client):
        r = client.post("/api/maintenance/rebuild-fts")
        assert r.status_code == 200
        assert r.json()["status"] == "rebuilt"

    def test_cleanup_trash(self, client):
        r = client.post("/api/maintenance/trash-cleanup?days=1")
        assert r.status_code == 200
        data = r.json()
        assert "removed" in data

    def test_cleanup_expired(self, client):
        r = client.post("/api/memories/cleanup-expired")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "cleaned"
        assert "removed" in data


# ── Analytics ─────────────────────────────────────────────────────

class TestAnalytics:
    def test_analytics_summary(self, client):
        r = client.get("/api/analytics/summary")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)

    def test_analytics_top_tags(self, client):
        _create_memory(client, key="a/1", value="v", tags=["python"])
        r = client.get("/api/analytics/top-tags")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_analytics_top_memories(self, client):
        r = client.get("/api/analytics/top-memories")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_analytics_memory_growth(self, client):
        r = client.get("/api/analytics/memory-growth")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ── Memory TTL ────────────────────────────────────────────────────

class TestMemoryTTL:
    def test_create_memory_with_ttl(self, client):
        _create_memory(client, key="ttl/short", value="expires", ttl_seconds=3600)
        r = client.get("/api/memories/ttl/short")
        assert r.status_code == 200
        data = r.json()
        assert data["expires_at"] is not None

    def test_memory_ttl_in_response(self, client):
        _create_memory(client, key="ttl/label", value="v", ttl_seconds=86400)
        r = client.get("/api/memories/ttl/label")
        assert r.status_code == 200
        data = r.json()
        assert "ttl_label" in data
        assert data["ttl_label"] is not None

    def test_pin_memory(self, client):
        _create_memory(client, key="pin/me", value="important")
        r = client.post("/api/memories/pin/me/pin?pinned=true")
        assert r.status_code == 200
        assert r.json()["pinned"] is True

    def test_memory_versions(self, client):
        _create_memory(client, key="ver/doc", value="v1")
        client.put("/api/memories/ver/doc", json={"key": "ver/doc", "value": "v2", "tags": []})

        r = client.get("/api/memories/ver/doc/versions")
        assert r.status_code == 200
        versions = r.json()
        assert isinstance(versions, list)
        assert len(versions) >= 1
        assert versions[0]["value"] == "v1"


# ── MCP Web Endpoints ────────────────────────────────────────────

class TestMCP:
    def test_mcp_status(self, client):
        r = client.get("/api/mcp-status")
        assert r.status_code == 200
        data = r.json()
        assert "registered" in data
        assert "config" in data
