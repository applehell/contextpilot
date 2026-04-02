"""Tests for system router endpoints — maintenance, MCP, scheduler, embeddings, webhooks, search."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


def _seed(client, key="test/mem", value="hello", tags=None):
    client.post("/api/memories", json={"key": key, "value": value, "tags": tags or ["test"]})


class TestSetupStatus:
    def test_setup_status_fresh(self, client):
        r = client.get("/api/setup-status")
        assert r.status_code == 200
        data = r.json()
        assert "profiles" in data
        assert "memory_count" in data
        assert "is_fresh" in data

    def test_setup_status_with_memories(self, client):
        _seed(client)
        r = client.get("/api/setup-status")
        data = r.json()
        assert data["memory_count"] >= 1


class TestDashboard:
    def test_dashboard(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "memory_count" in data
        assert "memory_tokens" in data
        assert "skill_total" in data
        assert "activity" in data

    def test_dashboard_with_data(self, client):
        _seed(client)
        r = client.get("/api/dashboard")
        data = r.json()
        assert data["memory_count"] >= 1


class TestSkills:
    def test_list_skills(self, client):
        r = client.get("/api/skills")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestGlobalSearch:
    def test_global_search(self, client):
        _seed(client, "search/target", "findme content", ["searchtag"])
        r = client.get("/api/global-search", params={"q": "findme"})
        assert r.status_code == 200
        data = r.json()
        assert "memories" in data
        assert "templates" in data
        assert "connectors" in data
        assert "folders" in data
        assert len(data["memories"]) >= 1

    def test_global_search_no_results(self, client):
        r = client.get("/api/global-search", params={"q": "nonexistent_xyz"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["memories"]) == 0


class TestMCPStatus:
    def test_mcp_status(self, client):
        r = client.get("/api/mcp-status")
        assert r.status_code == 200
        data = r.json()
        assert "registered" in data
        assert "config" in data

    def test_mcp_register(self, client):
        with patch("src.core.claude_config.register_mcp"):
            r = client.post("/api/mcp/register", json={"port": 8500, "transport": "sse"})
            assert r.status_code == 200
            data = r.json()
            assert data["status"] == "registered"
            assert data["port"] == 8500

    def test_mcp_register_default(self, client):
        with patch("src.core.claude_config.register_mcp"):
            r = client.post("/api/mcp/register", json={})
            assert r.status_code == 200
            assert r.json()["port"] == 8400

    def test_mcp_register_invalid_json(self, client):
        r = client.post("/api/mcp/register", content="not json", headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_mcp_deregister(self, client):
        with patch("src.core.claude_config.deregister_mcp"):
            r = client.post("/api/mcp/deregister")
            assert r.status_code == 200
            assert r.json()["status"] == "deregistered"


class TestMaintenance:
    def test_vacuum(self, client):
        r = client.post("/api/maintenance/vacuum")
        assert r.status_code == 200
        assert r.json()["status"] == "vacuumed"

    def test_rebuild_fts(self, client):
        r = client.post("/api/maintenance/rebuild-fts")
        assert r.status_code == 200
        assert r.json()["status"] == "rebuilt"

    def test_db_stats(self, client):
        r = client.get("/api/maintenance/db-stats")
        assert r.status_code == 200
        data = r.json()
        assert "db_size_bytes" in data
        assert "page_count" in data
        assert "memory_count" in data
        assert "schema_version" in data
        assert "fragmentation_pct" in data

    def test_trash_cleanup(self, client):
        r = client.post("/api/maintenance/trash-cleanup", params={"days": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "cleaned"
        assert "removed" in data


class TestBackups:
    def test_create_and_list_backups(self, client):
        r = client.post("/api/backups")
        assert r.status_code == 201
        data = r.json()
        assert "filename" in data
        assert "size_bytes" in data

        r = client.get("/api/backups")
        assert r.status_code == 200
        backups = r.json()
        assert len(backups) >= 1

    def test_restore_backup(self, client):
        r = client.post("/api/backups")
        filename = r.json()["filename"]
        r = client.post(f"/api/backups/{filename}/restore")
        assert r.status_code == 200
        assert r.json()["status"] == "restored"

    def test_restore_invalid_backup(self, client):
        r = client.post("/api/backups/nonexistent.zip/restore")
        assert r.status_code == 400

    def test_delete_backup(self, client):
        r = client.post("/api/backups")
        filename = r.json()["filename"]
        r = client.delete(f"/api/backups/{filename}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_delete_nonexistent_backup(self, client):
        r = client.delete("/api/backups/nonexistent.zip")
        assert r.status_code == 400


class TestWebhooks:
    def test_list_webhooks_empty(self, client):
        r = client.get("/api/webhooks")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_add_webhook(self, client):
        r = client.post("/api/webhooks", json={
            "name": "test-hook",
            "type": "generic",
            "url": "http://example.com/hook",
            "events": ["memory.create"],
        })
        assert r.status_code == 201
        assert r.json()["status"] == "created"

    def test_add_and_list_webhooks(self, client):
        client.post("/api/webhooks", json={
            "name": "hook1",
            "type": "generic",
            "url": "http://example.com/hook",
        })
        r = client.get("/api/webhooks")
        assert len(r.json()) >= 1

    def test_add_webhook_invalid_json(self, client):
        r = client.post("/api/webhooks", content="not json", headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_remove_webhook(self, client):
        client.post("/api/webhooks", json={
            "name": "to-remove",
            "type": "generic",
            "url": "http://example.com/hook",
        })
        r = client.delete("/api/webhooks/to-remove")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_remove_nonexistent_webhook(self, client):
        r = client.delete("/api/webhooks/nonexistent")
        assert r.status_code == 404

    def test_test_webhook(self, client):
        r = client.post("/api/webhooks/test", json={
            "event": "test",
            "message": "Hello!",
        })
        assert r.status_code == 200
        assert "results" in r.json()

    def test_test_webhook_invalid_json(self, client):
        r = client.post("/api/webhooks/test", content="bad", headers={"Content-Type": "application/json"})
        assert r.status_code == 400


class TestScheduler:
    def test_scheduler_status(self, client):
        r = client.get("/api/scheduler")
        assert r.status_code == 200
        data = r.json()
        assert "running" in data
        assert "interval_minutes" in data

    def test_scheduler_start_and_stop(self, client):
        r = client.post("/api/scheduler/start", params={"interval": 5})
        assert r.status_code == 200
        assert r.json()["status"] == "started"

        r = client.post("/api/scheduler/stop")
        assert r.status_code == 200
        assert r.json()["status"] == "stopped"

    def test_scheduler_run_now(self, client):
        r = client.post("/api/scheduler/run-now")
        assert r.status_code == 200
        data = r.json()
        assert "folders" in data
        assert "connectors" in data


class TestEmbeddings:
    def test_index_status(self, client):
        r = client.get("/api/embeddings/index/status")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data

    def test_embedding_stats(self, client):
        r = client.get("/api/embeddings/stats")
        assert r.status_code == 200

    def test_index_embeddings(self, client):
        r = client.post("/api/embeddings/index")
        assert r.status_code == 200
        assert r.json()["status"] in ("started", "already_running")


class TestSemanticSearch:
    def test_keyword_search(self, client):
        _seed(client, "sem/test", "keyword search target")
        r = client.get("/api/semantic-search", params={"q": "keyword", "mode": "keyword", "limit": 5})
        assert r.status_code == 200
        results = r.json()
        assert isinstance(results, list)

    def test_semantic_search(self, client):
        _seed(client, "sem/test2", "semantic test")
        r = client.get("/api/semantic-search", params={"q": "test", "mode": "semantic", "limit": 5})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_hybrid_search(self, client):
        _seed(client, "sem/test3", "hybrid test")
        r = client.get("/api/semantic-search", params={"q": "test", "mode": "hybrid", "limit": 5})
        assert r.status_code == 200
        assert isinstance(r.json(), list)
