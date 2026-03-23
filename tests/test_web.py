"""Tests for the Context Pilot web API endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.storage.db import Database
from src.web.app import create_app


@pytest.fixture
def client():
    """Create a test client with an in-memory database."""
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


class TestEstimate:
    def test_estimate_tokens(self, client):
        r = client.post("/api/estimate", json={"text": "hello world"})
        assert r.status_code == 200
        data = r.json()
        assert "tokens" in data
        assert data["tokens"] > 0

    def test_estimate_empty(self, client):
        r = client.post("/api/estimate", json={"text": ""})
        assert r.status_code == 200
        assert r.json()["tokens"] == 0


class TestAssemble:
    def test_assemble_basic(self, client):
        blocks = [
            {"content": "Hello world", "priority": "high"},
            {"content": "Some context here", "priority": "medium"},
        ]
        r = client.post("/api/assemble", json={"blocks": blocks, "budget": 4000})
        assert r.status_code == 200
        data = r.json()
        assert data["budget"] == 4000
        assert data["block_count"] == 2
        assert data["used_tokens"] > 0
        assert len(data["blocks"]) == 2
        assert "assembly_id" in data

    def test_assemble_drops_low_priority(self, client):
        blocks = [
            {"content": "A " * 500, "priority": "high"},
            {"content": "B " * 500, "priority": "low"},
        ]
        r = client.post("/api/assemble", json={"blocks": blocks, "budget": 100})
        data = r.json()
        assert data["dropped_count"] >= 1

    def test_assemble_with_compress_hint(self, client):
        blocks = [
            {"content": "This is a detailed paragraph about something.", "priority": "medium", "compress_hint": "bullet_extract"},
        ]
        r = client.post("/api/assemble", json={"blocks": blocks, "budget": 4000})
        assert r.status_code == 200
        assert r.json()["block_count"] == 1


class TestProjects:
    def test_list_empty(self, client):
        r = client.get("/api/projects")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_and_list(self, client):
        r = client.post("/api/projects", json={"name": "test-proj", "description": "A test"})
        assert r.status_code == 201
        assert r.json()["name"] == "test-proj"

        r = client.get("/api/projects")
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "test-proj"

    def test_create_duplicate(self, client):
        client.post("/api/projects", json={"name": "dup"})
        r = client.post("/api/projects", json={"name": "dup"})
        assert r.status_code == 409

    def test_get_project(self, client):
        client.post("/api/projects", json={"name": "myproj", "description": "desc"})
        r = client.get("/api/projects/myproj")
        assert r.status_code == 200
        data = r.json()
        assert data["meta"]["name"] == "myproj"
        assert data["meta"]["description"] == "desc"
        assert data["contexts"] == []

    def test_get_not_found(self, client):
        r = client.get("/api/projects/nonexistent")
        assert r.status_code == 404

    def test_delete_project(self, client):
        client.post("/api/projects", json={"name": "to-delete"})
        r = client.delete("/api/projects/to-delete")
        assert r.status_code == 200

        r = client.get("/api/projects")
        assert len(r.json()) == 0

    def test_delete_not_found(self, client):
        r = client.delete("/api/projects/nope")
        assert r.status_code == 404

    def test_add_context(self, client):
        client.post("/api/projects", json={"name": "ctx-proj"})
        r = client.post("/api/projects/ctx-proj/contexts", json={"name": "default"})
        assert r.status_code == 201

        r = client.get("/api/projects/ctx-proj")
        assert len(r.json()["contexts"]) == 1
        assert r.json()["contexts"][0]["name"] == "default"

    def test_add_context_duplicate(self, client):
        client.post("/api/projects", json={"name": "ctx-dup"})
        client.post("/api/projects/ctx-dup/contexts", json={"name": "main"})
        r = client.post("/api/projects/ctx-dup/contexts", json={"name": "main"})
        assert r.status_code == 409


class TestMemories:
    def test_list_empty(self, client):
        r = client.get("/api/memories")
        assert r.status_code == 200
        assert r.json() == []

    def test_set_and_get(self, client):
        r = client.post("/api/memories", json={"key": "greeting", "value": "hello", "tags": ["test"]})
        assert r.status_code == 201

        r = client.get("/api/memories/greeting")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "greeting"
        assert data["value"] == "hello"
        assert data["tags"] == ["test"]

    def test_get_not_found(self, client):
        r = client.get("/api/memories/nonexistent")
        assert r.status_code == 404

    def test_update_memory(self, client):
        client.post("/api/memories", json={"key": "k", "value": "v1"})
        client.post("/api/memories", json={"key": "k", "value": "v2"})
        r = client.get("/api/memories/k")
        assert r.json()["value"] == "v2"

    def test_delete(self, client):
        client.post("/api/memories", json={"key": "del-me", "value": "bye"})
        r = client.delete("/api/memories/del-me")
        assert r.status_code == 200

        r = client.get("/api/memories/del-me")
        assert r.status_code == 404

    def test_delete_not_found(self, client):
        r = client.delete("/api/memories/nope")
        assert r.status_code == 404

    def test_list_multiple(self, client):
        client.post("/api/memories", json={"key": "a", "value": "1"})
        client.post("/api/memories", json={"key": "b", "value": "2"})
        r = client.get("/api/memories")
        assert len(r.json()) == 2

    def test_search(self, client):
        client.post("/api/memories", json={"key": "python-tip", "value": "use list comprehensions"})
        client.post("/api/memories", json={"key": "js-tip", "value": "use arrow functions"})
        r = client.get("/api/memories/search?q=python")
        assert r.status_code == 200
        results = r.json()
        assert len(results) >= 1
        assert any(m["key"] == "python-tip" for m in results)

    def test_search_by_tags(self, client):
        client.post("/api/memories", json={"key": "tagged", "value": "val", "tags": ["important"]})
        client.post("/api/memories", json={"key": "untagged", "value": "val"})
        r = client.get("/api/memories/search?tags=important")
        results = r.json()
        assert len(results) == 1
        assert results[0]["key"] == "tagged"


class TestFeedback:
    def test_submit_feedback(self, client):
        r = client.post("/api/feedback", json={
            "assembly_id": "test123",
            "block_content": "hello world",
            "helpful": True,
        })
        assert r.status_code == 200
        assert r.json()["status"] == "recorded"
        assert "block_hash" in r.json()


class TestDashboard:
    def test_dashboard_empty(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        d = r.json()
        assert d["memory_count"] == 0
        assert d["memory_tokens"] == 0
        assert d["tag_count"] == 0
        assert d["skill_total"] >= 0
        assert d["skill_alive"] >= 0
        assert isinstance(d["skills"], list)
        assert isinstance(d["activity"], list)

    def test_dashboard_with_memories(self, client):
        client.post("/api/memories", json={"key": "a", "value": "hello world", "tags": ["test"]})
        client.post("/api/memories", json={"key": "b", "value": "foo bar"})
        r = client.get("/api/dashboard")
        d = r.json()
        assert d["memory_count"] == 2
        assert d["memory_tokens"] > 0
        assert d["tag_count"] == 1


class TestSkills:
    def test_list_skills_empty(self, client):
        r = client.get("/api/skills")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestPreviewContext:
    def test_preview_empty(self, client):
        r = client.post("/api/preview-context?budget=4000")
        assert r.status_code == 200
        d = r.json()
        assert d["block_count"] == 0
        assert d["budget"] == 4000

    def test_preview_with_memories(self, client):
        client.post("/api/memories", json={"key": "code", "value": "```python\ndef hello():\n    print('hi')\n```"})
        client.post("/api/memories", json={"key": "note", "value": "This is a short note."})
        r = client.post("/api/preview-context?budget=8000")
        assert r.status_code == 200
        d = r.json()
        assert d["block_count"] >= 1
        assert d["used_tokens"] > 0
        assert d["input_count"] == 2


class TestTestCompress:
    def test_compress_bullet(self, client):
        r = client.post("/api/test-compress", json={
            "content": "This is the first sentence. This is the second. And a third one here.",
            "compress_hint": "bullet_extract",
        })
        assert r.status_code == 200
        d = r.json()
        assert "compressed_content" in d
        assert d["original_tokens"] > 0
        assert d["compressed_tokens"] > 0
        assert "savings_pct" in d

    def test_compress_unknown(self, client):
        r = client.post("/api/test-compress", json={
            "content": "test",
            "compress_hint": "nonexistent",
        })
        assert r.status_code == 200
        assert "error" in r.json()

    def test_compress_code_compact(self, client):
        code = "def hello():\n    # A comment\n    print('world')\n\ndef bye():\n    # Another\n    pass"
        r = client.post("/api/test-compress", json={
            "content": code,
            "compress_hint": "code_compact",
        })
        assert r.status_code == 200
        d = r.json()
        assert d["compressed_tokens"] <= d["original_tokens"]


class TestMemoryTags:
    def test_tags_empty(self, client):
        r = client.get("/api/memory-tags")
        assert r.status_code == 200
        assert r.json() == []

    def test_tags_after_adding(self, client):
        client.post("/api/memories", json={"key": "a", "value": "v", "tags": ["alpha", "beta"]})
        client.post("/api/memories", json={"key": "b", "value": "v", "tags": ["beta", "gamma"]})
        r = client.get("/api/memory-tags")
        tags = r.json()
        assert "alpha" in tags
        assert "beta" in tags
        assert "gamma" in tags


class TestMemoryActivity:
    def test_activity_empty(self, client):
        r = client.get("/api/memory-activity")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


class TestKnowledgeGraph:
    def test_graph_empty(self, client):
        r = client.get("/api/knowledge-graph")
        assert r.status_code == 200
        d = r.json()
        assert d["nodes"] == []
        assert d["edges"] == []
        assert d["stats"]["total_memories"] == 0

    def test_graph_with_memories(self, client):
        client.post("/api/memories", json={"key": "skill/evcc/api", "value": "curl http://...", "tags": ["evcc", "skill"]})
        client.post("/api/memories", json={"key": "skill/evcc/modes", "value": "PV, Min+PV", "tags": ["evcc", "skill"]})
        client.post("/api/memories", json={"key": "skill/ha/api", "value": "REST API", "tags": ["ha", "skill"]})
        r = client.get("/api/knowledge-graph")
        d = r.json()
        assert d["stats"]["total_memories"] == 3
        assert d["stats"]["total_groups"] == 2
        assert len(d["nodes"]) == 3
        # evcc nodes share group, ha is different → cross-group edges via "skill" tag
        # but "skill" tag has 3 entries which is <= 20, so edges exist
        assert len(d["groups"]) == 2


class TestMemoryEdit:
    def test_update_memory(self, client):
        client.post("/api/memories", json={"key": "k", "value": "old", "tags": ["a"]})
        r = client.put("/api/memories/k", json={"key": "k", "value": "new", "tags": ["b"]})
        assert r.status_code == 200
        assert r.json()["status"] == "updated"
        r2 = client.get("/api/memories/k")
        assert r2.json()["value"] == "new"
        assert r2.json()["tags"] == ["b"]

    def test_update_not_found(self, client):
        r = client.put("/api/memories/nope", json={"key": "nope", "value": "x"})
        assert r.status_code == 404

    def test_bulk_delete(self, client):
        client.post("/api/memories", json={"key": "a", "value": "1"})
        client.post("/api/memories", json={"key": "b", "value": "2"})
        client.post("/api/memories", json={"key": "c", "value": "3"})
        r = client.post("/api/memories/bulk-delete", json=["a", "c"])
        assert r.status_code == 200
        assert r.json()["count"] == 2
        r2 = client.get("/api/memories")
        assert len(r2.json()) == 1
        assert r2.json()[0]["key"] == "b"

    def test_export_all(self, client):
        client.post("/api/memories", json={"key": "x", "value": "val", "tags": ["t"]})
        r = client.get("/api/export-memories")
        assert r.status_code == 200
        d = r.json()
        assert len(d["memories"]) == 1

    def test_export_by_tag(self, client):
        client.post("/api/memories", json={"key": "a", "value": "v", "tags": ["alpha"]})
        client.post("/api/memories", json={"key": "b", "value": "v", "tags": ["beta"]})
        r = client.get("/api/export-memories?tag=alpha")
        assert len(r.json()["memories"]) == 1


class TestImport:
    def test_import_claude_md(self, client):
        content = b"# My Instructions\n\n## Section One\nDo this.\n\n## Section Two\nDo that."
        r = client.post("/api/import/claude-md", files={"file": ("CLAUDE.md", content, "text/markdown")})
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "imported"
        assert d["count"] >= 1

        # Memories should exist now
        r2 = client.get("/api/memories")
        assert len(r2.json()) >= 1

    def test_import_copilot_md(self, client):
        content = b"# Copilot Instructions\n\n## Coding Style\nUse TypeScript.\n\n## Testing\nWrite tests."
        r = client.post("/api/import/copilot-md", files={"file": ("copilot-instructions.md", content, "text/markdown")})
        assert r.status_code == 200
        d = r.json()
        assert d["status"] == "imported"
        assert d["count"] >= 1


class TestSensitivity:
    def test_sensitivity_empty(self, client):
        r = client.get("/api/sensitivity")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] == 0
        assert d["sensitive"] == 0

    def test_sensitivity_with_secrets(self, client):
        client.post("/api/memories", json={"key": "creds", "value": 'password = "SuperSecret123"'})
        client.post("/api/memories", json={"key": "clean", "value": "Just a note."})
        r = client.get("/api/sensitivity")
        d = r.json()
        assert d["total"] == 2
        assert d["sensitive"] >= 1
        creds_entry = next(m for m in d["memories"] if m["key"] == "creds")
        assert creds_entry["severity"] in ("critical", "high")

    def test_redacted_view(self, client):
        client.post("/api/memories", json={"key": "secret", "value": 'api_key: ABCDEF1234567890ABCDEF'})
        r = client.get("/api/redacted?key=secret")
        assert r.status_code == 200
        d = r.json()
        assert "ABCDEF1234567890ABCDEF" not in d["value"]
        assert d["severity"] in ("high", "critical")

    def test_redacted_not_found(self, client):
        r = client.get("/api/redacted?key=nope")
        assert r.status_code == 404

    def test_redacted_slash_key(self, client):
        client.post("/api/memories", json={"key": "skill/test/creds", "value": 'password = "abc123"'})
        r = client.get("/api/redacted?key=skill/test/creds")
        assert r.status_code == 200
        assert "abc123" not in r.json()["value"]


class TestFrontend:
    def test_index_page(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "Context Pilot" in r.text
        assert "text/html" in r.headers["content-type"]

    def test_index_has_dashboard(self, client):
        r = client.get("/")
        assert "Dashboard" in r.text
        assert "Knowledge Graph" in r.text
        assert "Skills" in r.text
