"""Tests for Memory Editor logic (non-GUI parts) and MemoryStore integration scenarios."""
from __future__ import annotations

import pytest

from src.core.block import Block, Priority
from src.core.token_budget import TokenBudget
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore


@pytest.fixture
def db() -> Database:
    return Database(None)


@pytest.fixture
def store(db: Database) -> MemoryStore:
    return MemoryStore(db)


class TestMemoryEditorLogic:
    """Tests that exercise the MemoryStore operations the MemoryEditor GUI relies on."""

    def test_create_and_list(self, store: MemoryStore) -> None:
        store.set(Memory(key="sys-prompt", value="You are a helpful assistant.", tags=["system"]))
        store.set(Memory(key="user-pref", value="Prefer concise answers.", tags=["user"]))
        memories = store.list()
        assert len(memories) == 2
        keys = {m.key for m in memories}
        assert keys == {"sys-prompt", "user-pref"}

    def test_edit_updates_value_and_tags(self, store: MemoryStore) -> None:
        store.set(Memory(key="k", value="old", tags=["a"]))
        store.set(Memory(key="k", value="new", tags=["a", "b"]))
        m = store.get("k")
        assert m.value == "new"
        assert m.tags == ["a", "b"]

    def test_delete_and_verify_gone(self, store: MemoryStore) -> None:
        store.set(Memory(key="temp", value="x"))
        store.delete("temp")
        with pytest.raises(KeyError):
            store.get("temp")

    def test_search_filter_combination(self, store: MemoryStore) -> None:
        store.set(Memory(key="config-db", value="host=localhost", tags=["config"]))
        store.set(Memory(key="config-cache", value="redis://localhost", tags=["config", "cache"]))
        store.set(Memory(key="note-db", value="localhost issues", tags=["notes"]))
        results = store.search("localhost", tags=["config"])
        assert len(results) == 2
        keys = {r.key for r in results}
        assert "note-db" not in keys

    def test_tag_listing_after_mutations(self, store: MemoryStore) -> None:
        store.set(Memory(key="a", value="x", tags=["alpha", "beta"]))
        store.set(Memory(key="b", value="y", tags=["gamma"]))
        assert set(store.tags()) == {"alpha", "beta", "gamma"}
        store.delete("a")
        assert store.tags() == ["gamma"]

    def test_memory_to_block_conversion(self, store: MemoryStore) -> None:
        store.set(Memory(key="prompt", value="Be concise and direct."))
        m = store.get("prompt")
        block = Block(content=f"[{m.key}] {m.value}", priority=Priority.MEDIUM)
        assert block.token_count > 0
        assert "prompt" in block.content

    def test_token_counting_for_preview(self, store: MemoryStore) -> None:
        store.set(Memory(key="long", value="word " * 100))
        m = store.get("long")
        tokens = TokenBudget.estimate(m.value)
        assert tokens > 50

    def test_bulk_memories_context_budget(self, store: MemoryStore) -> None:
        for i in range(10):
            store.set(Memory(key=f"mem-{i}", value=f"Memory content block {i}" * 5))
        memories = store.list()
        blocks = [
            Block(content=f"[{m.key}] {m.value}", priority=Priority.MEDIUM)
            for m in memories
        ]
        total = sum(b.token_count for b in blocks)
        assert total > 0
        assert len(blocks) == 10

    def test_empty_key_handling(self, store: MemoryStore) -> None:
        store.set(Memory(key="", value="no key"))
        m = store.get("")
        assert m.value == "no key"

    def test_special_characters_in_search(self, store: MemoryStore) -> None:
        store.set(Memory(key="sql", value="SELECT * FROM users WHERE id = 1"))
        results = store.search("SELECT")
        assert len(results) >= 1
