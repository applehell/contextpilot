"""Tests for inbound webhook endpoint (QW5)."""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.web.app import create_app


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


class TestInboundWebhook:
    def test_success_with_valid_token(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "secret123"}):
            r = client.post("/api/inbound/secret123", json={
                "key": "webhook/test",
                "value": "Hello from webhook",
                "tags": ["external"],
            })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["key"] == "webhook/test"

    def test_memory_actually_stored(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "tok"}):
            client.post("/api/inbound/tok", json={
                "key": "webhook/stored",
                "value": "Stored value",
                "tags": ["wh"],
            })
        # Verify via memory API
        r = client.get("/api/memories/webhook/stored")
        assert r.status_code == 200
        data = r.json()
        assert data["value"] == "Stored value"

    def test_403_wrong_token(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "secret123"}):
            r = client.post("/api/inbound/wrongtoken", json={
                "key": "test", "value": "val", "tags": [],
            })
        assert r.status_code == 403
        assert "Invalid token" in r.json()["detail"]

    def test_403_when_env_not_set(self, client):
        with patch.dict(os.environ, {}, clear=False):
            # Remove the env var if it exists
            env = os.environ.copy()
            env.pop("CONTEXTPILOT_INBOUND_TOKEN", None)
            with patch.dict(os.environ, env, clear=True):
                r = client.post("/api/inbound/anytoken", json={
                    "key": "test", "value": "val", "tags": [],
                })
        assert r.status_code == 403
        assert "not configured" in r.json()["detail"]

    def test_400_missing_key(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "tok"}):
            r = client.post("/api/inbound/tok", json={
                "key": "",
                "value": "some value",
                "tags": [],
            })
        assert r.status_code == 400

    def test_400_missing_value(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "tok"}):
            r = client.post("/api/inbound/tok", json={
                "key": "test/key",
                "value": "",
                "tags": [],
            })
        assert r.status_code == 400

    def test_default_empty_tags(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "tok"}):
            r = client.post("/api/inbound/tok", json={
                "key": "webhook/notags",
                "value": "No tags provided",
            })
        assert r.status_code == 200

    def test_422_invalid_body(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "tok"}):
            r = client.post("/api/inbound/tok", json={"garbage": True})
        assert r.status_code == 422
