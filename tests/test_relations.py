"""Tests for F8 — Memory Relations: RelationStore extensions, DependencyDetector fixes, API endpoint."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.storage.relations import RelationStore
from src.core.dependency_detector import detect_dependencies
from src.web.app import create_app


@pytest.fixture
def db():
    return Database(path=None)


@pytest.fixture
def store(db):
    return RelationStore(db)


@pytest.fixture
def mem_store(db):
    return MemoryStore(db)


@pytest.fixture
def client():
    app = create_app(db_path=None)
    with TestClient(app) as c:
        yield c


def _mem(key: str, value: str, tags: list | None = None) -> Memory:
    return Memory(key=key, value=value, tags=tags or [])


class TestGetRelatedKeys:
    def test_bidirectional_lookup(self, store) -> None:
        store.add("alpha", "beta", "related")
        store.add("gamma", "alpha", "depends_on")

        related = store.get_related_keys("alpha")
        assert "beta" in related
        assert "gamma" in related
        assert "alpha" not in related

    def test_source_only(self, store) -> None:
        store.add("a", "b", "ref")
        related = store.get_related_keys("a")
        assert related == ["b"]

    def test_target_only(self, store) -> None:
        store.add("a", "b", "ref")
        related = store.get_related_keys("b")
        assert related == ["a"]

    def test_no_relations(self, store) -> None:
        assert store.get_related_keys("nonexistent") == []

    def test_deduplication(self, store) -> None:
        store.add("a", "b", "ref")
        store.add("a", "b", "depends_on")
        related = store.get_related_keys("a")
        assert related == ["b"]


class TestGetGraph:
    def test_structure(self, store) -> None:
        store.add("a", "b", "related")
        store.add("b", "c", "depends_on")

        graph = store.get_graph()
        assert "nodes" in graph
        assert "edges" in graph
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2

    def test_node_format(self, store) -> None:
        store.add("x", "y", "ref")
        graph = store.get_graph()
        for node in graph["nodes"]:
            assert "id" in node
            assert "label" in node
            assert node["id"] == node["label"]

    def test_edge_format(self, store) -> None:
        store.add("x", "y", "ref")
        graph = store.get_graph()
        edge = graph["edges"][0]
        assert edge["from"] == "x"
        assert edge["to"] == "y"
        assert edge["type"] == "ref"

    def test_empty_graph(self, store) -> None:
        graph = store.get_graph()
        assert graph == {"nodes": [], "edges": []}

    def test_limit(self, store) -> None:
        for i in range(10):
            store.add(f"a{i}", f"b{i}", "ref")
        graph = store.get_graph(limit=3)
        assert len(graph["edges"]) == 3


class TestDependencyDetectorWordBoundary:
    def test_no_match_substring(self) -> None:
        """'ip' should NOT match inside 'script' because of word boundaries."""
        mems = [
            _mem("ip", "IP address config"),
            _mem("scripts", "This script handles deployment"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert refs == []

    def test_short_key_filtered(self) -> None:
        """Keys shorter than 4 chars should be skipped in reference detection."""
        mems = [
            _mem("id", "Identifier"),
            _mem("config", "The id is used here"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert refs == []

    def test_exact_word_boundary_match(self) -> None:
        """Keys >= 4 chars that appear as whole words should still match."""
        mems = [
            _mem("server-config", "The server runs at 192.168.1.78"),
            _mem("deployment", "See server-config for details"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert len(refs) == 1
        assert refs[0]["target_key"] == "server-config"

    def test_no_partial_match_long_key(self) -> None:
        """Even long keys should not match as substrings without word boundaries."""
        mems = [
            _mem("port", "Port 8080"),
            _mem("transport", "HTTP transport layer"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert refs == []

    def test_3_char_key_skipped(self) -> None:
        mems = [
            _mem("dns", "DNS server"),
            _mem("network", "Configure dns settings here"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert refs == []

    def test_4_char_key_included(self) -> None:
        mems = [
            _mem("evcc", "EV charging controller"),
            _mem("solar", "PV surplus goes to evcc for car charging"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert len(refs) == 1
        assert refs[0]["target_key"] == "evcc"


class TestRelatedEndpoint:
    def test_get_related_memories(self, client) -> None:
        client.post("/api/memories", json={"key": "alpha", "value": "First memory"})
        client.post("/api/memories", json={"key": "beta", "value": "Second memory"})
        client.post("/api/relations", json={
            "source_key": "alpha", "target_key": "beta", "relation_type": "depends_on"
        })
        r = client.get("/api/memories/alpha/related")
        assert r.status_code == 200
        data = r.json()
        assert data["key"] == "alpha"
        assert data["count"] == 1
        assert data["related"][0]["key"] == "beta"
        assert data["related"][0]["relation_type"] == "depends_on"
        assert data["related"][0]["direction"] == "outgoing"

    def test_related_bidirectional(self, client) -> None:
        client.post("/api/memories", json={"key": "x", "value": "X"})
        client.post("/api/memories", json={"key": "y", "value": "Y"})
        client.post("/api/relations", json={"source_key": "x", "target_key": "y"})
        r = client.get("/api/memories/y/related")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        assert data["related"][0]["key"] == "x"
        assert data["related"][0]["direction"] == "incoming"

    def test_no_relations(self, client) -> None:
        client.post("/api/memories", json={"key": "lonely", "value": "No friends"})
        r = client.get("/api/memories/lonely/related")
        assert r.status_code == 200
        assert r.json()["count"] == 0
