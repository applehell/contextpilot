"""Extended tests for RelationStore — bulk_add_auto, clear_auto, get_related_keys, get_graph."""
from __future__ import annotations

import pytest

from src.storage.db import Database
from src.storage.relations import RelationStore


@pytest.fixture
def rs():
    db = Database(None)
    return RelationStore(db)


class TestRelationStore:
    def test_add_and_get(self, rs):
        r = rs.add("a", "b", "references")
        assert r.source_key == "a"
        assert r.target_key == "b"
        assert r.relation_type == "references"

    def test_add_duplicate(self, rs):
        rs.add("a", "b")
        with pytest.raises(ValueError):
            rs.add("a", "b")

    def test_remove(self, rs):
        r = rs.add("x", "y")
        rs.remove(r.id)
        assert rs.get_relations("x") == []

    def test_remove_not_found(self, rs):
        with pytest.raises(KeyError):
            rs.remove(99999)

    def test_list_all(self, rs):
        rs.add("a", "b")
        rs.add("c", "d")
        all_rels = rs.list_all()
        assert len(all_rels) == 2

    def test_bulk_add_auto(self, rs):
        relations = [
            {"source_key": "a", "target_key": "b", "relation_type": "references", "confidence": 0.9},
            {"source_key": "c", "target_key": "d", "relation_type": "shared_entity"},
        ]
        count = rs.bulk_add_auto(relations)
        assert count == 2
        all_rels = rs.list_all()
        assert len(all_rels) == 2
        auto_rels = [r for r in all_rels if r.auto]
        assert len(auto_rels) == 2

    def test_bulk_add_auto_skips_duplicates(self, rs):
        relations = [
            {"source_key": "a", "target_key": "b", "relation_type": "references"},
        ]
        rs.bulk_add_auto(relations)
        count = rs.bulk_add_auto(relations)
        assert count == 0

    def test_clear_auto(self, rs):
        rs.add("manual_a", "manual_b")
        rs.bulk_add_auto([{"source_key": "auto_a", "target_key": "auto_b", "relation_type": "auto"}])
        cleared = rs.clear_auto()
        assert cleared == 1
        remaining = rs.list_all()
        assert len(remaining) == 1
        assert remaining[0].source_key == "manual_a"

    def test_get_related_keys(self, rs):
        rs.add("center", "right")
        rs.add("left", "center")
        keys = rs.get_related_keys("center")
        assert "left" in keys
        assert "right" in keys

    def test_get_graph(self, rs):
        rs.add("a", "b", "references")
        rs.add("b", "c", "related")
        graph = rs.get_graph()
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2
        assert all("type" in e for e in graph["edges"])
