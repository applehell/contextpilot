"""Tests for MCP server tools — parameter validation, stateless mode, tool responses."""
from __future__ import annotations

import json
import pytest
from unittest.mock import patch, MagicMock

from src.interfaces.mcp_server import (
    memory_set, memory_get, memory_delete, memory_search, memory_list,
    heartbeat, register_skill, list_registered_skills, get_skill_context,
)


@pytest.fixture(autouse=True)
def mock_stores(tmp_path, monkeypatch):
    """Set up isolated stores for all MCP tests."""
    from src.storage.db import Database
    from src.storage.memory import MemoryStore
    from src.storage.memory_activity import MemoryActivityLog

    db = Database(tmp_path / "test.db")
    store = MemoryStore(db)
    log = MemoryActivityLog(db)

    monkeypatch.setattr("src.interfaces.mcp_server._get_memory_store", lambda: store)
    monkeypatch.setattr("src.interfaces.mcp_server._get_activity_log", lambda: log)
    yield store
    db.close()


class TestMemorySet:
    """memory_set tool parameter handling."""

    def test_basic_set(self):
        result = memory_set(key="test/key", value="hello world")
        assert result["status"] == "saved"
        assert result["key"] == "test/key"

    def test_set_with_tags(self):
        result = memory_set(key="test/tagged", value="data", tags=["a", "b"])
        assert result["status"] == "saved"

    def test_set_tags_none(self):
        result = memory_set(key="test/none-tags", value="data", tags=None)
        assert result["status"] == "saved"

    def test_set_empty_key_rejected(self):
        result = memory_set(key="", value="data")
        assert "error" in result

    def test_set_whitespace_key_rejected(self):
        result = memory_set(key="   ", value="data")
        assert "error" in result

    def test_update_existing(self):
        memory_set(key="test/update", value="v1")
        result = memory_set(key="test/update", value="v2")
        assert result["status"] == "saved"
        got = memory_get(key="test/update")
        assert got["value"] == "v2"

    def test_special_chars_in_key(self):
        result = memory_set(key="path/with spaces/and-dashes", value="ok")
        assert result["status"] == "saved"

    def test_long_value(self):
        result = memory_set(key="test/long", value="x" * 10000)
        assert result["status"] == "saved"


class TestMemoryGet:
    def test_get_existing(self):
        memory_set(key="test/get", value="hello")
        result = memory_get(key="test/get")
        assert result["key"] == "test/get"
        assert result["value"] == "hello"

    def test_get_nonexistent(self):
        result = memory_get(key="nonexistent/key")
        assert "error" in result

    def test_get_with_tags(self):
        memory_set(key="test/tags", value="v", tags=["t1", "t2"])
        result = memory_get(key="test/tags")
        assert result["tags"] == ["t1", "t2"]


class TestMemoryDelete:
    def test_delete_existing(self):
        memory_set(key="test/del", value="bye")
        result = memory_delete(key="test/del")
        assert result["status"] == "deleted"

    def test_delete_nonexistent(self):
        result = memory_delete(key="nope")
        assert "error" in result


class TestMemorySearch:
    def test_search_basic(self):
        memory_set(key="search/doc1", value="python programming guide")
        memory_set(key="search/doc2", value="javascript framework")
        result = memory_search(query="python")
        assert result["count"] >= 1

    def test_search_with_tags(self):
        memory_set(key="s/tagged", value="data", tags=["special"])
        result = memory_search(query="", tags=["special"])
        assert result["count"] >= 1

    def test_search_tags_none(self):
        memory_set(key="s/notag", value="plain data")
        result = memory_search(query="plain", tags=None)
        assert result["count"] >= 1

    def test_search_empty_query(self):
        result = memory_search(query="")
        assert "count" in result


class TestMemoryList:
    def test_list_empty(self):
        result = memory_list()
        assert result["count"] == 0

    def test_list_with_memories(self):
        memory_set(key="l/1", value="a")
        memory_set(key="l/2", value="b")
        result = memory_list()
        assert result["count"] == 2

    def test_list_with_tag_filter(self):
        memory_set(key="l/tagged", value="x", tags=["filter-me"])
        memory_set(key="l/other", value="y")
        result = memory_list(tag="filter-me")
        assert result["count"] == 1


class TestHeartbeat:
    def test_heartbeat_unregistered(self):
        result = heartbeat(name="nonexistent-skill")
        assert result["status"] == "not_registered"

    def test_heartbeat_registered(self):
        register_skill(name="test-skill", description="test")
        result = heartbeat(name="test-skill")
        assert result["status"] == "ok"


class TestRegisterSkill:
    def test_register_basic(self):
        result = register_skill(name="my-skill", description="A test skill")
        assert result["status"] == "registered"

    def test_register_with_hints(self):
        result = register_skill(name="hinted", description="test", context_hints=["python", "api"])
        assert result["status"] == "registered"

    def test_register_hints_none(self):
        result = register_skill(name="no-hints", description="test", context_hints=None)
        assert result["status"] == "registered"

    def test_register_empty_name(self):
        result = register_skill(name="", description="test")
        assert "error" in result

    def test_list_skills(self):
        register_skill(name="listed", description="test")
        result = list_registered_skills()
        assert result["count"] >= 1


class TestMutableDefaults:
    """Verify no mutable default arguments leak across calls."""

    def test_memory_set_tags_isolation(self):
        memory_set(key="iso/1", value="a")
        memory_set(key="iso/2", value="b", tags=["x"])
        r1 = memory_get(key="iso/1")
        r2 = memory_get(key="iso/2")
        assert r1["tags"] == []
        assert r2["tags"] == ["x"]

    def test_memory_search_tags_isolation(self):
        memory_set(key="iso/s1", value="data1", tags=["t1"])
        r1 = memory_search(query="data1")
        r2 = memory_search(query="data1", tags=["t1"])
        assert r1["count"] >= 1
        assert r2["count"] >= 1
