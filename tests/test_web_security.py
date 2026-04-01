"""Tests for web security fixes: CSP headers, API key auth, upload size limits, XSS prevention."""
from __future__ import annotations

import io
import os

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app, MAX_UPLOAD_BYTES


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
def authed_client(tmp_path, monkeypatch):
    """Client with API key authentication enabled."""
    db_path = tmp_path / "test_auth.db"
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", db_path)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.webhooks._DATA_DIR", tmp_path)
    from src.connectors.registry import ConnectorRegistry
    ConnectorRegistry._instance = None
    monkeypatch.setattr("src.web.app.API_KEY", "test-secret-key-123")

    app = create_app(db_path=db_path)
    with TestClient(app) as c:
        yield c


# ═══════════════════════════════════════════════════════════════
# M11: CSP Header
# ═══════════════════════════════════════════════════════════════

class TestCSPHeader:
    def test_csp_header_present(self, client):
        r = client.get("/health")
        assert "Content-Security-Policy" in r.headers

    def test_csp_header_contains_default_src(self, client):
        csp = client.get("/health").headers["Content-Security-Policy"]
        assert "default-src 'self'" in csp

    def test_csp_allows_cdn_scripts(self, client):
        csp = client.get("/health").headers["Content-Security-Policy"]
        assert "https://unpkg.com" in csp
        assert "https://cdn.jsdelivr.net" in csp

    def test_csp_header_on_api_routes(self, client):
        r = client.get("/api/dashboard")
        assert "Content-Security-Policy" in r.headers

    def test_security_headers_still_present(self, client):
        r = client.get("/health")
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "SAMEORIGIN"
        assert r.headers["Referrer-Policy"] == "same-origin"


# ═══════════════════════════════════════════════════════════════
# K1: API Key Authentication
# ═══════════════════════════════════════════════════════════════

class TestAPIKeyAuth:
    def test_no_auth_when_key_not_set(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200

    def test_health_always_accessible(self, authed_client):
        r = authed_client.get("/health")
        assert r.status_code == 200

    def test_api_rejected_without_key(self, authed_client):
        r = authed_client.get("/api/dashboard")
        assert r.status_code == 401
        assert r.json()["error"] == "Unauthorized"

    def test_api_accepted_with_header_key(self, authed_client):
        r = authed_client.get("/api/dashboard", headers={"X-API-Key": "test-secret-key-123"})
        assert r.status_code == 200

    def test_api_accepted_with_query_key(self, authed_client):
        r = authed_client.get("/api/dashboard?api_key=test-secret-key-123")
        assert r.status_code == 200

    def test_api_rejected_with_wrong_key(self, authed_client):
        r = authed_client.get("/api/dashboard", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_post_rejected_without_key(self, authed_client):
        r = authed_client.post("/api/estimate", json={"text": "hello"})
        assert r.status_code == 401

    def test_post_accepted_with_key(self, authed_client):
        r = authed_client.post(
            "/api/estimate",
            json={"text": "hello"},
            headers={"X-API-Key": "test-secret-key-123"},
        )
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════
# M10: Upload Size Limit
# ═══════════════════════════════════════════════════════════════

class TestUploadSizeLimit:
    def test_max_upload_bytes_constant(self):
        assert MAX_UPLOAD_BYTES == 50 * 1024 * 1024

    def test_import_json_rejects_large_file(self, client):
        # Create a fake large payload (just over limit)
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        r = client.post(
            "/api/import/json",
            files={"file": ("big.json", io.BytesIO(big), "application/json")},
        )
        assert r.status_code == 413

    def test_import_json_accepts_small_file(self, client):
        content = b'{"memories": []}'
        r = client.post(
            "/api/import/json",
            files={"file": ("small.json", io.BytesIO(content), "application/json")},
        )
        assert r.status_code == 200

    def test_import_claude_md_rejects_large_file(self, client):
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        r = client.post(
            "/api/import/claude-md",
            files={"file": ("big.md", io.BytesIO(big), "text/markdown")},
        )
        assert r.status_code == 413

    def test_import_copilot_md_rejects_large_file(self, client):
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        r = client.post(
            "/api/import/copilot-md",
            files={"file": ("big.md", io.BytesIO(big), "text/markdown")},
        )
        assert r.status_code == 413

    def test_import_sqlite_rejects_large_file(self, client):
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        r = client.post(
            "/api/import/sqlite",
            files={"file": ("big.db", io.BytesIO(big), "application/octet-stream")},
        )
        assert r.status_code == 413

    def test_profile_import_zip_rejects_large_file(self, client):
        big = b"x" * (MAX_UPLOAD_BYTES + 1)
        r = client.post(
            "/api/profiles/import-zip",
            files={"file": ("big.zip", io.BytesIO(big), "application/zip")},
        )
        assert r.status_code == 413


# ═══════════════════════════════════════════════════════════════
# H2: XSS in Knowledge Graph
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeGraphXSS:
    def test_xss_in_memory_key_escaped(self, client):
        # Create a memory with XSS in the key
        r = client.post("/api/memories", json={
            "key": '<script>alert("xss")</script>/test',
            "value": "safe value",
            "tags": ["test"],
        })
        assert r.status_code == 201

        r = client.get("/api/knowledge-graph")
        assert r.status_code == 200
        data = r.json()
        for node in data["nodes"]:
            assert "<script>" not in node["title"]
            assert "&lt;script&gt;" in node["title"] or "<script>" not in node["title"]

    def test_xss_in_tags_escaped(self, client):
        r = client.post("/api/memories", json={
            "key": "safe/key",
            "value": "safe value",
            "tags": ['<img src=x onerror="alert(1)">'],
        })
        assert r.status_code == 201

        r = client.get("/api/knowledge-graph")
        data = r.json()
        for node in data["nodes"]:
            if "safe/key" in node["id"]:
                assert 'onerror="alert(1)"' not in node["title"]
