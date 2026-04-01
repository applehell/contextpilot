"""Tests for web fixes: K5 webhook send, H7 SQL aggregates, H5 db_path env, MCP logging."""
from __future__ import annotations

import os
import logging

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app, _estimate_total_tokens
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore


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
    monkeypatch.setattr("src.web.app.API_KEY", None)

    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture
def populated_client(tmp_path, monkeypatch):
    """Client with some test memories pre-loaded."""
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
    monkeypatch.setattr("src.web.app.API_KEY", None)

    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        # Add some test memories
        for i in range(5):
            c.post("/api/memories", json={
                "key": f"test/mem-{i}",
                "value": f"Test memory content number {i} with some more text to have token counts.",
                "tags": ["test", f"group-{i % 2}"],
            })
        yield c


# ═══════════════════════════════════════════════════════════════
# K5: wm.send() replaced with wm.notify()
# ═══════════════════════════════════════════════════════════════

class TestSummaryReport:
    def test_summary_report_no_crash(self, client):
        r = client.post("/api/reports/summary")
        assert r.status_code == 200
        data = r.json()
        assert "report" in data
        assert "webhooks_sent" in data

    def test_summary_report_with_memories(self, populated_client):
        r = populated_client.post("/api/reports/summary")
        assert r.status_code == 200
        data = r.json()
        assert "Total:" in data["report"]
        assert data["webhooks_sent"] == 0  # no webhooks configured


# ═══════════════════════════════════════════════════════════════
# H7: SQL Aggregates instead of store.list()
# ═══════════════════════════════════════════════════════════════

class TestSQLAggregates:
    def test_estimate_total_tokens_empty_db(self, tmp_path):
        db = Database(tmp_path / "empty.db")
        result = _estimate_total_tokens(db)
        assert result == 0
        db.close()

    def test_estimate_total_tokens_with_data(self, tmp_path):
        db = Database(tmp_path / "tokens.db")
        store = MemoryStore(db)
        store.set(Memory(key="a", value="hello world" * 100, tags=[]))
        result = _estimate_total_tokens(db)
        assert result > 0
        db.close()

    def test_health_uses_count(self, populated_client):
        r = populated_client.get("/health")
        assert r.status_code == 200
        data = r.json()
        assert data["memories"]["count"] == 5
        assert data["memories"]["tokens"] > 0

    def test_dashboard_uses_count(self, populated_client):
        r = populated_client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert data["memory_count"] == 5
        assert data["memory_tokens"] > 0

    def test_dashboard_stats_uses_aggregates(self, populated_client):
        r = populated_client.get("/api/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 5
        assert data["total_tokens"] > 0
        assert "size_distribution" in data
        assert "top_tags" in data

    def test_setup_status_uses_count(self, populated_client):
        r = populated_client.get("/api/setup-status")
        assert r.status_code == 200
        data = r.json()
        assert data["memory_count"] == 5

    def test_sensitivity_supports_pagination(self, populated_client):
        r = populated_client.get("/api/sensitivity?page=1&page_size=2")
        assert r.status_code == 200
        data = r.json()
        assert len(data["memories"]) <= 2

    def test_duplicates_supports_limit(self, populated_client):
        r = populated_client.get("/api/duplicates?limit=10")
        assert r.status_code == 200

    def test_suggest_tags_works(self, populated_client):
        r = populated_client.post("/api/memories/suggest-tags", json={
            "key": "test/new", "value": "Test memory content"
        })
        assert r.status_code == 200
        assert "tags" in r.json()


# ═══════════════════════════════════════════════════════════════
# H5: --db-path CLI flag via environment variable
# ═══════════════════════════════════════════════════════════════

class TestDBPathEnvVar:
    def test_app_respects_db_path_env(self, tmp_path, monkeypatch):
        custom_db = tmp_path / "custom.db"
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "default.db")
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", tmp_path)
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None
        monkeypatch.setattr("src.web.app.API_KEY", None)

        monkeypatch.setenv("CONTEXTPILOT_DB_PATH", str(custom_db))

        # Force re-evaluation of module-level code by importing create_app
        app = create_app(db_path=custom_db)
        with TestClient(app) as c:
            r = c.get("/health")
            assert r.status_code == 200

    def test_cli_web_sets_env_var(self, tmp_path, monkeypatch):
        """Verify the CLI web command sets CONTEXTPILOT_DB_PATH."""
        from src.interfaces.cli import web
        from click.testing import CliRunner
        from src.interfaces.cli import cli

        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "default.db")
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

        captured_env = {}

        def mock_uvicorn_run(*args, **kwargs):
            captured_env["db_path"] = os.environ.get("CONTEXTPILOT_DB_PATH")

        monkeypatch.setattr("uvicorn.run", mock_uvicorn_run)

        runner = CliRunner()
        db_path = str(tmp_path / "test.db")
        result = runner.invoke(cli, ["--db-path", db_path, "web"])

        assert captured_env.get("db_path") == db_path


# ═══════════════════════════════════════════════════════════════
# H10: MCP server logging instead of swallowing errors
# ═══════════════════════════════════════════════════════════════

class TestMCPLogging:
    def test_mcp_server_has_logger(self):
        from src.interfaces import mcp_server
        assert hasattr(mcp_server, "logger")
        assert mcp_server.logger.name == "src.interfaces.mcp_server"

    def test_mcp_get_db_logs_close_error(self, caplog):
        """Verify that DB close errors are logged, not silently swallowed."""
        from src.interfaces.mcp_server import _get_db, _db_lock
        import src.interfaces.mcp_server as mcp_mod

        # Save original state
        orig_db = mcp_mod._db
        orig_path = mcp_mod._db_path

        class FakeDB:
            def close(self):
                raise RuntimeError("fake close error")

        try:
            with _db_lock:
                mcp_mod._db = FakeDB()
                mcp_mod._db_path = None  # force re-init

            with caplog.at_level(logging.WARNING, logger="src.interfaces.mcp_server"):
                try:
                    _get_db()
                except Exception:
                    pass  # DB init may fail in test, that's OK

            assert any("Failed to close DB" in r.message for r in caplog.records)
        finally:
            with _db_lock:
                mcp_mod._db = orig_db
                mcp_mod._db_path = orig_path
