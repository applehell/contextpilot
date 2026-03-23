"""Tests for the profile manager."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.storage.profiles import ProfileManager, Profile, PROFILES_DIR, CONFIG_FILE


@pytest.fixture
def pm(tmp_path, monkeypatch):
    """ProfileManager with temp dirs."""
    profiles_dir = tmp_path / "profiles"
    config_file = tmp_path / "profiles.json"
    default_db = tmp_path / "data.db"

    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", profiles_dir)
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", config_file)
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", default_db)

    return ProfileManager()


class TestInit:
    def test_creates_default_profile(self, pm):
        profiles = pm.list()
        assert len(profiles) >= 1
        assert any(p.name == "default" for p in profiles)

    def test_active_is_default(self, pm):
        assert pm.active_name == "default"


class TestCreate:
    def test_create_profile(self, pm):
        p = pm.create("test-profile", "A test profile")
        assert p.name == "test-profile"
        assert p.description == "A test profile"
        assert Path(p.db_path).exists()

    def test_create_duplicate_fails(self, pm):
        pm.create("dup")
        with pytest.raises(ValueError, match="already exists"):
            pm.create("dup")

    def test_create_invalid_name(self, pm):
        with pytest.raises(ValueError, match="alphanumeric"):
            pm.create("bad name!")

    def test_list_after_create(self, pm):
        pm.create("alpha")
        pm.create("beta")
        profiles = pm.list()
        names = [p.name for p in profiles]
        assert "default" in names
        assert "alpha" in names
        assert "beta" in names


class TestSwitch:
    def test_switch_profile(self, pm):
        pm.create("other")
        pm.switch("other")
        assert pm.active_name == "other"

    def test_switch_nonexistent_fails(self, pm):
        with pytest.raises(KeyError):
            pm.switch("nonexistent")

    def test_switch_updates_db_path(self, pm):
        pm.create("new")
        path = pm.switch("new")
        assert "new" in str(path)


class TestDelete:
    def test_delete_profile(self, pm):
        pm.create("to-delete")
        pm.delete("to-delete")
        assert pm.get("to-delete") is None

    def test_delete_default_fails(self, pm):
        with pytest.raises(ValueError, match="default"):
            pm.delete("default")

    def test_delete_active_switches_to_default(self, pm):
        pm.create("active-one")
        pm.switch("active-one")
        pm.delete("active-one")
        assert pm.active_name == "default"

    def test_delete_nonexistent_fails(self, pm):
        with pytest.raises(KeyError):
            pm.delete("nope")


class TestDuplicate:
    def test_duplicate_profile(self, pm):
        pm.create("source")
        p = pm.duplicate("source", "copy", "A copy")
        assert p.name == "copy"
        assert Path(p.db_path).exists()

    def test_duplicate_nonexistent_fails(self, pm):
        with pytest.raises(KeyError):
            pm.duplicate("nope", "copy")


class TestGet:
    def test_get_existing(self, pm):
        pm.create("findme")
        p = pm.get("findme")
        assert p is not None
        assert p.name == "findme"

    def test_get_nonexistent(self, pm):
        assert pm.get("nope") is None
