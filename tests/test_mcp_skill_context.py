"""Tests for MCP skill context tools — unregister, list, get_skill_context."""
from __future__ import annotations

import pytest

from src.interfaces.mcp_server import (
    register_skill,
    unregister_skill,
    list_registered_skills,
    get_skill_context,
    memory_set,
)
from src.storage.db import Database
from src.storage.memory import MemoryStore
from src.storage.memory_activity import MemoryActivityLog
from src.storage.usage import UsageStore
from src.core.skill_registry import SkillRegistry


@pytest.fixture(autouse=True)
def mock_stores(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    store = MemoryStore(db)
    log = MemoryActivityLog(db)
    usage = UsageStore(db)

    # Point SkillRegistry at a temp DB so it doesn't use the real one
    monkeypatch.setattr("src.core.skill_registry._DB_PATH", tmp_path / "skills.db")
    registry = SkillRegistry()

    monkeypatch.setattr("src.interfaces.mcp_server._get_db", lambda: db)
    monkeypatch.setattr("src.interfaces.mcp_server._get_memory_store", lambda: store)
    monkeypatch.setattr("src.interfaces.mcp_server._get_activity_log", lambda: log)
    monkeypatch.setattr("src.interfaces.mcp_server._get_usage_store", lambda: usage)
    monkeypatch.setattr("src.interfaces.mcp_server._registry", registry)
    yield store
    db.close()


class TestUnregisterSkill:
    def test_unregister_existing_skill(self):
        register_skill(name="tmp-skill", description="temporary")
        result = unregister_skill(name="tmp-skill")
        assert result["status"] == "unregistered"
        assert result["skill_name"] == "tmp-skill"

    def test_unregister_nonexistent(self):
        result = unregister_skill(name="does-not-exist")
        assert result["status"] == "not_found"

    def test_unregister_double(self):
        register_skill(name="double", description="d")
        first = unregister_skill(name="double")
        assert first["status"] == "unregistered"
        second = unregister_skill(name="double")
        assert second["status"] == "not_found"

    def test_unregister_empty_name(self):
        result = unregister_skill(name="")
        assert result["status"] == "not_found"


class TestListRegisteredSkills:
    def test_list_empty(self):
        result = list_registered_skills()
        assert result["count"] == 0
        assert result["skills"] == []

    def test_list_after_register(self):
        register_skill(name="skill-a", description="A")
        register_skill(name="skill-b", description="B")
        result = list_registered_skills()
        assert result["count"] == 2
        names = [s["name"] for s in result["skills"]]
        assert "skill-a" in names
        assert "skill-b" in names

    def test_list_contains_metadata(self):
        register_skill(name="meta", description="Meta skill", context_hints=["python", "api"])
        result = list_registered_skills()
        skill = result["skills"][0]
        assert skill["name"] == "meta"
        assert skill["description"] == "Meta skill"
        assert skill["context_hints"] == ["python", "api"]

    def test_list_after_unregister(self):
        register_skill(name="keep", description="K")
        register_skill(name="remove", description="R")
        unregister_skill(name="remove")
        result = list_registered_skills()
        assert result["count"] == 1
        assert result["skills"][0]["name"] == "keep"


class TestGetSkillContext:
    def test_unregistered_skill_error(self):
        result = get_skill_context(skill_name="ghost")
        assert "error" in result

    def test_empty_pool(self):
        register_skill(name="empty-pool", description="test")
        result = get_skill_context(skill_name="empty-pool")
        assert result["blocks"] == []
        assert result["total_tokens"] == 0

    def test_with_memories(self):
        register_skill(name="reader", description="reads stuff", context_hints=["python"])
        memory_set(key="mem/1", value="python programming guide")
        memory_set(key="mem/2", value="javascript framework notes")
        result = get_skill_context(skill_name="reader")
        assert result["blocks_selected"] >= 1
        assert result["total_tokens"] > 0

    def test_token_budget_limits(self):
        register_skill(name="budgeted", description="test", context_hints=["data"])
        for i in range(20):
            memory_set(key=f"bulk/{i}", value=f"data entry number {i} with some extra words to fill tokens")
        result = get_skill_context(skill_name="budgeted", token_budget=50)
        assert result["total_tokens"] <= 50

    def test_blocks_have_required_fields(self):
        register_skill(name="fields", description="test", context_hints=["info"])
        memory_set(key="f/1", value="some info content here")
        result = get_skill_context(skill_name="fields")
        if result["blocks_selected"] > 0:
            block = result["blocks"][0]
            assert "content" in block
            assert "token_count" in block
            assert "priority" in block
            assert "relevance" in block

    def test_custom_block_pool(self):
        register_skill(name="custom", description="test")
        custom_blocks = [
            {"content": "custom block one", "priority": "high"},
            {"content": "custom block two", "priority": "medium"},
        ]
        result = get_skill_context(skill_name="custom", blocks=custom_blocks)
        assert result["blocks_selected"] >= 1

    def test_blocks_served_tracked(self):
        register_skill(name="tracked", description="test")
        memory_set(key="t/1", value="tracking test content")
        get_skill_context(skill_name="tracked")
        skills = list_registered_skills()
        skill = [s for s in skills["skills"] if s["name"] == "tracked"][0]
        assert skill["blocks_served"] >= 1
