"""Extended web API tests — covers health, events, connectors, folders, profiles endpoints."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    # Isolate ALL profile-dependent storage to tmp_path
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", db_path)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.webhooks._DATA_DIR", tmp_path)
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
        assert any(p["id"] == "default" for p in d["profiles"])

    def test_create_returns_id(self, client):
        r = client.post("/api/profiles", json={"name": "test-profile", "description": "Test"})
        assert r.status_code == 201
        assert "id" in r.json()
        assert r.json()["name"] == "test-profile"

    def test_create_with_copy(self, client):
        client.post("/api/memories", json={"key": "src-mem", "value": "data", "tags": ["copy-tag"]})
        r = client.post("/api/profiles", json={"name": "copy-test", "copy_from": "default"})
        assert r.status_code == 201
        assert "imported" in r.json()

    def test_create_duplicate_fails(self, client):
        client.post("/api/profiles", json={"name": "dup"})
        r = client.post("/api/profiles", json={"name": "dup"})
        assert r.status_code == 409

    def test_switch_by_id(self, client):
        r = client.post("/api/profiles", json={"name": "switch-test"})
        pid = r.json()["id"]
        r = client.post(f"/api/profiles/{pid}/switch")
        assert r.status_code == 200
        assert r.json()["active"] == pid

    def test_switch_nonexistent(self, client):
        r = client.post("/api/profiles/nonexistent/switch")
        assert r.status_code == 404

    def test_rename_by_id(self, client):
        r = client.post("/api/profiles", json={"name": "old-name"})
        pid = r.json()["id"]
        r = client.put(f"/api/profiles/{pid}?new_name=new-name")
        assert r.status_code == 200

    def test_delete_by_id(self, client):
        r = client.post("/api/profiles", json={"name": "to-delete"})
        pid = r.json()["id"]
        r = client.delete(f"/api/profiles/{pid}")
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


# ═══════════════════════════════════════════════════════════════
# TEMPLATES
# ═══════════════════════════════════════════════════════════════

class TestTemplates:
    def test_list_empty(self, client):
        r = client.get("/api/templates")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_and_list(self, client):
        r = client.post("/api/templates", json={
            "name": "test-tpl", "description": "Test template",
            "tag_filter": ["python"], "key_filter": "src/", "budget": 5000,
        })
        assert r.status_code == 201
        templates = client.get("/api/templates").json()
        assert len(templates) == 1
        assert templates[0]["name"] == "test-tpl"
        assert templates[0]["budget"] == 5000

    def test_delete(self, client):
        client.post("/api/templates", json={"name": "del-me", "budget": 1000})
        r = client.delete("/api/templates/del-me")
        assert r.status_code == 200
        assert client.get("/api/templates").json() == []

    def test_delete_not_found(self, client):
        r = client.delete("/api/templates/nonexistent")
        assert r.status_code == 404

    def test_assemble_template(self, client):
        client.post("/api/memories", json={"key": "asm/a", "value": "Memory A content", "tags": ["asm"]})
        client.post("/api/memories", json={"key": "asm/b", "value": "Memory B content", "tags": ["asm"]})
        client.post("/api/memories", json={"key": "other/c", "value": "Unrelated", "tags": ["other"]})
        client.post("/api/templates", json={
            "name": "asm-test", "tag_filter": ["asm"], "budget": 4000,
        })
        r = client.post("/api/templates/asm-test/assemble")
        assert r.status_code == 200
        d = r.json()
        assert d["template"] == "asm-test"
        assert d["total_matching"] == 2
        assert d["block_count"] >= 1
        assert "assembly_id" in d
        assert d["used_tokens"] <= d["budget"]

    def test_assemble_not_found(self, client):
        r = client.post("/api/templates/ghost/assemble")
        assert r.status_code == 404

    def test_assemble_uses_compression(self, client):
        long_code = "import os\nfrom pathlib import Path\ndef main():\n    pass\nclass Foo:\n    pass\n" * 10
        client.post("/api/memories", json={"key": "code/big", "value": long_code, "tags": ["code"]})
        client.post("/api/templates", json={
            "name": "code-tpl", "tag_filter": ["code"], "budget": 4000,
        })
        r = client.post("/api/templates/code-tpl/assemble")
        d = r.json()
        assert d["block_count"] >= 1
        for b in d["blocks"]:
            assert "compress_hint" in b

    def test_suggest_empty(self, client):
        r = client.get("/api/templates/suggest")
        assert r.status_code == 200
        assert r.json()["suggestions"] == []

    def test_suggest_with_memories(self, client):
        for i in range(5):
            client.post("/api/memories", json={
                "key": f"cluster/item{i}", "value": f"Content {i}", "tags": ["grouped"],
            })
        r = client.get("/api/templates/suggest")
        assert r.status_code == 200
        suggestions = r.json()["suggestions"]
        assert len(suggestions) >= 1
        names = [s["name"] for s in suggestions]
        assert "cluster-context" in names

    def test_suggest_skips_existing(self, client):
        for i in range(5):
            client.post("/api/memories", json={
                "key": f"pfx/m{i}", "value": f"Val {i}", "tags": ["t"],
            })
        client.post("/api/templates", json={"name": "pfx-context", "budget": 2000})
        r = client.get("/api/templates/suggest")
        names = [s["name"] for s in r.json()["suggestions"]]
        assert "pfx-context" not in names


# ═══════════════════════════════════════════════════════════════
# INPUT VALIDATION (corner cases)
# ═══════════════════════════════════════════════════════════════

class TestInputValidation:
    # -- Memories --

    def test_create_memory_empty_key(self, client):
        with pytest.raises(ValueError, match="key must not be empty"):
            client.post("/api/memories", json={"key": "", "value": "v", "tags": []})

    def test_create_memory_special_chars_in_value(self, client):
        value = 'back\\slash "quotes" and\nnewlines\ttabs'
        r = client.post("/api/memories", json={"key": "special-val", "value": value, "tags": []})
        assert r.status_code == 201
        got = client.get("/api/memories/special-val").json()
        assert got["value"] == value

    def test_create_memory_fts5_operators_in_value(self, client):
        r = client.post("/api/memories", json={
            "key": "fts-ops", "value": "AND OR NOT * NEAR", "tags": [],
        })
        assert r.status_code == 201

    # -- Search --

    def test_search_special_chars(self, client):
        r = client.get("/api/memories/search", params={"q": "test*+AND+(foo)"})
        assert r.status_code == 200

    def test_search_empty_query(self, client):
        r = client.get("/api/memories/search", params={"q": ""})
        assert r.status_code == 200

    def test_search_quotes_in_query(self, client):
        r = client.get("/api/memories/search", params={"q": '"hello"'})
        assert r.status_code == 200

    def test_search_very_long_query(self, client):
        r = client.get("/api/memories/search", params={"q": "a" * 2000})
        assert r.status_code == 200

    # -- Templates --

    def test_create_template_empty_name(self, client):
        r = client.post("/api/templates", json={"name": "", "budget": 1000})
        assert r.status_code == 400

    def test_create_template_missing_name(self, client):
        r = client.post("/api/templates", json={})
        assert r.status_code == 400

    def test_create_template_zero_budget(self, client):
        r = client.post("/api/templates", json={"name": "zero", "budget": 0})
        assert r.status_code == 400

    def test_create_template_negative_budget(self, client):
        r = client.post("/api/templates", json={"name": "neg", "budget": -100})
        assert r.status_code == 400

    def test_create_template_huge_budget(self, client):
        r = client.post("/api/templates", json={"name": "huge", "budget": 999999})
        assert r.status_code == 400

    # -- Profiles --

    def test_create_profile_empty_name(self, client):
        r = client.post("/api/profiles", json={"name": ""})
        assert r.status_code == 400

    # -- Assemble --

    def test_assemble_invalid_priority(self, client):
        r = client.post("/api/assemble", json={
            "blocks": [{"content": "hello", "priority": "invalid"}],
            "budget": 1000,
        })
        assert r.status_code == 400

    def test_assemble_missing_content(self, client):
        r = client.post("/api/assemble", json={
            "blocks": [{"priority": "medium"}],
            "budget": 1000,
        })
        assert r.status_code == 422

    # -- Malformed JSON --

    def test_malformed_json_body(self, client):
        r = client.post(
            "/api/memories",
            content=b"{not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 422

    # -- Template suggest --

    def test_template_suggest_empty(self, client):
        r = client.get("/api/templates/suggest")
        assert r.status_code == 200
        assert r.json()["suggestions"] == []

    # -- Relations --

    def test_create_relation_missing_fields(self, client):
        r = client.post("/api/relations", json={})
        assert r.status_code == 400


# ═══════════════════════════════════════════════════════════════
# CONNECTOR ENDPOINTS (extended)
# ═══════════════════════════════════════════════════════════════

class TestConnectorEndpoints:
    def test_list_connectors_returns_all(self, client):
        r = client.get("/api/connectors")
        assert r.status_code == 200
        connectors = r.json()
        assert len(connectors) >= 17

    def test_connectors_have_category(self, client):
        connectors = client.get("/api/connectors").json()
        for c in connectors:
            assert "category" in c, f"Connector {c['name']} missing 'category'"

    def test_connectors_have_setup_guide(self, client):
        connectors = client.get("/api/connectors").json()
        for c in connectors:
            assert "setup_guide" in c, f"Connector {c['name']} missing 'setup_guide'"

    def test_connectors_have_color(self, client):
        connectors = client.get("/api/connectors").json()
        for c in connectors:
            assert "color" in c, f"Connector {c['name']} missing 'color'"

    def test_connector_health(self, client):
        r = client.get("/api/connectors/health")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_connector_health_fields(self, client):
        health = client.get("/api/connectors/health").json()
        for entry in health:
            assert "name" in entry, f"Health entry missing 'name'"
            assert "configured" in entry, f"Health entry {entry.get('name')} missing 'configured'"
            assert "enabled" in entry, f"Health entry {entry.get('name')} missing 'enabled'"
            assert "error_count" in entry, f"Health entry {entry.get('name')} missing 'error_count'"

    def test_connector_history_not_found(self, client):
        r = client.get("/api/connectors/nonexistent/history")
        assert r.status_code == 404

    def test_connector_history_empty(self, client):
        r = client.get("/api/connectors/rss/history")
        assert r.status_code == 200
        assert r.json() == []


# ═══════════════════════════════════════════════════════════════
# CONNECTOR STORE UI
# ═══════════════════════════════════════════════════════════════

class TestConnectorStoreUI:
    def test_index_has_connector_store(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Connector Store" in r.text

    def test_index_has_connector_filters(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert 'conn-filters' in r.text
