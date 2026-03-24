"""Tests for the profile manager."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from src.storage.profiles import ProfileManager, Profile, PROFILES_DIR, CONFIG_FILE, DEFAULT_ID


@pytest.fixture
def pm(tmp_path, monkeypatch):
    profiles_dir = tmp_path / "profiles"
    config_file = tmp_path / "profiles.json"
    default_db = tmp_path / "data.db"

    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", profiles_dir)
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", config_file)
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", default_db)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

    return ProfileManager()


class TestInit:
    def test_creates_default_profile(self, pm):
        profiles = pm.list()
        assert len(profiles) >= 1
        assert any(p.id == DEFAULT_ID for p in profiles)

    def test_active_is_default(self, pm):
        assert pm.active_id == DEFAULT_ID


class TestCreate:
    def test_create_profile(self, pm):
        p = pm.create("test-profile", "A test profile")
        assert p.name == "test-profile"
        assert p.id != DEFAULT_ID
        assert len(p.id) == 8
        assert Path(p.db_path).exists()

    def test_create_duplicate_name_fails(self, pm):
        pm.create("dup")
        with pytest.raises(ValueError, match="already exists"):
            pm.create("dup")

    def test_create_with_unicode_name(self, pm):
        p = pm.create("Büro & Privat", "Umlaute erlaubt")
        assert p.name == "Büro & Privat"
        assert len(p.id) == 8

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
        p = pm.create("other")
        pm.switch(p.id)
        assert pm.active_id == p.id

    def test_switch_nonexistent_fails(self, pm):
        with pytest.raises(KeyError):
            pm.switch("nonexistent")

    def test_switch_updates_db_path(self, pm):
        p = pm.create("new")
        path = pm.switch(p.id)
        assert p.id in str(path)


class TestDelete:
    def test_delete_profile(self, pm):
        p = pm.create("to-delete")
        pm.delete(p.id)
        assert pm.get(p.id) is None

    def test_delete_default_fails(self, pm):
        with pytest.raises(ValueError, match="default"):
            pm.delete(DEFAULT_ID)

    def test_delete_active_switches_to_default(self, pm):
        p = pm.create("active-one")
        pm.switch(p.id)
        pm.delete(p.id)
        assert pm.active_id == DEFAULT_ID

    def test_delete_nonexistent_fails(self, pm):
        with pytest.raises(KeyError):
            pm.delete("nope")


class TestDuplicate:
    def test_duplicate_profile(self, pm):
        p = pm.create("source")
        dup = pm.duplicate(p.id, "copy", "A copy")
        assert dup.name == "copy"
        assert dup.id != p.id
        assert Path(dup.db_path).exists()

    def test_duplicate_nonexistent_fails(self, pm):
        with pytest.raises(KeyError):
            pm.duplicate("nope", "copy")


class TestRename:
    def test_rename_profile(self, pm):
        p = pm.create("old-name")
        pm.rename(p.id, "new-name")
        updated = pm.get(p.id)
        assert updated.name == "new-name"

    def test_rename_default_fails(self, pm):
        with pytest.raises(ValueError, match="default"):
            pm.rename(DEFAULT_ID, "other")

    def test_rename_to_existing_name_fails(self, pm):
        a = pm.create("a")
        pm.create("b")
        with pytest.raises(ValueError, match="already in use"):
            pm.rename(a.id, "b")

    def test_rename_keeps_same_id(self, pm):
        p = pm.create("original")
        pm.rename(p.id, "renamed")
        assert pm.get(p.id) is not None
        assert pm.get(p.id).name == "renamed"


class TestGet:
    def test_get_existing(self, pm):
        p = pm.create("findme")
        found = pm.get(p.id)
        assert found is not None
        assert found.name == "findme"

    def test_get_nonexistent(self, pm):
        assert pm.get("nope") is None

    def test_get_default(self, pm):
        p = pm.get(DEFAULT_ID)
        assert p is not None
        assert p.is_default is True


class TestDataDir:
    def test_default_uses_root_dir(self, pm, tmp_path):
        assert pm.active_data_dir == tmp_path

    def test_other_profile_uses_profile_dir(self, pm, tmp_path):
        p = pm.create("test")
        pm.switch(p.id)
        assert pm.active_data_dir == tmp_path / "profiles" / p.id


class TestMigration:
    def test_legacy_profiles_get_ids(self, tmp_path, monkeypatch):
        """Old profiles without UUIDs get migrated."""
        config = {
            "active": "default",
            "profiles": {
                "default": {"name": "default", "db_path": str(tmp_path / "data.db"),
                            "created_at": 1.0, "is_default": True},
                "Kalle": {"name": "Kalle", "db_path": str(tmp_path / "profiles/Kalle/data.db"),
                           "created_at": 2.0, "is_default": False},
            }
        }
        config_file = tmp_path / "profiles.json"
        config_file.write_text(json.dumps(config))

        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", config_file)
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

        pm = ProfileManager()
        profiles = pm.list()

        # Default should keep "default" as ID
        default = next(p for p in profiles if p.is_default)
        assert default.id == DEFAULT_ID

        # Kalle should have a UUID id, name preserved
        kalle = next(p for p in profiles if p.name == "Kalle")
        assert kalle.id != "Kalle"
        assert len(kalle.id) == 8
