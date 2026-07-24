"""Tests for src.core.sleep — nightly consolidation cycle."""
from __future__ import annotations

import json
import time

import pytest

from src.core import sleep
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


def _episodic(key: str, value: str, age_days: float, tags=None) -> Memory:
    ts = time.time() - age_days * DAY
    return Memory(key=key, value=value, tags=tags or [], category="episodic",
                  created_at=ts, updated_at=ts)


class TestConfig:
    def test_defaults(self, tmp_path) -> None:
        cfg = sleep.load_config(tmp_path)
        assert cfg == sleep.DEFAULT_CONFIG

    def test_save_and_reload(self, tmp_path) -> None:
        sleep.save_config(tmp_path, {"enabled": False, "hour": 5, "unknown": "x"})
        cfg = sleep.load_config(tmp_path)
        assert cfg["enabled"] is False
        assert cfg["hour"] == 5
        assert "unknown" not in cfg

    def test_type_coercion_and_clamp(self, tmp_path) -> None:
        cfg = sleep.save_config(tmp_path, {"hour": 99, "auto_merge": 1, "episodic_age_days": "7"})
        assert cfg["hour"] == 23
        assert cfg["auto_merge"] is True
        assert cfg["episodic_age_days"] == 7

    def test_corrupt_file_falls_back(self, tmp_path) -> None:
        (tmp_path / sleep.CONFIG_FILE).write_text("{broken")
        assert sleep.load_config(tmp_path) == sleep.DEFAULT_CONFIG


class TestSleepDue:
    @pytest.fixture(autouse=True)
    def _data_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        yield tmp_path

    def test_due_after_hour(self) -> None:
        noon = time.mktime((2026, 7, 24, 12, 0, 0, 0, 0, -1))
        assert sleep.sleep_due(noon) is True

    def test_not_due_before_hour(self) -> None:
        one_am = time.mktime((2026, 7, 24, 1, 0, 0, 0, 0, -1))
        assert sleep.sleep_due(one_am) is False

    def test_not_due_twice_a_day(self) -> None:
        noon = time.mktime((2026, 7, 24, 12, 0, 0, 0, 0, -1))
        sleep.save_state({"last_date": time.strftime("%Y-%m-%d", time.localtime(noon))})
        assert sleep.sleep_due(noon) is False

    def test_disabled_never_due(self, _data_dir) -> None:
        sleep.save_config(_data_dir, {"enabled": False})
        noon = time.mktime((2026, 7, 24, 12, 0, 0, 0, 0, -1))
        assert sleep.sleep_due(noon) is False


class TestEpisodicConsolidation:
    def test_old_episodic_becomes_digest(self, db, store, tmp_path) -> None:
        m = _episodic("beobachtung/heizung-an", "Heizung wurde eingeschaltet, 21 Grad", 20, ["heizung"])
        store.set(m, reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        ep = report["episodic"]
        assert ep["eligible"] == 1
        assert ep["digests_created"] == 1
        assert ep["consolidated"] == 1

        month = time.strftime("%Y-%m", time.localtime(m.created_at))
        digest = store.get(f"digest/beobachtung/{month}")
        assert digest.category == "persistent"
        assert "digest" in digest.tags
        assert "heizung" in digest.tags
        assert "beobachtung/heizung-an" in digest.value
        assert digest.metadata["consolidated_from"] == ["beobachtung/heizung-an"]

        original = store.get("beobachtung/heizung-an")
        assert original.metadata["consolidated_into"] == f"digest/beobachtung/{month}"
        rels = RelationStore(db).get_relations("beobachtung/heizung-an")
        assert any(r.relation_type == "consolidated_into" for r in rels)

    def test_original_updated_at_preserved(self, db, store, tmp_path) -> None:
        m = _episodic("log/event", "Etwas ist passiert am Morgen", 20)
        store.set(m, reset_ttl=False)
        before = store.get("log/event").updated_at
        sleep.run_sleep_cycle(db, tmp_path)
        assert store.get("log/event").updated_at == before

    def test_young_episodic_untouched(self, db, store, tmp_path) -> None:
        store.set(_episodic("log/fresh", "Gerade eben passiert", 2), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["episodic"]["consolidated"] == 0
        assert "consolidated_into" not in store.get("log/fresh").metadata

    def test_persistent_untouched(self, db, store, tmp_path) -> None:
        old = time.time() - 30 * DAY
        store.set(Memory(key="fakten/ip", value="Server hat die IP 192.168.1.78",
                         created_at=old, updated_at=old), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["episodic"]["eligible"] == 0

    def test_idempotent_second_run(self, db, store, tmp_path) -> None:
        store.set(_episodic("log/a", "Ereignis A ist eingetreten heute", 20), reset_ttl=False)
        r1 = sleep.run_sleep_cycle(db, tmp_path)
        r2 = sleep.run_sleep_cycle(db, tmp_path)
        assert r1["episodic"]["consolidated"] == 1
        assert r2["episodic"]["consolidated"] == 0
        assert r2["episodic"]["digests_created"] == 0

    def test_digest_appends_new_members(self, db, store, tmp_path) -> None:
        store.set(_episodic("log/a", "Erstes Ereignis des Monats", 20), reset_ttl=False)
        sleep.run_sleep_cycle(db, tmp_path)
        b = _episodic("log/b", "Zweites Ereignis desselben Monats", 20)
        b.created_at = store.get("log/a").created_at  # same month bucket
        store.set(b, reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["episodic"]["digests_updated"] == 1
        month = time.strftime("%Y-%m", time.localtime(b.created_at))
        digest = store.get(f"digest/log/{month}")
        assert "log/a" in digest.value and "log/b" in digest.value
        assert digest.metadata["consolidated_from"] == ["log/a", "log/b"]

    def test_disabled_via_config(self, db, store, tmp_path) -> None:
        store.set(_episodic("log/a", "Ereignis A ist eingetreten heute", 20), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path, {"episodic_enabled": False})
        assert "episodic" not in report


class TestDuplicatesAndMerge:
    LONG = "Der go-e Charger in der Garage hat die feste IP-Adresse 192.168.1.104 im Heimnetz."

    def test_report_only_by_default(self, db, store, tmp_path) -> None:
        store.set(Memory(key="a", value=self.LONG), reset_ttl=False)
        store.set(Memory(key="b", value=self.LONG), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["duplicates"]["groups"] == 1
        assert report["duplicates"]["auto_merged"] == 0
        assert store.get("a") and store.get("b")

    def test_auto_merge_folds_group(self, db, store, tmp_path) -> None:
        store.set(Memory(key="a", value=self.LONG), reset_ttl=False)
        store.set(Memory(key="b", value=self.LONG), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path, {"auto_merge": True})
        assert report["duplicates"]["auto_merged"] == 1
        survivor = report["duplicates"]["merged"][0]["survivor"]
        assert store.get(survivor)
        merged_away = "a" if survivor == "b" else "b"
        with pytest.raises(KeyError):
            store.get(merged_away)

    def test_auto_merge_skips_pinned(self, db, store, tmp_path) -> None:
        store.set(Memory(key="a", value=self.LONG, pinned=True), reset_ttl=False)
        store.set(Memory(key="b", value=self.LONG), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path, {"auto_merge": True})
        assert report["duplicates"]["auto_merged"] == 0
        assert store.get("a") and store.get("b")


class TestReportAndRelations:
    def test_report_written_and_trimmed(self, db, store, tmp_path) -> None:
        store.set(Memory(key="x", value="Ein Eintrag mit etwas Inhalt"), reset_ttl=False)
        for _ in range(3):
            sleep.run_sleep_cycle(db, tmp_path, {"keep_reports": 2})
        reports = json.loads((tmp_path / sleep.REPORTS_FILE).read_text())
        assert len(reports) == 2
        assert sleep.load_reports(tmp_path, limit=1)[0]["total_memories"] == 1

    def test_relations_detected(self, db, store, tmp_path) -> None:
        store.set(Memory(key="a", value="Server läuft auf 192.168.1.78 im Rack"), reset_ttl=False)
        store.set(Memory(key="b", value="Backup zielt auf 192.168.1.78 jede Nacht"), reset_ttl=False)
        report = sleep.run_sleep_cycle(db, tmp_path)
        assert report["relations"]["added"] >= 1

    def test_report_structure(self, db, store, tmp_path) -> None:
        report = sleep.run_sleep_cycle(db, tmp_path)
        for key in ("total_memories", "duplicates", "contradictions", "low_confidence", "duration_ms"):
            assert key in report
        assert report["errors"] == []


class TestStoreAdditions:
    def test_update_metadata_preserves_updated_at(self, store) -> None:
        ts = time.time() - 5 * DAY
        store.set(Memory(key="k", value="v", created_at=ts, updated_at=ts), reset_ttl=False)
        store.update_metadata("k", {"flag": True})
        m = store.get("k")
        assert m.metadata["flag"] is True
        assert m.updated_at == ts

    def test_update_metadata_missing_raises(self, store) -> None:
        with pytest.raises(KeyError):
            store.update_metadata("nope", {"a": 1})

    def test_category_stats_include_episodic(self, store) -> None:
        store.set(Memory(key="e", value="v", category="episodic"), reset_ttl=False)
        stats = store.category_stats()
        assert stats["episodic"] == 1

    def test_episodic_has_no_auto_ttl(self, store) -> None:
        store.set(Memory(key="e", value="v", category="episodic"), reset_ttl=False)
        assert store.get("e").expires_at is None
