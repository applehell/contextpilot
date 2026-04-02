"""Tests for analytics router endpoints — dashboard stats, summary report, analytics, duplicates."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


def _seed(client, key="test/mem", value="hello", tags=None):
    client.post("/api/memories", json={"key": key, "value": value, "tags": tags or ["test"]})


class TestDashboardStats:
    def test_dashboard_stats_empty(self, client):
        r = client.get("/api/dashboard/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "total_tokens" in data
        assert "new_today" in data
        assert "size_distribution" in data
        assert "top_tags" in data
        assert "trash_count" in data
        assert "pinned" in data

    def test_dashboard_stats_with_data(self, client):
        _seed(client, "stats/a", "a " * 50, ["alpha"])
        _seed(client, "stats/b", "b " * 200, ["beta"])
        _seed(client, "stats/c", "c " * 10, ["alpha"])
        r = client.get("/api/dashboard/stats")
        data = r.json()
        assert data["total"] >= 3
        assert data["new_today"] >= 3


class TestSummaryReport:
    def test_summary_report_empty(self, client):
        r = client.post("/api/reports/summary")
        assert r.status_code == 200
        data = r.json()
        assert "report" in data
        assert "webhooks_sent" in data
        assert "Context Pilot Report" in data["report"]

    def test_summary_report_with_data(self, client):
        _seed(client, "report/a", "new memory for report")
        r = client.post("/api/reports/summary")
        data = r.json()
        assert "New today:" in data["report"]


class TestAnalyticsSummary:
    def test_analytics_summary(self, client):
        r = client.get("/api/analytics/summary")
        assert r.status_code == 200

    def test_analytics_top_memories(self, client):
        _seed(client)
        r = client.get("/api/analytics/top-memories", params={"limit": 5})
        assert r.status_code == 200

    def test_analytics_top_tags(self, client):
        _seed(client, "tag/a", "a", ["alpha"])
        r = client.get("/api/analytics/top-tags", params={"limit": 5})
        assert r.status_code == 200

    def test_analytics_connector_stats(self, client):
        r = client.get("/api/analytics/connector-stats")
        assert r.status_code == 200

    def test_analytics_memory_growth(self, client):
        r = client.get("/api/analytics/memory-growth", params={"days": 7})
        assert r.status_code == 200
