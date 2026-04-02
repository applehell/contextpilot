"""Tests for assembly router endpoints — templates, preview, compress, export."""
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


class TestPreviewContext:
    def test_preview_empty(self, client):
        r = client.post("/api/preview-context", params={"budget": 4000})
        assert r.status_code == 200
        data = r.json()
        assert data["input_count"] == 0
        assert data["blocks"] == []

    def test_preview_with_data(self, client):
        _seed(client, "prev/a", "some preview content here")
        _seed(client, "prev/b", "more content")
        r = client.post("/api/preview-context", params={"budget": 8000})
        assert r.status_code == 200
        data = r.json()
        assert data["input_count"] >= 2
        assert data["block_count"] >= 1


class TestTestCompress:
    def test_compress_bullet_extract(self, client):
        r = client.post("/api/test-compress", json={
            "content": "This is a long paragraph about various topics. It covers many different aspects.",
            "compress_hint": "bullet_extract",
        })
        assert r.status_code == 200
        data = r.json()
        assert "original_tokens" in data
        assert "compressed_tokens" in data

    def test_compress_code_compact(self, client):
        code = """def hello():
    # This is a comment
    print("Hello World")

def goodbye():
    # Another comment
    print("Goodbye")
"""
        r = client.post("/api/test-compress", json={
            "content": code,
            "compress_hint": "code_compact",
        })
        assert r.status_code == 200
        assert "compressed_content" in r.json()

    def test_compress_unknown(self, client):
        r = client.post("/api/test-compress", json={
            "content": "hello",
            "compress_hint": "nonexistent_compressor",
        })
        assert r.status_code == 200
        assert "error" in r.json()


class TestTemplates:
    def test_list_templates_empty(self, client):
        r = client.get("/api/templates")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_save_template(self, client):
        r = client.post("/api/templates", json={
            "name": "my-template",
            "description": "Test template",
            "tag_filter": ["test"],
            "key_filter": "",
            "budget": 4000,
        })
        assert r.status_code == 201
        assert r.json()["status"] == "saved"

    def test_save_template_no_name(self, client):
        r = client.post("/api/templates", json={
            "description": "No name",
            "budget": 4000,
        })
        assert r.status_code == 400

    def test_save_template_invalid_budget(self, client):
        r = client.post("/api/templates", json={
            "name": "bad-budget",
            "budget": -1,
        })
        assert r.status_code == 400

    def test_save_template_invalid_json(self, client):
        r = client.post("/api/templates", content="bad",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_delete_template(self, client):
        client.post("/api/templates", json={
            "name": "delete-me",
            "budget": 4000,
        })
        r = client.delete("/api/templates/delete-me")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_delete_nonexistent_template(self, client):
        r = client.delete("/api/templates/nonexistent")
        assert r.status_code == 404


class TestAssembleTemplate:
    def test_assemble_template(self, client):
        _seed(client, "tpl/a", "template content a", ["tpltest"])
        _seed(client, "tpl/b", "template content b", ["tpltest"])
        client.post("/api/templates", json={
            "name": "test-tpl",
            "tag_filter": ["tpltest"],
            "budget": 8000,
        })
        r = client.post("/api/templates/test-tpl/assemble")
        assert r.status_code == 200
        data = r.json()
        assert data["template"] == "test-tpl"
        assert data["total_matching"] >= 2
        assert "blocks" in data

    def test_assemble_template_with_key_filter(self, client):
        _seed(client, "filtered/x", "x content", ["any"])
        _seed(client, "other/y", "y content", ["any"])
        client.post("/api/templates", json={
            "name": "key-filter-tpl",
            "key_filter": "filtered/",
            "budget": 4000,
        })
        r = client.post("/api/templates/key-filter-tpl/assemble")
        assert r.status_code == 200
        data = r.json()
        assert data["total_matching"] >= 1

    def test_assemble_nonexistent_template(self, client):
        r = client.post("/api/templates/nonexistent/assemble")
        assert r.status_code == 404


class TestSuggestTemplates:
    def test_suggest_empty(self, client):
        r = client.get("/api/templates/suggest")
        assert r.status_code == 200
        assert r.json()["suggestions"] == []

    def test_suggest_with_data(self, client):
        for i in range(12):
            _seed(client, f"proj/item{i}", f"content {i}", ["project"])
        r = client.get("/api/templates/suggest")
        data = r.json()
        assert len(data["suggestions"]) >= 1


class TestExportClaudeMd:
    def test_export_all(self, client):
        _seed(client, "export/a", "export content", ["export"])
        r = client.get("/api/export-claude-md")
        assert r.status_code == 200
        data = r.json()
        assert "content" in data
        assert data["memory_count"] >= 1
        assert "# Context Pilot Export" in data["content"]

    def test_export_by_tags(self, client):
        _seed(client, "exp/tagged", "tagged", ["special"])
        _seed(client, "exp/other", "other", ["normal"])
        r = client.get("/api/export-claude-md", params={"tags": "special"})
        data = r.json()
        assert data["memory_count"] >= 1

    def test_export_by_key_prefix(self, client):
        _seed(client, "prefix/a", "a")
        _seed(client, "other/b", "b")
        r = client.get("/api/export-claude-md", params={"key_prefix": "prefix/"})
        data = r.json()
        assert data["memory_count"] >= 1


class TestExportMarkdown:
    def test_export_markdown(self, client):
        _seed(client, "md/a", "markdown content", ["mdtag"])
        r = client.get("/api/export-markdown")
        assert r.status_code == 200
        data = r.json()
        assert "content" in data
        assert data["memory_count"] >= 1
        assert "Knowledge Export" in data["content"]

    def test_export_markdown_by_tags(self, client):
        _seed(client, "md/tagged", "tagged", ["mdspecial"])
        r = client.get("/api/export-markdown", params={"tags": "mdspecial"})
        data = r.json()
        assert data["memory_count"] >= 1

    def test_export_markdown_by_prefix(self, client):
        _seed(client, "mdprefix/x", "x")
        r = client.get("/api/export-markdown", params={"key_prefix": "mdprefix/"})
        data = r.json()
        assert data["memory_count"] >= 1


class TestAssembleInvalidPriority:
    def test_assemble_invalid_priority(self, client):
        blocks = [{"content": "hello", "priority": "invalid_priority"}]
        r = client.post("/api/assemble", json={"blocks": blocks, "budget": 4000})
        assert r.status_code == 400
