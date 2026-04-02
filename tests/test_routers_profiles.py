"""Tests for profile router endpoints — list, create, rename, etc.

Note: Profile operations that create/switch/delete real filesystem profiles are
tested carefully to avoid SQLite threading race conditions with the background
indexing thread. Tests that would reinitialize the DB are avoided.
"""
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


def _seed(client, key="test/mem", value="hello", tags=None):
    client.post("/api/memories", json={"key": key, "value": value, "tags": tags or ["test"]})


class TestProfileList:
    def test_list_profiles(self, client):
        r = client.get("/api/profiles")
        assert r.status_code == 200
        data = r.json()
        assert "active" in data
        assert "profiles" in data
        assert len(data["profiles"]) >= 1
        for p in data["profiles"]:
            assert "id" in p
            assert "name" in p
            assert "is_active" in p


class TestProfileCreateValidation:
    def test_create_empty_name(self, client):
        r = client.post("/api/profiles", json={"name": "", "description": "Empty"})
        assert r.status_code == 400

    def test_create_whitespace_name(self, client):
        r = client.post("/api/profiles", json={"name": "   ", "description": "Whitespace"})
        assert r.status_code == 400


class TestProfileSwitchValidation:
    def test_switch_nonexistent(self, client):
        r = client.post("/api/profiles/nonexistent_id/switch")
        assert r.status_code == 404


class TestProfileRename:
    def test_rename_nonexistent(self, client):
        r = client.put("/api/profiles/bad_id_xyz", params={"new_name": "x"})
        assert r.status_code == 400


class TestProfileDuplicate:
    def test_duplicate_nonexistent(self, client):
        r = client.post("/api/profiles/bad_id_xyz/duplicate", params={"new_name": "x"})
        assert r.status_code == 400


class TestProfileDelete:
    def test_delete_nonexistent(self, client):
        r = client.delete("/api/profiles/bad_id_xyz")
        assert r.status_code == 400


class TestProfileTags:
    def test_get_profile_tags(self, client):
        _seed(client, "tags/a", "a", ["alpha"])
        profiles = client.get("/api/profiles").json()
        active_id = profiles["active"]
        r = client.get(f"/api/profiles/{active_id}/tags")
        assert r.status_code == 200

    def test_get_profile_tags_nonexistent(self, client):
        r = client.get("/api/profiles/bad_id_xyz/tags")
        assert r.status_code == 404


class TestProfileImportMemories:
    def test_import_nonexistent_source(self, client):
        profiles = client.get("/api/profiles").json()
        active_id = profiles["active"]
        r = client.post(f"/api/profiles/{active_id}/import-memories", json={
            "source_id": "nonexistent_id_xyz",
        })
        assert r.status_code == 404


class TestProfilePreviewImport:
    def test_preview_nonexistent(self, client):
        profiles = client.get("/api/profiles").json()
        active_id = profiles["active"]
        r = client.post(f"/api/profiles/{active_id}/preview-import", json={
            "source_id": "bad_id_xyz",
        })
        assert r.status_code == 404


class TestProfileExport:
    def test_export_profile(self, client):
        _seed(client)
        profiles = client.get("/api/profiles").json()
        active_id = profiles["active"]
        r = client.get(f"/api/profiles/{active_id}/export")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/zip"

    def test_export_nonexistent(self, client):
        r = client.get("/api/profiles/bad_id_xyz/export")
        assert r.status_code == 404
