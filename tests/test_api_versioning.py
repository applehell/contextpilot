"""Tests for API versioning with /api/v1/ prefix support."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


class TestVersionEndpoint:
    def test_api_version(self, client):
        r = client.get("/api/version")
        assert r.status_code == 200
        data = r.json()
        assert data["current"] == "v1"
        assert data["supported"] == ["v1"]
        assert data["deprecation_notice"] is None

    def test_api_v1_version(self, client):
        r = client.get("/api/v1/version")
        assert r.status_code == 200
        data = r.json()
        assert data["current"] == "v1"


class TestV1Rewrite:
    def test_memories_original(self, client):
        r = client.get("/api/memories")
        assert r.status_code == 200

    def test_memories_v1(self, client):
        r = client.get("/api/v1/memories")
        assert r.status_code == 200

    def test_memories_same_result(self, client):
        r1 = client.get("/api/memories")
        r2 = client.get("/api/v1/memories")
        assert r1.status_code == r2.status_code
        assert r1.json() == r2.json()

    def test_connectors_v1(self, client):
        r = client.get("/api/v1/connectors")
        assert r.status_code == 200

    def test_profiles_v1(self, client):
        r = client.get("/api/v1/profiles")
        assert r.status_code == 200


class TestNonVersioned:
    def test_health_not_affected(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_v1_not_routed(self, client):
        r = client.get("/api/v1/health")
        # /health is not under /api/, so /api/v1/health rewrites to /api/health
        # which doesn't exist -> 404 (or whatever the app returns)
        assert r.status_code in (404, 405)

    def test_root_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
