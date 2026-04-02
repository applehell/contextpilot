"""Tests for event router endpoints — events list, stats, SSE stream."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


class TestEvents:
    def test_get_events(self, client):
        r = client.get("/api/events", params={"limit": 10})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_events_with_category(self, client):
        # Trigger an event first
        client.post("/api/memories", json={"key": "evt/test", "value": "hello", "tags": ["test"]})
        r = client.get("/api/events", params={"limit": 10, "category": "memory"})
        assert r.status_code == 200

    def test_event_stats(self, client):
        r = client.get("/api/events/stats")
        assert r.status_code == 200
        assert isinstance(r.json(), dict)
