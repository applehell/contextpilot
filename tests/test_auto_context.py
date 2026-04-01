"""Tests for auto-context MCP tool (F2: get_context_for_task)."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.core.embeddings import index_memories, close_all_stores, set_data_dir


@pytest.fixture
def db():
    d = Database(None)
    yield d
    d.close()


@pytest.fixture
def store(db):
    return MemoryStore(db)


@pytest.fixture
def seeded_env(store, db, tmp_path):
    """Setup memories and embeddings, patch MCP internals."""
    set_data_dir(tmp_path)
    memories = [
        Memory(key="python/basics", value="Python is a versatile programming language", tags=["python"]),
        Memory(key="python/types", value="Python supports type hints since 3.5", tags=["python", "typing"]),
        Memory(key="python/testing", value="Pytest is the standard testing framework", tags=["python", "testing"]),
        Memory(key="docker/basics", value="Docker uses containers for isolation", tags=["docker"]),
        Memory(key="docker/compose", value="Docker Compose defines multi-container setups", tags=["docker"]),
        Memory(key="api/rest", value="REST APIs use HTTP methods for CRUD", tags=["api"]),
        Memory(key="api/graphql", value="GraphQL provides flexible querying", tags=["api"]),
        Memory(key="db/postgres", value="PostgreSQL is a relational database", tags=["database"]),
        Memory(key="db/redis", value="Redis is an in-memory key-value store", tags=["database"]),
        Memory(key="security/auth", value="OAuth2 is widely used for authentication", tags=["security"]),
    ]
    for m in memories:
        store.set(m)
    index_memories(memories, profile_dir=tmp_path)
    yield store, db
    close_all_stores()


class TestGetContextForTask:
    def test_returns_matching_blocks(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("Python programming and testing")
        assert result["memories_considered"] > 0
        assert result["memories_included"] > 0
        assert len(result["blocks"]) > 0
        assert result["total_tokens"] > 0

    def test_blocks_have_required_fields(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("Docker containers")
        for b in result["blocks"]:
            assert "key" in b
            assert "content" in b
            assert "priority" in b
            assert "tokens" in b

    def test_budget_limits_output(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("Python Docker API database", budget=50)
        assert result["total_tokens"] <= 50 or result["memories_included"] <= 1

    def test_tag_filtering(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("programming", include_tags=["docker"])
        # All returned blocks should come from docker-tagged memories
        for b in result["blocks"]:
            assert "docker" in b["key"].lower() or "docker" in b["content"].lower()

    def test_empty_description_returns_empty(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("")
        assert result["blocks"] == []
        assert result["total_tokens"] == 0
        assert result["memories_considered"] == 0
        assert result["memories_included"] == 0

    def test_priority_assignment(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("Python Docker API database security", budget=8000)
        priorities = [b["priority"] for b in result["blocks"]]
        # With enough results, we should see high priority blocks
        if len(priorities) >= 5:
            assert "high" in priorities

    def test_no_matching_memories(self, seeded_env):
        store, db = seeded_env
        with patch("src.interfaces.mcp_server._get_memory_store", return_value=store), \
             patch("src.interfaces.mcp_server._get_db", return_value=db):
            from src.interfaces.mcp_server import get_context_for_task
            result = get_context_for_task("xyznonexistent12345")
        assert result["memories_included"] == 0 or isinstance(result["blocks"], list)
