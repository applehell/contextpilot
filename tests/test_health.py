"""Tests for the /health endpoint."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


class TestHealthBasic:
    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_existing_fields(self, client):
        data = client.get("/health").json()
        for key in ("status", "version", "uptime", "uptime_seconds", "python",
                     "platform", "pid", "requests", "memories", "skills",
                     "profiles", "storage"):
            assert key in data, f"Missing field: {key}"

    def test_health_requests_structure(self, client):
        data = client.get("/health").json()
        assert "total" in data["requests"]
        assert "errors" in data["requests"]


class TestHealthNewFields:
    def test_db_schema_version_present(self, client):
        data = client.get("/health").json()
        assert "db_schema_version" in data
        assert isinstance(data["db_schema_version"], int)

    def test_connectors_present(self, client):
        data = client.get("/health").json()
        assert "connectors" in data
        if data["connectors"] is not None:
            for key in ("total", "configured", "enabled", "last_sync_errors"):
                assert key in data["connectors"], f"Missing connector field: {key}"

    def test_mcp_present(self, client):
        data = client.get("/health").json()
        assert "mcp" in data
        if data["mcp"] is not None:
            assert "registered" in data["mcp"]
            assert "port" in data["mcp"]

    def test_embeddings_present(self, client):
        data = client.get("/health").json()
        assert "embeddings" in data
        if data["embeddings"] is not None:
            assert "status" in data["embeddings"]
            assert "indexed" in data["embeddings"]


class TestHealthDegradedStatus:
    def test_healthy_when_no_errors(self, client):
        data = client.get("/health").json()
        # With no configured connectors and enough disk, should be healthy
        assert data["status"] == "healthy"

    def test_degraded_on_connector_errors(self, client):
        """Patch connector registry to simulate sync errors."""
        mock_connector = MagicMock()
        mock_connector.configured = True
        mock_connector.enabled = True
        mock_connector.info.return_value = {
            "sync_history": [{"errors": 3, "timestamp": 1}],
        }

        mock_registry = MagicMock()
        mock_registry.list.return_value = [mock_connector]

        with patch("src.connectors.registry.ConnectorRegistry.instance", return_value=mock_registry):
            data = client.get("/health").json()
            assert data["status"] == "degraded"
            assert data["connectors"]["last_sync_errors"] == 1

    def test_degraded_on_low_disk(self, client):
        """Patch shutil.disk_usage to simulate >90% disk usage."""
        fake_usage = MagicMock()
        fake_usage.total = 100 * 1024**3  # 100 GB
        fake_usage.free = 5 * 1024**3     # 5 GB (5% free)
        fake_usage.used = 95 * 1024**3

        with patch("shutil.disk_usage", return_value=fake_usage):
            data = client.get("/health").json()
            assert data["status"] == "degraded"
