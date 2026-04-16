"""Tests for TemplateStore — context template CRUD operations."""
from __future__ import annotations

import pytest

from src.storage.db import Database
from src.storage.templates import TemplateStore, ContextTemplate


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    s = TemplateStore(db)
    yield s
    db.close()


class TestTemplateStore:
    def test_list_empty(self, store):
        assert store.list() == []

    def test_save_and_get(self, store):
        t = ContextTemplate(name="my-tmpl", description="A template", key_filter="proj/*", budget=2000)
        store.save(t)
        got = store.get("my-tmpl")
        assert got.name == "my-tmpl"
        assert got.description == "A template"
        assert got.key_filter == "proj/*"
        assert got.budget == 2000

    def test_save_with_tags(self, store):
        t = ContextTemplate(name="tagged", tag_filter=["python", "api", "docs"])
        store.save(t)
        got = store.get("tagged")
        assert got.tag_filter == ["python", "api", "docs"]

    def test_list_multiple(self, store):
        for name in ["charlie", "alpha", "bravo"]:
            store.save(ContextTemplate(name=name))
        result = store.list()
        assert len(result) == 3
        names = [t.name for t in result]
        assert names == ["alpha", "bravo", "charlie"]

    def test_update_existing(self, store):
        store.save(ContextTemplate(name="dup", description="v1", budget=1000))
        store.save(ContextTemplate(name="dup", description="v2", budget=2000))
        got = store.get("dup")
        assert got.description == "v2"
        assert got.budget == 2000
        assert len(store.list()) == 1

    def test_delete_existing(self, store):
        store.save(ContextTemplate(name="gone"))
        store.delete("gone")
        assert store.list() == []

    def test_delete_nonexistent(self, store):
        with pytest.raises(KeyError):
            store.delete("nope")

    def test_get_nonexistent(self, store):
        with pytest.raises(KeyError):
            store.get("nope")

    def test_save_empty_name(self, store):
        t = ContextTemplate(name="")
        store.save(t)
        got = store.get("")
        assert got.name == ""

    def test_budget_default(self, store):
        t = ContextTemplate(name="defaults")
        store.save(t)
        got = store.get("defaults")
        assert got.budget == 4000
