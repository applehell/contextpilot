"""Tests for src.core.dependency_detector — auto-detect memory dependencies."""
from __future__ import annotations

from src.core.dependency_detector import detect_dependencies
from src.storage.memory import Memory


def _mem(key: str, value: str, tags: list | None = None) -> Memory:
    return Memory(key=key, value=value, tags=tags or [])


class TestKeyReferences:
    def test_value_mentions_other_key(self) -> None:
        mems = [
            _mem("server-config", "The server runs at 192.168.1.78"),
            _mem("deployment", "See server-config for details on the host"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert len(refs) == 1
        assert refs[0]["source_key"] == "deployment"
        assert refs[0]["target_key"] == "server-config"
        assert refs[0]["confidence"] == 0.9

    def test_no_key_reference(self) -> None:
        mems = [
            _mem("alpha", "first memory"),
            _mem("beta", "second memory"),
        ]
        deps = detect_dependencies(mems)
        refs = [d for d in deps if d["relation_type"] == "references"]
        assert refs == []


class TestSharedEntities:
    def test_shared_ip(self) -> None:
        mems = [
            _mem("server", "Runs on 192.168.1.78"),
            _mem("homeassistant", "HA at 192.168.1.78:8123"),
        ]
        deps = detect_dependencies(mems)
        shared = [d for d in deps if d["relation_type"] == "shared_entity"]
        assert len(shared) >= 1
        keys_in_pair = {shared[0]["source_key"], shared[0]["target_key"]}
        assert keys_in_pair == {"homeassistant", "server"}
        assert shared[0]["confidence"] == 0.7

    def test_shared_url(self) -> None:
        mems = [
            _mem("docs", "Visit https://example.com/api for docs"),
            _mem("config", "API base: https://example.com/api"),
        ]
        deps = detect_dependencies(mems)
        shared = [d for d in deps if d["relation_type"] == "shared_entity"]
        assert len(shared) >= 1

    def test_entity_over_20_occurrences_filtered(self) -> None:
        mems = [_mem(f"m{i}", "common IP 10.0.0.1 here") for i in range(25)]
        deps = detect_dependencies(mems)
        shared = [d for d in deps if d["relation_type"] == "shared_entity"]
        # IP appears in >20 memories, so no shared_entity relations for it
        ip_shared = [d for d in shared if "10.0.0.1" not in str(d)]
        assert shared == []  # all would reference 10.0.0.1 which is filtered


class TestTagClusters:
    def test_two_shared_tags(self) -> None:
        mems = [
            _mem("a", "val a", tags=["docker", "networking", "config"]),
            _mem("b", "val b", tags=["docker", "networking"]),
        ]
        deps = detect_dependencies(mems)
        clusters = [d for d in deps if d["relation_type"] == "tag_cluster"]
        assert len(clusters) == 1
        assert clusters[0]["confidence"] == 0.6  # 2 shared * 0.3

    def test_one_shared_tag_not_enough(self) -> None:
        mems = [
            _mem("a", "val a", tags=["docker"]),
            _mem("b", "val b", tags=["docker"]),
        ]
        deps = detect_dependencies(mems)
        clusters = [d for d in deps if d["relation_type"] == "tag_cluster"]
        assert clusters == []

    def test_no_tags(self) -> None:
        mems = [
            _mem("a", "val a"),
            _mem("b", "val b"),
        ]
        deps = detect_dependencies(mems)
        clusters = [d for d in deps if d["relation_type"] == "tag_cluster"]
        assert clusters == []

    def test_confidence_capped_at_1(self) -> None:
        mems = [
            _mem("a", "val", tags=["t1", "t2", "t3", "t4", "t5"]),
            _mem("b", "val", tags=["t1", "t2", "t3", "t4", "t5"]),
        ]
        deps = detect_dependencies(mems)
        clusters = [d for d in deps if d["relation_type"] == "tag_cluster"]
        assert len(clusters) == 1
        assert clusters[0]["confidence"] == 1.0  # min(1.0, 5 * 0.3) = 1.0


class TestEdgeCases:
    def test_empty_list(self) -> None:
        assert detect_dependencies([]) == []

    def test_single_memory(self) -> None:
        deps = detect_dependencies([_mem("only", "value")])
        assert deps == []
