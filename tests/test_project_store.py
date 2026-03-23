"""Tests for src.storage.project — ProjectStore (SQLite-backed)."""
from __future__ import annotations

import pytest

from src.storage.db import Database
from src.storage.project import ProjectStore, ProjectMeta, ContextConfig


@pytest.fixture
def db():
    database = Database(None)  # in-memory
    yield database
    database.close()


@pytest.fixture
def store(db: Database) -> ProjectStore:
    return ProjectStore(db)


class TestProjectStore:
    def test_list_empty(self, store: ProjectStore) -> None:
        assert store.list_projects() == []

    def test_create_and_list(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="demo", description="A demo project"))
        projects = store.list_projects()
        assert len(projects) == 1
        assert projects[0].name == "demo"
        assert projects[0].description == "A demo project"

    def test_create_duplicate_raises(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="dup"))
        with pytest.raises(FileExistsError):
            store.create(ProjectMeta(name="dup"))

    def test_load_and_save(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="proj"))
        meta, contexts = store.load("proj")
        assert meta.name == "proj"
        assert contexts == []

    def test_load_nonexistent_raises(self, store: ProjectStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.load("nope")

    def test_delete(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="del_me"))
        store.delete("del_me")
        assert store.list_projects() == []

    def test_delete_nonexistent_raises(self, store: ProjectStore) -> None:
        with pytest.raises(FileNotFoundError):
            store.delete("ghost")

    def test_add_and_remove_context(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="ctx_proj"))
        store.add_context("ctx_proj", ContextConfig(name="default", blocks=[{"content": "hello", "priority": "high"}]))
        _, contexts = store.load("ctx_proj")
        assert len(contexts) == 1
        assert contexts[0].name == "default"
        assert len(contexts[0].blocks) == 1

        store.remove_context("ctx_proj", "default")
        _, contexts = store.load("ctx_proj")
        assert len(contexts) == 0

    def test_add_duplicate_context_raises(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="dup_ctx"))
        store.add_context("dup_ctx", ContextConfig(name="main"))
        with pytest.raises(ValueError):
            store.add_context("dup_ctx", ContextConfig(name="main"))

    def test_save_updates_meta(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="upd"))
        meta, _ = store.load("upd")
        meta.description = "updated"
        store.save(meta)
        meta2, _ = store.load("upd")
        assert meta2.description == "updated"

    def test_last_used_updated_on_load(self, store: ProjectStore) -> None:
        store.create(ProjectMeta(name="ts", created_at=1.0, last_used=1.0))
        meta, _ = store.load("ts")
        assert meta.last_used > 1.0


class TestProjectMeta:
    def test_roundtrip(self) -> None:
        m = ProjectMeta(name="test", description="desc", created_at=100.0, last_used=200.0)
        d = m.to_dict()
        m2 = ProjectMeta.from_dict(d)
        assert m2.name == m.name
        assert m2.description == m.description
        assert m2.created_at == m.created_at
        assert m2.last_used == m.last_used


class TestContextConfig:
    def test_roundtrip(self) -> None:
        c = ContextConfig(name="main", blocks=[{"content": "x"}])
        d = c.to_dict()
        c2 = ContextConfig.from_dict(d)
        assert c2.name == c.name
        assert c2.blocks == c.blocks
