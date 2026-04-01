"""Tests for ProfileManager singleton caching behavior."""
from __future__ import annotations

import pytest

from src.storage.profiles import ProfileManager


@pytest.fixture(autouse=True)
def _clean_singleton():
    """Ensure singleton is cleared before and after each test."""
    ProfileManager.invalidate()
    yield
    ProfileManager.invalidate()


class TestProfileCache:
    def test_instance_returns_same_object(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        a = ProfileManager.instance()
        b = ProfileManager.instance()
        assert a is b

    def test_invalidate_clears_singleton(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        a = ProfileManager.instance()
        ProfileManager.invalidate()
        b = ProfileManager.instance()
        assert a is not b

    def test_create_invalidates_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        pm = ProfileManager.instance()
        pm.create("test-profile")
        assert ProfileManager._instance is None

    def test_switch_invalidates_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        pm = ProfileManager.instance()
        p = pm.create("switchable")
        # Re-fetch since create invalidated
        pm2 = ProfileManager.instance()
        pm2.switch(p.id)
        assert ProfileManager._instance is None

    def test_delete_invalidates_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        pm = ProfileManager.instance()
        p = pm.create("deletable")
        pm2 = ProfileManager.instance()
        pm2.delete(p.id)
        assert ProfileManager._instance is None

    def test_rename_invalidates_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        pm = ProfileManager.instance()
        p = pm.create("renamable")
        pm2 = ProfileManager.instance()
        pm2.rename(p.id, "renamed-profile")
        assert ProfileManager._instance is None

    def test_instance_after_invalidate_reads_updated_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")

        pm = ProfileManager.instance()
        p = pm.create("new-one")
        # After create, cache is invalidated — new instance should see the profile
        pm2 = ProfileManager.instance()
        profiles = pm2.list()
        names = {pr.name for pr in profiles}
        assert "new-one" in names
