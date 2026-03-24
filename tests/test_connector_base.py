"""Tests for ConnectorPlugin base class and ConnectorRegistry."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.connectors.base import ConfigField, ConnectorPlugin, SyncResult
from src.connectors.registry import ConnectorRegistry
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore


# --- Minimal test connector ---

class DummyConnector(ConnectorPlugin):
    name = "dummy"
    display_name = "Dummy Connector"
    description = "A test connector"
    icon = "D"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("url", "URL", required=True, placeholder="http://example.com"),
            ConfigField("token", "Token", type="password", required=True),
            ConfigField("tags", "Tags", type="tags"),
        ]

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        return {"ok": True, "items": 42}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r
        store.set(Memory(key=f"{self.name}/1", value="test content", tags=["dummy"]))
        result = SyncResult(added=1, total_remote=1)
        self._update_sync_stats(1)
        return result


@pytest.fixture
def connector(tmp_path, monkeypatch):
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    return DummyConnector()


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    return MemoryStore(db)


class TestConfigField:
    def test_to_dict(self):
        f = ConfigField("url", "URL", type="text", placeholder="http://...", required=True, default="")
        d = f.to_dict()
        assert d["name"] == "url"
        assert d["label"] == "URL"
        assert d["type"] == "text"
        assert d["required"] is True


class TestSyncResult:
    def test_to_dict(self):
        r = SyncResult(added=3, updated=1, removed=2, skipped=5, total_remote=11, errors=["oops"])
        d = r.to_dict()
        assert d["added"] == 3
        assert d["total_remote"] == 11
        assert d["errors"] == ["oops"]

    def test_defaults(self):
        r = SyncResult()
        assert r.added == 0
        assert r.errors == []


class TestConnectorLifecycle:
    def test_not_configured_initially(self, connector):
        assert connector.configured is False
        assert connector.enabled is True

    def test_configure(self, connector):
        connector.configure({"url": "http://test", "token": "secret"})
        assert connector.configured is True
        assert connector._config["url"] == "http://test"
        assert connector._config["token"] == "secret"

    def test_configure_persists(self, connector, tmp_path, monkeypatch):
        connector.configure({"url": "http://test", "token": "s"})
        # Create a new instance — should load saved config
        monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
        c2 = DummyConnector()
        assert c2.configured is True
        assert c2._config["url"] == "http://test"

    def test_update(self, connector):
        connector.configure({"url": "http://old", "token": "t"})
        connector.update({"url": "http://new"})
        assert connector._config["url"] == "http://new"
        assert connector._config["token"] == "t"  # unchanged

    def test_set_enabled(self, connector):
        connector.configure({"url": "http://test", "token": "t"})
        connector.set_enabled(False)
        assert connector.enabled is False
        connector.set_enabled(True)
        assert connector.enabled is True

    def test_remove(self, connector):
        connector.configure({"url": "http://test", "token": "t"})
        connector.remove()
        assert connector.configured is False
        assert not connector._config_path.exists()

    def test_test_connection_not_configured(self, connector):
        result = connector.test_connection()
        assert result["ok"] is False

    def test_test_connection_configured(self, connector):
        connector.configure({"url": "http://test", "token": "t"})
        result = connector.test_connection()
        assert result["ok"] is True
        assert result["items"] == 42


class TestGetStatus:
    def test_status_unconfigured(self, connector):
        s = connector.get_status()
        assert s["name"] == "dummy"
        assert s["display_name"] == "Dummy Connector"
        assert s["configured"] is False
        assert len(s["schema"]) == 3

    def test_status_configured_masks_password(self, connector):
        connector.configure({"url": "http://test", "token": "secret123"})
        s = connector.get_status()
        assert s["configured"] is True
        assert s["config"]["url"] == "http://test"
        assert s["config"]["token"] == "••••••••"  # masked

    def test_status_has_sync_stats(self, connector, store):
        connector.configure({"url": "http://test", "token": "t"})
        connector.sync(store)
        s = connector.get_status()
        assert s["synced_count"] == 1
        assert s["last_sync"] is not None


class TestSyncAndPurge:
    def test_sync_not_configured(self, connector, store):
        result = connector.sync(store)
        assert result.errors == ["Not configured"]

    def test_sync_creates_memories(self, connector, store):
        connector.configure({"url": "http://test", "token": "t"})
        result = connector.sync(store)
        assert result.added == 1
        assert store.get("dummy/1").value == "test content"

    def test_purge(self, connector, store):
        connector.configure({"url": "http://test", "token": "t"})
        connector.sync(store)
        count = connector.purge(store)
        assert count == 1
        assert len(store.list()) == 0

    def test_purge_only_own_prefix(self, connector, store):
        connector.configure({"url": "http://test", "token": "t"})
        connector.sync(store)
        store.set(Memory(key="other/key", value="unrelated"))
        count = connector.purge(store)
        assert count == 1
        assert len(store.list()) == 1  # "other/key" remains


class TestRegistry:
    def test_discovers_paperless(self):
        reg = ConnectorRegistry()
        names = reg.names()
        assert "paperless" in names

    def test_get_existing(self):
        reg = ConnectorRegistry()
        c = reg.get("paperless")
        assert c is not None
        assert c.display_name == "Paperless-ngx"

    def test_get_nonexistent(self):
        reg = ConnectorRegistry()
        assert reg.get("nonexistent") is None

    def test_list_returns_plugins(self):
        reg = ConnectorRegistry()
        plugins = reg.list()
        assert len(plugins) >= 1
        assert all(hasattr(p, "name") for p in plugins)

    def test_singleton(self):
        a = ConnectorRegistry.instance()
        b = ConnectorRegistry.instance()
        assert a is b
