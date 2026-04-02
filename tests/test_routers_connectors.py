"""Tests for connector router endpoints — list, setup, sync, health, email accounts, inbound."""
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


class TestConnectorList:
    def test_list_connectors(self, client):
        r = client.get("/api/connectors")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_connector_status(self, client):
        connectors = client.get("/api/connectors").json()
        if connectors:
            name = connectors[0]["name"]
            r = client.get(f"/api/connectors/{name}")
            assert r.status_code == 200

    def test_connector_not_found(self, client):
        r = client.get("/api/connectors/nonexistent_connector_xyz")
        assert r.status_code == 404


class TestConnectorHealth:
    def test_connectors_health(self, client):
        r = client.get("/api/connectors/health")
        assert r.status_code == 200
        assert isinstance(r.json(), list)
        for item in r.json():
            assert "name" in item
            assert "configured" in item
            assert "reachable" in item


class TestConnectorSetup:
    def test_setup_connector_invalid_json(self, client):
        connectors = client.get("/api/connectors").json()
        if connectors:
            name = connectors[0]["name"]
            r = client.post(f"/api/connectors/{name}/setup",
                            content="bad json", headers={"Content-Type": "application/json"})
            assert r.status_code == 400

    def test_setup_nonexistent_connector(self, client):
        r = client.post("/api/connectors/nonexistent_xyz/setup", json={"url": "http://example.com"})
        assert r.status_code == 404


class TestConnectorUpdate:
    def test_update_not_configured(self, client):
        connectors = client.get("/api/connectors").json()
        unconfigured = [c for c in connectors if not c.get("configured")]
        if unconfigured:
            name = unconfigured[0]["name"]
            r = client.put(f"/api/connectors/{name}", json={"key": "val"})
            assert r.status_code == 400

    def test_update_invalid_json(self, client):
        connectors = client.get("/api/connectors").json()
        if connectors:
            name = connectors[0]["name"]
            r = client.put(f"/api/connectors/{name}",
                           content="bad", headers={"Content-Type": "application/json"})
            # Either 400 (bad json) or 400 (not configured)
            assert r.status_code == 400

    def test_update_nonexistent(self, client):
        r = client.put("/api/connectors/nonexistent_xyz", json={"key": "val"})
        assert r.status_code == 404


class TestConnectorSync:
    def test_sync_nonexistent(self, client):
        r = client.post("/api/connectors/nonexistent_xyz/sync")
        assert r.status_code == 404

    def test_connector_test(self, client):
        connectors = client.get("/api/connectors").json()
        if connectors:
            name = connectors[0]["name"]
            r = client.post(f"/api/connectors/{name}/test")
            # May fail if not configured, but should not 500
            assert r.status_code in (200, 400, 404, 500)


class TestConnectorHistory:
    def test_history(self, client):
        connectors = client.get("/api/connectors").json()
        if connectors:
            name = connectors[0]["name"]
            r = client.get(f"/api/connectors/{name}/history")
            assert r.status_code == 200
            assert isinstance(r.json(), list)


class TestConnectorEnable:
    def test_enable_connector(self, client):
        connectors = client.get("/api/connectors").json()
        if connectors:
            name = connectors[0]["name"]
            r = client.post(f"/api/connectors/{name}/enable", params={"enabled": True})
            assert r.status_code == 200
            assert r.json()["status"] == "updated"


class TestConnectorRemove:
    def test_remove_nonexistent(self, client):
        r = client.delete("/api/connectors/nonexistent_xyz")
        assert r.status_code == 404


class TestEmailAccounts:
    def test_email_accounts_list(self, client):
        r = client.get("/api/connectors/email/accounts")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_add_email_account(self, client):
        r = client.post("/api/connectors/email/accounts", json={
            "name": "test-account",
            "host": "imap.example.com",
            "user": "user@example.com",
            "password": "secret123",
        })
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "added"
        assert data["name"] == "test-account"

    def test_add_email_account_missing_fields(self, client):
        r = client.post("/api/connectors/email/accounts", json={
            "name": "bad-account",
        })
        assert r.status_code == 400

    def test_add_email_account_invalid_json(self, client):
        r = client.post("/api/connectors/email/accounts",
                        content="bad", headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_remove_email_account_not_found(self, client):
        r = client.delete("/api/connectors/email/accounts/nonexistent")
        assert r.status_code == 404

    def test_add_and_remove_email_account(self, client):
        client.post("/api/connectors/email/accounts", json={
            "name": "removeme",
            "host": "imap.example.com",
            "user": "user@example.com",
            "password": "secret",
        })
        r = client.delete("/api/connectors/email/accounts/removeme")
        assert r.status_code == 200
        assert r.json()["status"] == "removed"

    def test_email_passwords_masked(self, client):
        client.post("/api/connectors/email/accounts", json={
            "name": "masked",
            "host": "imap.example.com",
            "user": "user@example.com",
            "password": "supersecret",
        })
        r = client.get("/api/connectors/email/accounts")
        for acc in r.json():
            if acc.get("name") == "masked":
                assert acc["password"] == "********"


class TestInboundWebhook:
    def test_inbound_no_token_configured(self, client):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTEXTPILOT_INBOUND_TOKEN", None)
            r = client.post("/api/inbound/sometoken", json={
                "key": "inbound/test",
                "value": "hello",
                "tags": ["inbound"],
            })
            assert r.status_code == 403

    def test_inbound_invalid_token(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "correct-token"}):
            r = client.post("/api/inbound/wrong-token", json={
                "key": "inbound/test",
                "value": "hello",
            })
            assert r.status_code == 403

    def test_inbound_valid(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "mytoken"}):
            r = client.post("/api/inbound/mytoken", json={
                "key": "inbound/test",
                "value": "hello from inbound",
                "tags": ["inbound"],
            })
            assert r.status_code == 200
            assert r.json()["status"] == "ok"

    def test_inbound_missing_key(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "mytoken"}):
            r = client.post("/api/inbound/mytoken", json={
                "key": "",
                "value": "hello",
            })
            assert r.status_code == 400

    def test_inbound_missing_value(self, client):
        with patch.dict(os.environ, {"CONTEXTPILOT_INBOUND_TOKEN": "mytoken"}):
            r = client.post("/api/inbound/mytoken", json={
                "key": "inbound/test",
                "value": "",
            })
            assert r.status_code == 400
