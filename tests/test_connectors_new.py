"""Tests for new connectors (v3.5) and base class architecture features."""
from __future__ import annotations

import time
from typing import Any, Dict, List

import pytest

from src.connectors.base import ConfigField, ConnectorPlugin, SyncResult
from src.connectors.registry import ConnectorRegistry


VALID_CATEGORIES = {
    "Development",
    "Documents",
    "Smart Home",
    "Communication",
    "Knowledge",
    "Infrastructure",
}


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    return ConnectorRegistry(data_dir=tmp_path)


def _get_connector(registry: ConnectorRegistry, name: str) -> ConnectorPlugin:
    c = registry.get(name)
    assert c is not None, f"Connector '{name}' not found in registry"
    return c


# ---------------------------------------------------------------------------
# TestConnectorMetadata
# ---------------------------------------------------------------------------

class TestConnectorMetadata:
    def test_all_connectors_have_category(self, registry):
        for c in registry.list():
            assert c.category, f"{c.name}: category is empty"
            assert c.category != "Other", f"{c.name}: category is still default 'Other'"

    def test_all_connectors_have_setup_guide(self, registry):
        for c in registry.list():
            assert c.setup_guide, f"{c.name}: setup_guide is empty"

    def test_all_connectors_have_color(self, registry):
        for c in registry.list():
            assert c.color, f"{c.name}: color is empty"

    def test_all_connectors_have_icon(self, registry):
        for c in registry.list():
            assert c.icon, f"{c.name}: icon is empty"

    def test_connector_count(self, registry):
        assert len(registry.list()) >= 17, (
            f"Expected at least 17 connectors, found {len(registry.list())}: "
            f"{registry.names()}"
        )

    def test_categories_are_valid(self, registry):
        for c in registry.list():
            assert c.category in VALID_CATEGORIES, (
                f"{c.name}: category '{c.category}' not in {VALID_CATEGORIES}"
            )


# ---------------------------------------------------------------------------
# TestRecordSync
# ---------------------------------------------------------------------------

class _StubConnector(ConnectorPlugin):
    name = "stub"
    display_name = "Stub"
    description = "stub"
    icon = "S"
    category = "Knowledge"
    setup_guide = "n/a"
    color = "#000"

    def config_schema(self) -> List[ConfigField]:
        return []

    def test_connection(self) -> Dict[str, Any]:
        return {"ok": True}

    def sync(self, store):
        return SyncResult()


@pytest.fixture
def stub(tmp_path, monkeypatch):
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    return _StubConnector()


class TestRecordSync:
    def test_record_sync_stores_history(self, stub):
        result = SyncResult(added=3, updated=1, removed=0, skipped=2, total_remote=6)
        stub._record_sync(result)

        history = stub._config.get("_sync_history", [])
        assert len(history) == 1
        entry = history[0]
        assert entry["added"] == 3
        assert entry["updated"] == 1
        assert entry["removed"] == 0
        assert entry["skipped"] == 2
        assert entry["errors"] == 0
        assert "timestamp" in entry

    def test_record_sync_limits_to_20(self, stub):
        for i in range(25):
            stub._record_sync(SyncResult(added=i))

        history = stub._config.get("_sync_history", [])
        assert len(history) == 20

    def test_record_sync_newest_first(self, stub):
        stub._record_sync(SyncResult(added=1))
        stub._record_sync(SyncResult(added=2))
        stub._record_sync(SyncResult(added=3))

        history = stub._config["_sync_history"]
        assert history[0]["added"] == 3
        assert history[1]["added"] == 2
        assert history[2]["added"] == 1
        assert history[0]["timestamp"] >= history[1]["timestamp"]

    def test_record_sync_stores_error_details(self, stub):
        errors = [f"error_{i}" for i in range(8)]
        result = SyncResult(errors=errors)
        stub._record_sync(result)

        entry = stub._config["_sync_history"][0]
        assert entry["errors"] == 8
        assert len(entry["error_details"]) == 5
        assert entry["error_details"][0] == "error_0"
        assert entry["error_details"][4] == "error_4"


# ---------------------------------------------------------------------------
# TestGetStatusExtended
# ---------------------------------------------------------------------------

class TestGetStatusExtended:
    def test_status_includes_category(self, stub):
        s = stub.get_status()
        assert "category" in s
        assert s["category"] == "Knowledge"

    def test_status_includes_setup_guide(self, stub):
        s = stub.get_status()
        assert "setup_guide" in s
        assert s["setup_guide"] == "n/a"

    def test_status_includes_color(self, stub):
        s = stub.get_status()
        assert "color" in s
        assert s["color"] == "#000"

    def test_status_includes_sync_history(self, stub):
        s = stub.get_status()
        assert "sync_history" in s
        assert isinstance(s["sync_history"], list)

        stub._record_sync(SyncResult(added=5))
        s = stub.get_status()
        assert len(s["sync_history"]) == 1

    def test_status_includes_error_count(self, stub):
        s = stub.get_status()
        assert "error_count" in s
        assert s["error_count"] == 0

        stub._record_sync(SyncResult(errors=["e1", "e2"]))
        stub._record_sync(SyncResult(errors=["e3"]))
        s = stub.get_status()
        assert s["error_count"] == 3


# ---------------------------------------------------------------------------
# Connector-specific tests
# ---------------------------------------------------------------------------

class TestRSSConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "rss")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "feed_urls" in names
        assert "max_items_per_feed" in names
        assert "include_content" in names

    def test_configure(self, conn):
        conn.configure({"feed_urls": "https://example.com/rss"})
        assert conn.configured is True


class TestTelegramConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "telegram")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "bot_token" in names
        assert "chat_ids" in names
        assert "message_limit" in names


class TestExcelConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "excel")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "directory_path" in names
        assert "file_pattern" in names
        assert "sheet_filter" in names


class TestNotionConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "notion")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "token" in names
        assert "database_ids" in names
        assert "sync_pages" in names
        assert "sync_databases" in names


class TestTeamsConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "teams")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "tenant_id" in names
        assert "client_id" in names
        assert "client_secret" in names


class TestGDriveConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "gdrive")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "service_account_json" in names
        assert "folder_id" in names
        assert "file_types" in names


class TestBitwardenConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "bitwarden")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "server_url" in names
        assert "client_id" in names
        assert "client_secret" in names


class TestKeePassConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "keepass")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "database_path" in names
        assert "password" in names
        assert "key_file" in names


class TestKubernetesConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "kubernetes")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "api_url" in names
        assert "token" in names
        assert "namespaces" in names
        assert "sync_items" in names


class TestDockgeConnector:
    @pytest.fixture
    def conn(self, registry):
        return _get_connector(registry, "dockge")

    def test_not_configured(self, conn):
        assert conn.configured is False

    def test_config_schema(self, conn):
        names = [f.name for f in conn.config_schema()]
        assert "stacks_dir" in names
        assert "dockge_url" in names
        assert "include_env" in names
