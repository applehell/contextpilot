"""Tests for knowledge graph, relations, and dependency detection endpoints."""
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


class TestKnowledgeGraph:
    def test_empty_graph(self, client):
        r = client.get("/api/knowledge-graph")
        assert r.status_code == 200
        data = r.json()
        assert "nodes" in data
        assert "edges" in data
        assert "stats" in data
        assert data["stats"]["total_memories"] == 0

    def test_graph_with_memories(self, client):
        _seed(client, "project/a", "content a", ["shared"])
        _seed(client, "project/b", "content b", ["shared"])
        _seed(client, "other/c", "content c", ["shared"])
        r = client.get("/api/knowledge-graph")
        data = r.json()
        assert data["stats"]["total_memories"] == 3
        assert len(data["nodes"]) == 3

    def test_graph_groups(self, client):
        _seed(client, "cat/sub/a", "a", ["test"])
        _seed(client, "cat/sub/b", "b", ["test"])
        r = client.get("/api/knowledge-graph")
        data = r.json()
        assert "groups" in data

    def test_graph_edges_from_tags(self, client):
        _seed(client, "alpha/x", "x content", ["link"])
        _seed(client, "beta/y", "y content", ["link"])
        r = client.get("/api/knowledge-graph")
        data = r.json()
        assert data["stats"]["total_edges"] >= 1

    def test_graph_preamble_label(self, client):
        _seed(client, "ns/_preamble", "preamble text")
        r = client.get("/api/knowledge-graph")
        nodes = r.json()["nodes"]
        preamble_nodes = [n for n in nodes if n["id"] == "ns/_preamble"]
        assert len(preamble_nodes) == 1
        assert preamble_nodes[0]["label"] == "(preamble)"

    def test_graph_single_part_key(self, client):
        _seed(client, "standalone", "value", ["tag1"])
        r = client.get("/api/knowledge-graph")
        nodes = r.json()["nodes"]
        standalone = [n for n in nodes if n["id"] == "standalone"]
        assert len(standalone) == 1
        assert standalone[0]["group"] == "standalone"


class TestDependencyDetection:
    def test_detect_dependencies(self, client):
        _seed(client, "mod/a", "This module imports from mod/b")
        _seed(client, "mod/b", "Core module content")
        r = client.post("/api/dependencies/detect")
        assert r.status_code == 200
        data = r.json()
        assert "detected" in data
        assert "added" in data
        assert "cleared" in data


class TestRelations:
    def test_get_relations_empty(self, client):
        _seed(client, "rel/orphan", "lonely")
        r = client.get("/api/relations/rel/orphan")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_add_relation(self, client):
        _seed(client, "rel/a", "a")
        _seed(client, "rel/b", "b")
        r = client.post("/api/relations", json={
            "source_key": "rel/a",
            "target_key": "rel/b",
            "relation_type": "references",
        })
        assert r.status_code == 201
        data = r.json()
        assert data["source_key"] == "rel/a"
        assert data["target_key"] == "rel/b"

    def test_add_relation_missing_keys(self, client):
        r = client.post("/api/relations", json={
            "source_key": "",
            "target_key": "rel/b",
        })
        assert r.status_code == 400

    def test_add_relation_invalid_json(self, client):
        r = client.post("/api/relations", content="bad json",
                        headers={"Content-Type": "application/json"})
        assert r.status_code == 400

    def test_add_duplicate_relation(self, client):
        _seed(client, "dup/a", "a")
        _seed(client, "dup/b", "b")
        client.post("/api/relations", json={
            "source_key": "dup/a",
            "target_key": "dup/b",
        })
        r = client.post("/api/relations", json={
            "source_key": "dup/a",
            "target_key": "dup/b",
        })
        assert r.status_code == 409

    def test_get_relations_after_add(self, client):
        _seed(client, "link/a", "a")
        _seed(client, "link/b", "b")
        client.post("/api/relations", json={
            "source_key": "link/a",
            "target_key": "link/b",
        })
        r = client.get("/api/relations/link/a")
        assert r.status_code == 200
        rels = r.json()
        assert len(rels) >= 1

    def test_remove_relation(self, client):
        _seed(client, "rm/a", "a")
        _seed(client, "rm/b", "b")
        r = client.post("/api/relations", json={
            "source_key": "rm/a",
            "target_key": "rm/b",
        })
        rel_id = r.json()["id"]
        r = client.delete(f"/api/relations/{rel_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

    def test_remove_nonexistent_relation(self, client):
        r = client.delete("/api/relations/99999")
        assert r.status_code == 404

    def test_graph_includes_relations(self, client):
        _seed(client, "grel/a", "a", ["t1"])
        _seed(client, "grel/b", "b", ["t2"])
        client.post("/api/relations", json={
            "source_key": "grel/a",
            "target_key": "grel/b",
            "relation_type": "references",
        })
        r = client.get("/api/knowledge-graph")
        data = r.json()
        ref_edges = [e for e in data["edges"] if "references" in e.get("title", "")]
        assert len(ref_edges) >= 1
