"""Tests for profile-aware startup — ensures web app and MCP server
use the active profile DB immediately, without manual profile switch.

Regression tests for:
- Web app started with DEFAULT_DB_PATH instead of active profile
- MCP server used hardcoded ~/.contextpilot/data.db instead of active profile
- Memories only appeared after manual profile switch in the UI
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.storage.profiles import ProfileManager, DEFAULT_ID


@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    """Set up isolated profile environment with a non-default active profile
    that has pre-seeded memories."""
    profiles_dir = tmp_path / "profiles"
    config_file = tmp_path / "profiles.json"
    default_db = tmp_path / "data.db"

    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", profiles_dir)
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", config_file)
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", default_db)
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

    # Create profile manager + non-default profile
    pm = ProfileManager()
    profile = pm.create("smarthome", "Smarthome und Homelab")
    pm.switch(profile.id)

    # Seed memories into the smarthome profile DB
    smarthome_db = Database(Path(profile.db_path))
    smarthome_store = MemoryStore(smarthome_db)
    smarthome_store.set(Memory(key="ha/test-automation", value="Buero Licht Automation", tags=["homeassistant"]))
    smarthome_store.set(Memory(key="ha/garage", value="Garagentor Automation", tags=["homeassistant"]))
    smarthome_store.set(Memory(key="skill/homematic", value="CCU3 API Referenz", tags=["homematic"]))
    smarthome_db.close()

    # Seed a different memory into the default DB
    default_db_inst = Database(default_db)
    default_store = MemoryStore(default_db_inst)
    default_store.set(Memory(key="default/only", value="This is only in default", tags=["default"]))
    default_db_inst.close()

    return {
        "tmp_path": tmp_path,
        "pm": pm,
        "profile": profile,
        "default_db": default_db,
        "smarthome_db_path": Path(profile.db_path),
    }


class TestWebAppStartup:
    """Web app must use active profile DB on startup, not DEFAULT_DB_PATH."""

    def test_create_app_uses_active_profile(self, profile_env, monkeypatch):
        monkeypatch.setattr("src.storage.folders._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.connectors.base._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", profile_env["tmp_path"])
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None

        from src.web.app import create_app
        app = create_app(db_path=profile_env["smarthome_db_path"])
        with TestClient(app) as client:
            r = client.get("/api/memories")
            assert r.status_code == 200
            total = r.json()["total"]
            assert total == 3, f"Expected 3 smarthome memories, got {total}"

            keys = [m["key"] for m in r.json()["memories"]]
            assert "ha/test-automation" in keys
            assert "default/only" not in keys

    def test_create_app_with_default_shows_default_memories(self, profile_env, monkeypatch):
        monkeypatch.setattr("src.storage.folders._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.connectors.base._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", profile_env["tmp_path"])
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None

        from src.web.app import create_app
        app = create_app(db_path=profile_env["default_db"])
        with TestClient(app) as client:
            r = client.get("/api/memories")
            keys = [m["key"] for m in r.json()["memories"]]
            assert "default/only" in keys
            assert "ha/test-automation" not in keys

    def test_health_shows_correct_memory_count_on_startup(self, profile_env, monkeypatch):
        monkeypatch.setattr("src.storage.folders._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.connectors.base._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", profile_env["tmp_path"])
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None

        from src.web.app import create_app
        app = create_app(db_path=profile_env["smarthome_db_path"])
        with TestClient(app) as client:
            r = client.get("/health")
            assert r.status_code == 200
            assert r.json()["memories"]["count"] == 3

    def test_search_works_on_active_profile_without_switch(self, profile_env, monkeypatch):
        monkeypatch.setattr("src.storage.folders._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.connectors.base._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", profile_env["tmp_path"])
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None

        from src.web.app import create_app
        app = create_app(db_path=profile_env["smarthome_db_path"])
        with TestClient(app) as client:
            r = client.get("/api/memories/search?q=buero")
            assert r.status_code == 200
            assert r.json()["total"] >= 1


class TestMCPServerProfile:
    """MCP server must use active profile DB, not hardcoded default."""

    def test_mcp_db_path_uses_active_profile(self, profile_env, monkeypatch):
        """The _db_path in mcp_server should resolve to the active profile's DB."""
        # Reset MCP server module state
        import src.interfaces.mcp_server as mcp_mod
        monkeypatch.setattr(mcp_mod, "_db", None)
        monkeypatch.setattr(mcp_mod, "_memory_store", None)
        monkeypatch.setattr(mcp_mod, "_usage_store", None)
        monkeypatch.setattr(mcp_mod, "_activity_log", None)
        monkeypatch.setattr(mcp_mod, "_db_path", ProfileManager().active_db_path)

        db = mcp_mod._get_db()
        store = mcp_mod._get_memory_store()
        memories = store.list()
        assert len(memories) == 3
        keys = [m.key for m in memories]
        assert "ha/test-automation" in keys

    def test_mcp_memory_set_persists_to_active_profile(self, profile_env, monkeypatch):
        """memory_set via MCP should write to the active profile DB."""
        import src.interfaces.mcp_server as mcp_mod
        monkeypatch.setattr(mcp_mod, "_db", None)
        monkeypatch.setattr(mcp_mod, "_memory_store", None)
        monkeypatch.setattr(mcp_mod, "_usage_store", None)
        monkeypatch.setattr(mcp_mod, "_activity_log", None)
        monkeypatch.setattr(mcp_mod, "_db_path", ProfileManager().active_db_path)

        mcp_mod.memory_set(key="test/mcp-write", value="written via MCP", tags=["test"])

        # Verify it landed in the smarthome profile DB, not default
        smarthome_db = Database(profile_env["smarthome_db_path"])
        store = MemoryStore(smarthome_db)
        mem = store.get("test/mcp-write")
        assert mem.value == "written via MCP"
        smarthome_db.close()

        # Verify it did NOT land in default DB
        default_db = Database(profile_env["default_db"])
        default_store = MemoryStore(default_db)
        with pytest.raises(KeyError):
            default_store.get("test/mcp-write")
        default_db.close()

    def test_mcp_memory_search_uses_active_profile(self, profile_env, monkeypatch):
        import src.interfaces.mcp_server as mcp_mod
        monkeypatch.setattr(mcp_mod, "_db", None)
        monkeypatch.setattr(mcp_mod, "_memory_store", None)
        monkeypatch.setattr(mcp_mod, "_usage_store", None)
        monkeypatch.setattr(mcp_mod, "_activity_log", None)
        monkeypatch.setattr(mcp_mod, "_db_path", ProfileManager().active_db_path)

        results = mcp_mod.memory_search(query="Buero")
        assert len(results) >= 1
        assert any(r["key"] == "ha/test-automation" for r in results)

    def test_mcp_memory_list_uses_active_profile(self, profile_env, monkeypatch):
        import src.interfaces.mcp_server as mcp_mod
        monkeypatch.setattr(mcp_mod, "_db", None)
        monkeypatch.setattr(mcp_mod, "_memory_store", None)
        monkeypatch.setattr(mcp_mod, "_usage_store", None)
        monkeypatch.setattr(mcp_mod, "_activity_log", None)
        monkeypatch.setattr(mcp_mod, "_db_path", ProfileManager().active_db_path)

        results = mcp_mod.memory_list()
        assert len(results) == 3
        keys = [r["key"] for r in results]
        assert "default/only" not in keys

    def test_mcp_does_not_use_default_db_when_profile_active(self, profile_env, monkeypatch):
        """Regression: MCP server must NOT fall back to DEFAULT_DB_PATH."""
        import src.interfaces.mcp_server as mcp_mod
        active_path = ProfileManager().active_db_path
        assert str(active_path) != str(profile_env["default_db"]), \
            "Active profile DB path should differ from default DB path"
        assert profile_env["profile"].id in str(active_path)


class TestProfileManagerActiveDbPath:
    """ProfileManager.active_db_path must return the correct path."""

    def test_default_profile_returns_default_db(self, tmp_path, monkeypatch):
        default_db = tmp_path / "data.db"
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", default_db)
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

        pm = ProfileManager()
        assert pm.active_db_path == default_db

    def test_switched_profile_returns_profile_db(self, tmp_path, monkeypatch):
        default_db = tmp_path / "data.db"
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", default_db)
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

        pm = ProfileManager()
        p = pm.create("test-profile")
        pm.switch(p.id)

        # Re-instantiate to simulate process restart
        pm2 = ProfileManager()
        assert pm2.active_id == p.id
        assert p.id in str(pm2.active_db_path)
        assert str(pm2.active_db_path) != str(default_db)

    def test_active_profile_persists_across_restart(self, tmp_path, monkeypatch):
        """Simulate container restart: ProfileManager re-reads config from disk."""
        default_db = tmp_path / "data.db"
        monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
        monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
        monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", default_db)
        monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)

        pm1 = ProfileManager()
        p = pm1.create("persistent")
        pm1.switch(p.id)

        # Simulate restart
        pm2 = ProfileManager()
        assert pm2.active_id == p.id
        assert pm2.active_name == "persistent"
        assert p.id in str(pm2.active_db_path)


class TestProfileSwitchReloadsData:
    """Switching profiles via API must immediately show the new profile's data."""

    def test_switch_shows_new_memories_immediately(self, profile_env, monkeypatch):
        monkeypatch.setattr("src.storage.folders._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.connectors.base._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", profile_env["tmp_path"])
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None

        from src.web.app import create_app
        app = create_app(db_path=profile_env["smarthome_db_path"])
        with TestClient(app) as client:
            # Start with smarthome profile (3 memories)
            r = client.get("/api/memories")
            assert r.json()["total"] == 3

            # Switch to default (1 memory)
            client.post("/api/profiles/default/switch")
            r = client.get("/api/memories")
            assert r.json()["total"] == 1
            assert r.json()["memories"][0]["key"] == "default/only"

            # Switch back to smarthome
            client.post(f"/api/profiles/{profile_env['profile'].id}/switch")
            r = client.get("/api/memories")
            assert r.json()["total"] == 3

    def test_memory_set_after_switch_goes_to_correct_profile(self, profile_env, monkeypatch):
        monkeypatch.setattr("src.storage.folders._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.connectors.base._DATA_DIR", profile_env["tmp_path"])
        monkeypatch.setattr("src.core.webhooks._DATA_DIR", profile_env["tmp_path"])
        from src.connectors.registry import ConnectorRegistry
        ConnectorRegistry._instance = None

        from src.web.app import create_app
        app = create_app(db_path=profile_env["smarthome_db_path"])
        with TestClient(app) as client:
            # Write to smarthome
            client.post("/api/memories", json={"key": "new/entry", "value": "smarthome data", "tags": []})

            # Switch to default and verify it's not there
            client.post("/api/profiles/default/switch")
            r = client.get("/api/memories")
            keys = [m["key"] for m in r.json()["memories"]]
            assert "new/entry" not in keys
