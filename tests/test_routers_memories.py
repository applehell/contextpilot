"""Tests for memory router endpoints — TTL, pinning, trash, bulk ops, tags, presets, sensitivity."""
from __future__ import annotations

import time
import json
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


class TestExpiringMemories:
    def test_expiring_no_ttl(self, client):
        r = client.get("/api/memories/expiring", params={"hours": 24})
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_expiring_with_ttl(self, client):
        client.post("/api/memories", json={
            "key": "ttl/soon",
            "value": "expiring soon",
            "tags": ["ttl"],
            "ttl_seconds": 3600,
        })
        r = client.get("/api/memories/expiring", params={"hours": 2})
        assert r.status_code == 200


class TestTTLStats:
    def test_ttl_stats(self, client):
        r = client.get("/api/memories/ttl-stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_with_ttl" in data
        assert "expired" in data
        assert "expiring_24h" in data
        assert "expiring_7d" in data

    def test_ttl_stats_with_data(self, client):
        client.post("/api/memories", json={
            "key": "ttlstat/a",
            "value": "val",
            "ttl_seconds": 7200,
        })
        r = client.get("/api/memories/ttl-stats")
        data = r.json()
        assert data["total_with_ttl"] >= 1


class TestCategoryStats:
    def test_category_stats(self, client):
        _seed(client)
        r = client.get("/api/memories/category-stats")
        assert r.status_code == 200


class TestRelatedMemories:
    def test_related_no_relations(self, client):
        _seed(client, "rel/lone", "lonely")
        r = client.get("/api/memories/rel/lone/related")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "rel/lone"
        assert data["count"] == 0

    def test_related_with_relations(self, client):
        _seed(client, "rel/a", "a")
        _seed(client, "rel/b", "b")
        client.post("/api/relations", json={
            "source_key": "rel/a",
            "target_key": "rel/b",
        })
        r = client.get("/api/memories/rel/a/related")
        data = r.json()
        assert data["count"] >= 1
        assert data["related"][0]["key"] == "rel/b"

    def test_related_deleted_target(self, client):
        _seed(client, "rel/src", "source")
        _seed(client, "rel/tgt", "target")
        client.post("/api/relations", json={
            "source_key": "rel/src",
            "target_key": "rel/tgt",
        })
        client.delete("/api/memories/rel/tgt")
        r = client.get("/api/memories/rel/src/related")
        data = r.json()
        assert data["count"] >= 1
        deleted_item = [i for i in data["related"] if i["key"] == "rel/tgt"]
        assert len(deleted_item) == 1
        assert deleted_item[0]["value"] == "(deleted)"


class TestMemoryVersions:
    def test_versions_empty(self, client):
        _seed(client, "ver/test", "original")
        r = client.get("/api/memories/ver/test/versions")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_versions_after_update(self, client):
        _seed(client, "ver/upd", "original value")
        client.put("/api/memories/ver/upd", json={
            "key": "ver/upd",
            "value": "updated value",
            "tags": ["test"],
        })
        r = client.get("/api/memories/ver/upd/versions")
        versions = r.json()
        assert len(versions) >= 1
        assert versions[0]["value"] == "original value"


class TestMemoryTTL:
    def test_set_ttl(self, client):
        _seed(client, "ttl/set", "val")
        r = client.post("/api/memories/ttl/set/ttl", json={"ttl_seconds": 3600})
        assert r.status_code == 200
        assert r.json()["ttl_seconds"] == 3600

    def test_set_ttl_not_found(self, client):
        r = client.post("/api/memories/ttl/missing/ttl", json={"ttl_seconds": 3600})
        assert r.status_code == 404

    def test_set_ttl_invalid_json(self, client):
        _seed(client, "ttl/bad", "val")
        r = client.post("/api/memories/ttl/bad/ttl",
                        content="bad", headers={"Content-Type": "application/json"})
        assert r.status_code == 400


class TestCleanupExpired:
    def test_cleanup_expired(self, client):
        r = client.post("/api/memories/cleanup-expired")
        assert r.status_code == 200
        assert r.json()["status"] == "cleaned"


class TestSuggestTags:
    def test_suggest_tags(self, client):
        _seed(client, "suggest/a", "python programming code", ["python", "code"])
        _seed(client, "suggest/b", "python flask web", ["python", "web"])
        r = client.post("/api/memories/suggest-tags", json={
            "key": "new/mem",
            "value": "python programming",
        })
        assert r.status_code == 200
        data = r.json()
        assert "tags" in data

    def test_suggest_tags_empty(self, client):
        r = client.post("/api/memories/suggest-tags", json={
            "key": "",
            "value": "",
        })
        assert r.status_code == 200

    def test_suggest_tags_invalid_json(self, client):
        r = client.post("/api/memories/suggest-tags",
                        content="bad", headers={"Content-Type": "application/json"})
        assert r.status_code == 400


class TestPinning:
    def test_pin_memory(self, client):
        _seed(client, "pin/test", "pinme")
        r = client.post("/api/memories/pin/test/pin", params={"pinned": True})
        assert r.status_code == 200
        assert r.json()["pinned"] is True

    def test_unpin_memory(self, client):
        _seed(client, "pin/test2", "unpinme")
        client.post("/api/memories/pin/test2/pin", params={"pinned": True})
        r = client.post("/api/memories/pin/test2/pin", params={"pinned": False})
        assert r.status_code == 200
        assert r.json()["pinned"] is False

    def test_pin_nonexistent(self, client):
        r = client.post("/api/memories/nonexistent/pin", params={"pinned": True})
        assert r.status_code == 404


class TestTrash:
    def test_list_trash_empty(self, client):
        r = client.get("/api/trash")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_delete_to_trash_and_restore(self, client):
        _seed(client, "trash/test", "trashme")
        client.delete("/api/memories/trash/test")
        r = client.get("/api/trash")
        trash_keys = [t["key"] if isinstance(t, dict) else t for t in r.json()]
        assert any("trash/test" in str(t) for t in trash_keys)

        r = client.post("/api/trash/trash/test/restore")
        assert r.status_code == 200

    def test_restore_nonexistent(self, client):
        r = client.post("/api/trash/nonexistent/restore")
        assert r.status_code == 404

    def test_purge_single(self, client):
        _seed(client, "trash/purge", "purgeme")
        client.delete("/api/memories/trash/purge")
        r = client.delete("/api/trash/trash/purge")
        assert r.status_code == 200
        assert r.json()["status"] == "purged"

    def test_empty_trash(self, client):
        r = client.delete("/api/trash")
        assert r.status_code == 200
        assert r.json()["status"] == "emptied"


class TestBulkTagOperations:
    def test_bulk_tags_add(self, client):
        _seed(client, "bulk/a", "a", ["base"])
        _seed(client, "bulk/b", "b", ["base"])
        r = client.post("/api/memories/bulk-tags", json={
            "keys": ["bulk/a", "bulk/b"],
            "add": ["newtag"],
            "remove": [],
        })
        assert r.status_code == 200
        assert r.json()["updated"] == 2

    def test_bulk_tags_remove(self, client):
        _seed(client, "bulk/c", "c", ["removeme", "keep"])
        r = client.post("/api/memories/bulk-tags", json={
            "keys": ["bulk/c"],
            "add": [],
            "remove": ["removeme"],
        })
        assert r.status_code == 200
        assert r.json()["updated"] == 1

    def test_bulk_tags_invalid_json(self, client):
        r = client.post("/api/memories/bulk-tags",
                        content="bad", headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_bulk_tags_missing_key(self, client):
        r = client.post("/api/memories/bulk-tags", json={
            "keys": ["nonexistent/key"],
            "add": ["tag"],
            "remove": [],
        })
        assert r.status_code == 200
        assert r.json()["updated"] == 0


class TestMemoryPresets:
    def test_list_presets_empty(self, client):
        r = client.get("/api/memory-presets")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_save_preset(self, client):
        r = client.post("/api/memory-presets", json={
            "name": "my-preset",
            "key_prefix": "project/",
            "default_tags": ["project"],
            "description": "Project memories",
        })
        assert r.status_code == 201
        assert r.json()["status"] == "saved"

    def test_save_preset_empty_name(self, client):
        r = client.post("/api/memory-presets", json={
            "name": "",
        })
        assert r.status_code == 400

    def test_save_preset_invalid_json(self, client):
        r = client.post("/api/memory-presets",
                        content="bad", headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_list_presets_after_save(self, client):
        client.post("/api/memory-presets", json={
            "name": "listed-preset",
            "key_prefix": "x/",
            "default_tags": ["x"],
        })
        r = client.get("/api/memory-presets")
        names = [p["name"] for p in r.json()]
        assert "listed-preset" in names

    def test_delete_preset(self, client):
        client.post("/api/memory-presets", json={
            "name": "delete-me",
            "key_prefix": "",
        })
        r = client.delete("/api/memory-presets/delete-me")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"


class TestSensitivity:
    def test_sensitivity_scan(self, client):
        _seed(client, "sens/normal", "just a normal text")
        r = client.get("/api/sensitivity", params={"page": 1, "page_size": 100})
        assert r.status_code == 200
        data = r.json()
        assert "total" in data
        assert "sensitive" in data
        assert "memories" in data

    def test_sensitivity_with_secret(self, client):
        _seed(client, "sens/secret", "password = s3cr3tP@ssw0rd! and API_KEY=sk-1234567890abcdef")
        r = client.get("/api/sensitivity")
        data = r.json()
        assert data["total"] >= 1


class TestRedacted:
    def test_redacted_memory(self, client):
        _seed(client, "redact/test", "some text with password=secret123")
        r = client.get("/api/redacted", params={"key": "redact/test"})
        assert r.status_code == 200
        data = r.json()
        assert "value" in data
        assert "severity" in data

    def test_redacted_not_found(self, client):
        r = client.get("/api/redacted", params={"key": "nonexistent/key"})
        assert r.status_code == 404


class TestExportMemories:
    def test_export_all(self, client):
        _seed(client)
        r = client.get("/api/export-memories")
        assert r.status_code == 200
        data = r.json()
        assert "memories" in data
        assert len(data["memories"]) >= 1

    def test_export_by_tag(self, client):
        _seed(client, "exp/a", "a", ["export-tag"])
        _seed(client, "exp/b", "b", ["other-tag"])
        r = client.get("/api/export-memories", params={"tag": "export-tag"})
        data = r.json()
        assert all(any("export-tag" in m.get("tags", []) for m in [m]) for m in data["memories"])


class TestMemoryActivity:
    def test_memory_activity(self, client):
        _seed(client, "act/test", "activity test")
        r = client.get("/api/memory-activity", params={"limit": 10})
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestFeedback:
    def test_submit_feedback(self, client):
        r = client.post("/api/feedback", json={
            "assembly_id": "test-assembly-123",
            "block_content": "some block content",
            "helpful": True,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "recorded"


class TestBulkDelete:
    def test_bulk_delete(self, client):
        _seed(client, "bd/a", "a")
        _seed(client, "bd/b", "b")
        r = client.post("/api/memories/bulk-delete", json=["bd/a", "bd/b"])
        assert r.status_code == 200
        assert r.json()["count"] == 2

    def test_bulk_delete_nonexistent(self, client):
        r = client.post("/api/memories/bulk-delete", json=["nonexistent/a"])
        assert r.status_code == 200
        assert r.json()["count"] == 0
