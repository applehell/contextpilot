"""Tests for the associative-brain features — spreading activation, archive
stage, write-time relation detection, forget step."""
from __future__ import annotations

import time

import pytest

from src.core import sleep
from src.core.activation import expand_results, spread_activation
from src.core.dependency_detector import detect_for_memory
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.storage.relations import RelationStore

DAY = 86400


@pytest.fixture
def db() -> Database:
    return Database(None)


@pytest.fixture
def store(db) -> MemoryStore:
    return MemoryStore(db)


@pytest.fixture
def rels(db) -> RelationStore:
    return RelationStore(db)


class TestSpreadActivation:
    def test_one_hop(self, rels) -> None:
        rels.add("a", "b")
        out = spread_activation({"a": 1.0}, rels)
        assert out == {"b": 0.5}

    def test_two_hops_decay(self, rels) -> None:
        rels.add("a", "b")
        rels.add("b", "c")
        out = spread_activation({"a": 1.0}, rels)
        assert out["b"] == 0.5
        assert out["c"] == 0.25

    def test_hop_limit(self, rels) -> None:
        rels.add("a", "b")
        rels.add("b", "c")
        rels.add("c", "d")
        out = spread_activation({"a": 1.0}, rels, max_hops=2)
        assert "d" not in out

    def test_min_activation_cutoff(self, rels) -> None:
        rels.add("a", "b")
        out = spread_activation({"a": 0.05}, rels)  # 0.05*0.5 < 0.05
        assert out == {}

    def test_seeds_excluded_and_max_nodes(self, rels) -> None:
        for i in range(12):
            rels.add("a", f"n{i}")
        out = spread_activation({"a": 1.0}, rels, max_nodes=5)
        assert "a" not in out
        assert len(out) == 5

    def test_confidence_weights_edge(self, db, rels) -> None:
        db.conn.execute(
            "INSERT INTO memory_relations (source_key, target_key, relation_type, auto, confidence, created_at) VALUES ('a', 'b', 'x', 1, 0.5, 0)")
        db.conn.commit()
        out = spread_activation({"a": 1.0}, rels)
        assert out["b"] == 0.25


class TestExpandResults:
    def test_appends_associated(self, store, rels) -> None:
        store.set(Memory(key="wallbox/config", value="go-e Charger Konfiguration"), reset_ttl=False)
        store.set(Memory(key="wallbox/reset-karte", value="RFID Reset-Karte 237102"), reset_ttl=False)
        rels.add("wallbox/config", "wallbox/reset-karte")
        results = [{"key": "wallbox/config", "value": "x", "score": 0.9, "tags": [], "method": "hybrid"}]
        extras = expand_results(results, store, rels)
        assert len(extras) == 1
        assert extras[0]["key"] == "wallbox/reset-karte"
        assert extras[0]["method"] == "associated"

    def test_skips_archived_and_existing(self, store, rels) -> None:
        store.set(Memory(key="a", value="v"), reset_ttl=False)
        store.set(Memory(key="b", value="v"), reset_ttl=False)
        store.archive("b")
        rels.add("a", "b")
        results = [{"key": "a", "value": "v", "score": 0.9, "tags": [], "method": "fts"}]
        assert expand_results(results, store, rels) == []

    def test_empty_results(self, store, rels) -> None:
        assert expand_results([], store, rels) == []


class TestArchive:
    def test_archive_excludes_from_list_and_search(self, store) -> None:
        store.set(Memory(key="k", value="findbarer Inhalt"), reset_ttl=False)
        store.archive("k")
        assert store.list() == []
        assert store.search("findbarer") == []
        assert store.list(include_archived=True)[0].key == "k"
        assert store.search("findbarer", include_archived=True)[0].key == "k"

    def test_get_still_works(self, store) -> None:
        store.set(Memory(key="k", value="v"), reset_ttl=False)
        store.archive("k")
        assert store.get("k").archived is True

    def test_unarchive(self, store) -> None:
        store.set(Memory(key="k", value="v"), reset_ttl=False)
        store.archive("k")
        store.archive("k", archived=False)
        assert len(store.list()) == 1

    def test_archive_missing_raises(self, store) -> None:
        with pytest.raises(KeyError):
            store.archive("nope")

    def test_export_includes_archived(self, store) -> None:
        store.set(Memory(key="k", value="v"), reset_ttl=False)
        store.archive("k")
        assert '"k"' in store.export_json()

    def test_category_stats_exclude_archived(self, store) -> None:
        store.set(Memory(key="a", value="v"), reset_ttl=False)
        store.set(Memory(key="b", value="v"), reset_ttl=False)
        store.archive("b")
        assert store.category_stats()["persistent"] == 1
        assert store.archived_count() == 1

    def test_set_preserves_archived_roundtrip(self, store) -> None:
        store.set(Memory(key="k", value="v"), reset_ttl=False)
        store.archive("k")
        m = store.get("k")
        m.value = "v2"
        store.set(m, reset_ttl=False)
        assert store.get("k").archived is True


class TestForgetStep:
    def _consolidated_episodic(self, key: str, age_days: float) -> Memory:
        ts = time.time() - age_days * DAY
        return Memory(key=key, value="Alte Beobachtung mit Inhalt", category="episodic",
                      metadata={"consolidated_into": "digest/log/2026-01"},
                      created_at=ts, updated_at=ts)

    def test_old_consolidated_archived(self, db, store, tmp_path) -> None:
        store.set(self._consolidated_episodic("log/old", 40), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["forget"]["archived"] == 1
        assert store.get("log/old").archived is True

    def test_young_consolidated_kept(self, db, store, tmp_path) -> None:
        store.set(self._consolidated_episodic("log/young", 10), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["forget"]["archived"] == 0

    def test_unconsolidated_never_archived(self, db, store, tmp_path) -> None:
        ts = time.time() - 90 * DAY
        store.set(Memory(key="log/raw", value="Nie konsolidiert", category="episodic",
                         created_at=ts, updated_at=ts),
                  reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path, {"episodic_enabled": False})
        assert report["forget"]["archived"] == 0

    def test_pinned_kept(self, db, store, tmp_path) -> None:
        m = self._consolidated_episodic("log/pinned", 40)
        m.pinned = True
        store.set(m, reset_ttl=False)
        store.pin("log/pinned")
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["forget"]["archived"] == 0

    def test_disabled(self, db, store, tmp_path) -> None:
        store.set(self._consolidated_episodic("log/old", 40), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path, {"forget_enabled": False})
        assert "forget" not in report


class TestEmptyVectorRepair:
    @pytest.fixture(autouse=True)
    def _embeddings_dir(self, tmp_path):
        from src.core import embeddings
        embeddings.set_data_dir(tmp_path)
        yield
        embeddings.close_all_stores()

    def test_new_vocab_single_index_reports_failure(self, store) -> None:
        from src.core import embeddings
        store.set(Memory(key="alt/heizung", value="Heizung Vorlauf Temperatur"), reset_ttl=False)
        embeddings.index_memories(store.list())
        neu = Memory(key="neu/wallbox", value="Charger Garage Ladeleistung")
        store.set(neu, reset_ttl=False)
        # vocabulary entirely unknown to the current IDF corpus → must not
        # store an empty vector, must request a full reindex instead
        assert embeddings.index_single_memory(neu) is False
        assert embeddings._get_store().get("neu/wallbox") is None

    def test_full_index_repairs_empty_stored_vector(self, store) -> None:
        from src.core import embeddings
        store.set(Memory(key="alt/heizung", value="Heizung Vorlauf Temperatur"), reset_ttl=False)
        embeddings.index_memories(store.list())
        neu = Memory(key="neu/wallbox", value="Charger Garage Ladeleistung")
        store.set(neu, reset_ttl=False)
        # simulate the historical bug: empty vector persisted with current hash
        import hashlib
        text = f"{neu.key} {' '.join(neu.tags)} {neu.value}"
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        embeddings._get_store().store(neu.key, h, {})
        embeddings.index_memories(store.list())
        assert embeddings._get_store().get("neu/wallbox")
        assert embeddings.semantic_search("Charger Garage")


class TestDetectForMemory:
    def test_reference_to_existing_key(self, db, store) -> None:
        store.set(Memory(key="geraet/wallbox", value="go-e Charger in der Garage"), reset_ttl=False)
        m = Memory(key="notiz/laden", value="Siehe geraet/wallbox für Details")
        store.set(m, reset_ttl=False)
        rels = detect_for_memory(m, db)
        assert any(r["target_key"] == "geraet/wallbox" and r["relation_type"] == "references"
                   for r in rels)

    def test_existing_value_references_new_key(self, db, store) -> None:
        store.set(Memory(key="alt/notiz", value="Der Plan steht in plan/urlaub beschrieben"), reset_ttl=False)
        m = Memory(key="plan/urlaub", value="Urlaubsplanung Details")
        store.set(m, reset_ttl=False)
        rels = detect_for_memory(m, db)
        assert any(r["source_key"] == "alt/notiz" and r["target_key"] == "plan/urlaub"
                   for r in rels)

    def test_shared_ip_entity(self, db, store) -> None:
        store.set(Memory(key="a", value="Server läuft auf 192.168.1.78"), reset_ttl=False)
        m = Memory(key="b", value="Backup zielt auf 192.168.1.78")
        store.set(m, reset_ttl=False)
        rels = detect_for_memory(m, db)
        assert any(r["relation_type"] == "shared_entity" for r in rels)

    def test_no_relations_for_isolated_memory(self, db, store) -> None:
        m = Memory(key="solo", value="Völlig eigenständiger Inhalt ohne Bezüge")
        store.set(m, reset_ttl=False)
        assert detect_for_memory(m, db) == []
