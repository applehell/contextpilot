"""Tests for rate limiting — RateLimiter class and middleware integration."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from src.web.rate_limit import RateLimiter


class TestRateLimiter:
    def test_allows_under_limit(self):
        rl = RateLimiter(requests_per_minute=5, burst=2)
        for _ in range(7):
            assert rl.is_allowed("1.2.3.4")

    def test_blocks_over_limit(self):
        rl = RateLimiter(requests_per_minute=3, burst=0)
        for _ in range(3):
            assert rl.is_allowed("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")

    def test_burst_allows_extra(self):
        rl = RateLimiter(requests_per_minute=3, burst=2)
        for _ in range(5):
            assert rl.is_allowed("1.2.3.4")
        assert not rl.is_allowed("1.2.3.4")

    def test_different_ips_independent(self):
        rl = RateLimiter(requests_per_minute=2, burst=0)
        assert rl.is_allowed("1.1.1.1")
        assert rl.is_allowed("1.1.1.1")
        assert not rl.is_allowed("1.1.1.1")
        assert rl.is_allowed("2.2.2.2")

    def test_remaining(self):
        rl = RateLimiter(requests_per_minute=5, burst=0)
        assert rl.remaining("1.1.1.1") == 5
        rl.is_allowed("1.1.1.1")
        assert rl.remaining("1.1.1.1") == 4

    def test_get_retry_after_returns_positive(self):
        rl = RateLimiter(requests_per_minute=1, burst=0)
        rl.is_allowed("1.1.1.1")
        rl.is_allowed("1.1.1.1")  # denied
        retry = rl.get_retry_after("1.1.1.1")
        assert retry >= 1

    def test_get_retry_after_zero_when_empty(self):
        rl = RateLimiter(requests_per_minute=10, burst=0)
        assert rl.get_retry_after("9.9.9.9") == 0

    def test_cleanup_removes_stale(self):
        rl = RateLimiter(requests_per_minute=100, burst=0)
        rl._window["old_ip"] = [time.monotonic() - 120.0]
        rl._last_cleanup = 0  # force cleanup
        rl.is_allowed("trigger")
        assert "old_ip" not in rl._window


def _make_client(tmp_path, monkeypatch, rate_limiter):
    """Helper to create a TestClient with a custom rate limiter."""
    from src.connectors.registry import ConnectorRegistry

    db_path = tmp_path / "test_rl.db"
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", db_path)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.storage.folders._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.core.webhooks._DATA_DIR", tmp_path)
    ConnectorRegistry._instance = None
    monkeypatch.setattr("src.web.app.API_KEY", None)

    from src.web.app import create_app
    app = create_app(db_path=db_path)
    app.state.rate_limiter = rate_limiter
    return app


class TestRateLimitMiddleware:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        rl = RateLimiter(requests_per_minute=5, burst=0)
        app = _make_client(tmp_path, monkeypatch, rl)
        with TestClient(app) as c:
            yield c

    def test_api_returns_remaining_header(self, client):
        r = client.post("/api/estimate", json={"text": "hi"})
        assert "X-RateLimit-Remaining" in r.headers

    def test_429_on_exceeded(self, client):
        for _ in range(5):
            client.post("/api/estimate", json={"text": "x"})
        r = client.post("/api/estimate", json={"text": "x"})
        assert r.status_code == 429
        body = r.json()
        assert body["error"] == "Rate limit exceeded"
        assert "retry_after" in body
        assert body["retry_after"] >= 1

    def test_429_has_retry_after_header(self, client):
        for _ in range(5):
            client.post("/api/estimate", json={"text": "x"})
        r = client.post("/api/estimate", json={"text": "x"})
        assert r.status_code == 429
        assert "Retry-After" in r.headers

    def test_health_not_rate_limited(self, client):
        for _ in range(10):
            r = client.get("/health")
        assert r.status_code == 200

    def test_non_api_not_rate_limited(self, client):
        for _ in range(10):
            r = client.get("/")
        assert r.status_code == 200


class TestRateLimitDisabled:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        app = _make_client(tmp_path, monkeypatch, rate_limiter=None)
        with TestClient(app) as c:
            yield c

    def test_no_rate_limit_when_disabled(self, client):
        for _ in range(200):
            r = client.post("/api/estimate", json={"text": "x"})
        assert r.status_code != 429
