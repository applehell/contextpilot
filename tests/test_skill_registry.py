"""Tests for src.core.skill_registry — SQLite-backed skill registry."""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from src.core.skill_registry import SkillRegistry, _STALE_TIMEOUT


@pytest.fixture
def registry(tmp_path):
    db_path = tmp_path / "test_skills.db"
    with patch("src.core.skill_registry._DB_PATH", db_path):
        SkillRegistry._instance = None
        reg = SkillRegistry()
        yield reg
        SkillRegistry._instance = None


class TestRegister:
    def test_register_creates_entry(self, registry: SkillRegistry) -> None:
        skill = registry.register("test-skill", "A test skill", ["hint1"])
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.context_hints == ["hint1"]
        fetched = registry.get("test-skill")
        assert fetched is not None
        assert fetched.name == "test-skill"

    def test_register_upsert(self, registry: SkillRegistry) -> None:
        registry.register("skill", "old desc")
        registry.register("skill", "new desc")
        fetched = registry.get("skill")
        assert fetched.description == "new desc"

    def test_register_without_hints(self, registry: SkillRegistry) -> None:
        skill = registry.register("no-hints", "desc")
        assert skill.context_hints == []


class TestHeartbeat:
    def test_heartbeat_existing(self, registry: SkillRegistry) -> None:
        registry.register("alive", "desc")
        result = registry.heartbeat("alive")
        assert result is True

    def test_heartbeat_nonexistent(self, registry: SkillRegistry) -> None:
        result = registry.heartbeat("ghost")
        assert result is False


class TestListAliveStale:
    def test_fresh_skill_is_alive(self, registry: SkillRegistry) -> None:
        registry.register("fresh", "desc")
        alive = registry.list_alive()
        assert len(alive) == 1
        assert alive[0].name == "fresh"
        assert registry.list_stale() == []

    def test_old_skill_is_stale(self, registry: SkillRegistry) -> None:
        registry.register("old", "desc")
        old_time = time.time() - _STALE_TIMEOUT - 100
        registry._conn.execute(
            "UPDATE skill_registry SET last_seen = ? WHERE name = ?",
            (old_time, "old"),
        )
        registry._conn.commit()
        assert registry.list_alive() == []
        stale = registry.list_stale()
        assert len(stale) == 1
        assert stale[0].name == "old"


class TestCleanupStale:
    def test_cleanup_removes_stale(self, registry: SkillRegistry) -> None:
        registry.register("fresh", "desc")
        registry.register("old", "desc")
        old_time = time.time() - _STALE_TIMEOUT - 100
        registry._conn.execute(
            "UPDATE skill_registry SET last_seen = ? WHERE name = ?",
            (old_time, "old"),
        )
        registry._conn.commit()

        removed = registry.cleanup_stale()
        assert removed == 1
        assert registry.get("old") is None
        assert registry.get("fresh") is not None

    def test_cleanup_nothing_stale(self, registry: SkillRegistry) -> None:
        registry.register("fresh", "desc")
        removed = registry.cleanup_stale()
        assert removed == 0


class TestUnregister:
    def test_unregister_existing(self, registry: SkillRegistry) -> None:
        registry.register("to-delete", "desc")
        assert registry.unregister("to-delete") is True
        assert registry.get("to-delete") is None

    def test_unregister_nonexistent(self, registry: SkillRegistry) -> None:
        assert registry.unregister("ghost") is False


class TestListAll:
    def test_list_all_ordered(self, registry: SkillRegistry) -> None:
        registry.register("beta", "b")
        registry.register("alpha", "a")
        all_skills = registry.list_all()
        assert [s.name for s in all_skills] == ["alpha", "beta"]
