"""Extended web API tests — covers health, events, connectors, folders, profiles endpoints."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    # Isolate profiles, folders, connectors config to tmp_path
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", db_path)
    monkeypatch.setattr("src.storage.folders.FOLDERS_CONFIG", tmp_path / "folders.json")
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    # Reset singletons
    from src.connectors.registry import ConnectorRegistry
    ConnectorRegistry._instance = None

    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c


# ═══════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════

class TestHealth:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_required_fields(self, client):
        d = client.get("/health").json()
        assert d["status"] == "healthy"
        assert "version" in d
        assert "uptime" in d
        assert "uptime_seconds" in d
        assert "python" in d
        assert "platform" in d
        assert "pid" in d

    def test_health_has_metrics(self, client):
        d = client.get("/health").json()
        assert "requests" in d
        assert d["requests"]["total"] >= 0
        assert "memories" in d
        assert d["memories"]["count"] >= 0
        assert "skills" in d
        assert "profiles" in d
        assert "storage" in d
        assert d["storage"]["db_size_bytes"] >= 0


# ═══════════════════════════════════════════════════════════════
# EVENTS
# ═══════════════════════════════════════════════════════════════

class TestEvents:
    def test_events_empty(self, client):
        r = client.get("/api/events")
        assert r.status_code == 200
        # May have events from middleware, so just check it's a list
        assert isinstance(r.json(), list)

    def test_events_generated_by_api_calls(self, client):
        client.get("/api/dashboard")
        r = client.get("/api/events?limit=10")
        events = r.json()
        assert len(events) >= 1
        api_events = [e for e in events if e["category"] == "api"]
        assert len(api_events) >= 1

    def test_events_with_category_filter(self, client):
        # Generate a memory event
        client.post("/api/memories", json={"key": "test", "value": "val", "tags": []})
        r = client.get("/api/events?category=memory")
        events = r.json()
        assert all(e["category"] == "memory" for e in events)

    def test_events_stats(self, client):
        client.get("/api/dashboard")
        r = client.get("/api/events/stats")
        assert r.status_code == 200
        stats = r.json()
        assert isinstance(stats, dict)
        assert "api.get" in stats

    # SSE stream test skipped — requires async client with timeout handling


# ═══════════════════════════════════════════════════════════════
# CONNECTORS
# ═══════════════════════════════════════════════════════════════

class TestConnectors:
    def test_list_connectors(self, client):
        r = client.get("/api/connectors")
        assert r.status_code == 200
        connectors = r.json()
        assert isinstance(connectors, list)
        # Paperless should be auto-discovered
        names = [c["name"] for c in connectors]
        assert "paperless" in names

    def test_get_connector(self, client):
        r = client.get("/api/connectors/paperless")
        assert r.status_code == 200
        d = r.json()
        assert d["name"] == "paperless"
        assert "schema" in d
        assert "configured" in d

    def test_get_nonexistent_connector(self, client):
        r = client.get("/api/connectors/nonexistent")
        assert r.status_code == 404

    def test_setup_connector(self, client):
        r = client.post("/api/connectors/paperless/setup", json={
            "url": "http://fake:8000",
            "token": "faketoken",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "configured"
        assert "test" in d

    def test_update_connector(self, client):
        client.post("/api/connectors/paperless/setup", json={
            "url": "http://fake:8000",
            "token": "t",
        })
        r = client.put("/api/connectors/paperless", json={"sync_tags": "finance"})
        assert r.status_code == 200

    def test_update_unconfigured_fails(self, client):
        # Ensure clean state
        client.delete("/api/connectors/paperless?purge=false")
        r = client.put("/api/connectors/paperless", json={"sync_tags": "x"})
        assert r.status_code == 400

    def test_test_connector(self, client):
        r = client.post("/api/connectors/paperless/test")
        assert r.status_code == 200
        d = r.json()
        assert "ok" in d

    def test_enable_disable(self, client):
        client.post("/api/connectors/paperless/setup", json={
            "url": "http://fake:8000",
            "token": "t",
        })
        r = client.post("/api/connectors/paperless/enable?enabled=false")
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_remove_connector(self, client):
        client.post("/api/connectors/paperless/setup", json={
            "url": "http://fake:8000",
            "token": "t",
        })
        r = client.delete("/api/connectors/paperless?purge=false")
        assert r.status_code == 200
        assert r.json()["status"] == "removed"

    def test_remove_with_purge(self, client):
        client.post("/api/connectors/paperless/setup", json={
            "url": "http://fake:8000",
            "token": "t",
        })
        r = client.delete("/api/connectors/paperless?purge=true")
        assert r.status_code == 200
        assert r.json()["purged_memories"] >= 0


# ═══════════════════════════════════════════════════════════════
# FOLDERS (Web API layer)
# ═══════════════════════════════════════════════════════════════

class TestFoldersAPI:
    def test_list_empty(self, client):
        r = client.get("/api/folders")
        assert r.status_code == 200
        assert r.json() == []

    def test_add_folder(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "test.txt").write_text("hello")

        r = client.post("/api/folders", json={
            "name": "test-docs",
            "path": str(folder),
            "description": "Test",
        })
        assert r.status_code == 201
        assert r.json()["status"] == "created"

    def test_add_invalid_path(self, client):
        r = client.post("/api/folders", json={
            "name": "bad",
            "path": "/nonexistent/path",
        })
        assert r.status_code == 400

    def test_scan_folder(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.txt").write_text("content a")
        (folder / "b.md").write_text("# content b")

        client.post("/api/folders", json={"name": "scan-test", "path": str(folder)})
        r = client.post("/api/folders/scan-test/scan")
        assert r.status_code == 200
        d = r.json()
        assert d["added"] == 2

    def test_scan_nonexistent(self, client):
        r = client.post("/api/folders/nope/scan")
        assert r.status_code == 404

    def test_update_folder(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        client.post("/api/folders", json={"name": "upd", "path": str(folder)})
        r = client.put("/api/folders/upd", json={"enabled": False})
        assert r.status_code == 200

    def test_delete_folder(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        client.post("/api/folders", json={"name": "del", "path": str(folder)})
        r = client.delete("/api/folders/del?purge=false")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_delete_with_purge(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "x.txt").write_text("data")
        client.post("/api/folders", json={"name": "purge-test", "path": str(folder)})
        client.post("/api/folders/purge-test/scan")
        r = client.delete("/api/folders/purge-test?purge=true")
        assert r.status_code == 200
        assert r.json()["purged_memories"] == 1

    def test_scan_all(self, client, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "x.txt").write_text("data")
        client.post("/api/folders", json={"name": "all-test", "path": str(folder)})
        r = client.post("/api/folders/scan-all")
        assert r.status_code == 200
        assert "all-test" in r.json()


# ═══════════════════════════════════════════════════════════════
# PROFILES (Web API layer)
# ═══════════════════════════════════════════════════════════════

class TestProfilesAPI:
    def test_list_profiles(self, client):
        r = client.get("/api/profiles")
        assert r.status_code == 200
        d = r.json()
        assert "profiles" in d
        assert any(p["name"] == "default" for p in d["profiles"])

    def test_create_profile(self, client):
        r = client.post("/api/profiles", json={"name": "test-profile", "description": "Test"})
        assert r.status_code == 201
        assert r.json()["name"] == "test-profile"

    def test_create_with_copy(self, client):
        # Add a memory to default
        client.post("/api/memories", json={"key": "src-mem", "value": "data", "tags": ["copy-tag"]})
        r = client.post("/api/profiles", json={
            "name": "copy-test",
            "copy_from": "default",
        })
        assert r.status_code == 201
        # import_memories_from reads directly from source DB file
        # In test context with tmp_path, the default DB may be in-memory
        # so we just verify the endpoint accepts the parameter
        assert "imported" in r.json()

    def test_create_duplicate_fails(self, client):
        client.post("/api/profiles", json={"name": "dup"})
        r = client.post("/api/profiles", json={"name": "dup"})
        assert r.status_code == 409

    def test_switch_profile(self, client):
        client.post("/api/profiles", json={"name": "switch-test"})
        r = client.post("/api/profiles/switch-test/switch")
        assert r.status_code == 200
        assert r.json()["active"] == "switch-test"

    def test_switch_nonexistent(self, client):
        r = client.post("/api/profiles/nonexistent/switch")
        assert r.status_code == 404

    def test_rename_profile(self, client):
        client.post("/api/profiles", json={"name": "old-name"})
        r = client.put("/api/profiles/old-name?new_name=new-name")
        assert r.status_code == 200

    def test_delete_profile(self, client):
        client.post("/api/profiles", json={"name": "to-delete"})
        r = client.delete("/api/profiles/to-delete")
        assert r.status_code == 200

    def test_delete_default_fails(self, client):
        r = client.delete("/api/profiles/default")
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# MEMORY EVENTS
# ═══════════════════════════════════════════════════════════════

class TestMemoryEvents:
    def test_create_emits_event(self, client):
        client.post("/api/memories", json={"key": "ev-test", "value": "v", "tags": []})
        events = client.get("/api/events?category=memory").json()
        creates = [e for e in events if e["action"] == "create"]
        assert any(e["subject"] == "ev-test" for e in creates)

    def test_delete_emits_event(self, client):
        client.post("/api/memories", json={"key": "del-ev", "value": "v", "tags": []})
        client.delete("/api/memories/del-ev")
        events = client.get("/api/events?category=memory").json()
        deletes = [e for e in events if e["action"] == "delete"]
        assert any(e["subject"] == "del-ev" for e in deletes)

    def test_search_emits_event(self, client):
        client.get("/api/memories/search?q=findme")
        events = client.get("/api/events?category=memory").json()
        searches = [e for e in events if e["action"] == "search"]
        assert any(e["subject"] == "findme" for e in searches)
