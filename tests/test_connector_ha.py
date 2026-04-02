"""Tests for the Home Assistant connector with mocked API."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.connectors.homeassistant import HomeAssistantConnector, _HAAPI
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


@pytest.fixture
def connector(tmp_path):
    c = HomeAssistantConnector(data_dir=tmp_path)
    c.configure({"url": "http://localhost:8123", "token": "eyJtest"})
    return c


MOCK_STATES = [
    {"entity_id": "automation.lights_on", "state": "on", "attributes": {
        "friendly_name": "Lights On at Sunset",
        "last_triggered": "2025-01-01T18:00:00",
        "current": "idle",
    }},
    {"entity_id": "automation.heating", "state": "off", "attributes": {
        "friendly_name": "Heating Schedule",
    }},
    {"entity_id": "scene.movie_time", "state": "scening", "attributes": {
        "friendly_name": "Movie Time",
        "area": "Living Room",
    }},
    {"entity_id": "script.backup", "state": "off", "attributes": {
        "friendly_name": "Daily Backup",
    }},
    {"entity_id": "light.kitchen", "state": "on", "attributes": {
        "friendly_name": "Kitchen Light",
    }},
]

MOCK_CONFIG = {"location_name": "Home", "version": "2025.1.0"}


class TestHAConnector:
    def test_not_configured(self, tmp_path):
        c = HomeAssistantConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured(self, connector):
        assert connector.configured

    def test_config_schema(self, connector):
        schema = connector.config_schema()
        assert len(schema) >= 2
        names = [f.name for f in schema]
        assert "url" in names
        assert "token" in names

    def test_test_connection_not_configured(self, tmp_path):
        c = HomeAssistantConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    @patch.object(_HAAPI, "_get")
    def test_test_connection_ok(self, mock_get, connector):
        def side_effect(path):
            if path == "/api/config":
                return MOCK_CONFIG
            if path == "/api/states":
                return MOCK_STATES
        mock_get.side_effect = side_effect
        result = connector.test_connection()
        assert result["ok"] is True
        assert result["location"] == "Home"
        assert result["entity_count"] == len(MOCK_STATES)

    @patch.object(_HAAPI, "_get")
    def test_test_connection_error(self, mock_get, connector):
        mock_get.side_effect = ConnectionError("refused")
        result = connector.test_connection()
        assert result["ok"] is False

    @patch.object(_HAAPI, "_get")
    def test_sync(self, mock_get, connector, store):
        mock_get.return_value = MOCK_STATES
        result = connector.sync(store)
        assert result.added >= 3  # 2 automations + 1 scene + 1 script
        assert result.errors == []
        keys = [m.key for m in store.list()]
        assert any("automation.lights_on" in k for k in keys)

    @patch.object(_HAAPI, "_get")
    def test_sync_updates(self, mock_get, connector, store):
        mock_get.return_value = MOCK_STATES
        connector.sync(store)
        updated_states = list(MOCK_STATES)
        updated_states[0] = dict(updated_states[0])
        updated_states[0]["state"] = "off"
        mock_get.return_value = updated_states
        result = connector.sync(store)
        assert result.updated >= 1

    @patch.object(_HAAPI, "_get")
    def test_sync_removes_deleted(self, mock_get, connector, store):
        mock_get.return_value = MOCK_STATES
        connector.sync(store)
        mock_get.return_value = MOCK_STATES[:1]  # Only first automation
        result = connector.sync(store)
        assert result.removed >= 1

    def test_sync_not_configured(self, tmp_path, store):
        c = HomeAssistantConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["Not configured"]

    @patch.object(_HAAPI, "_get")
    def test_sync_api_error(self, mock_get, connector, store):
        mock_get.side_effect = ConnectionError("network error")
        result = connector.sync(store)
        assert len(result.errors) >= 1

    @patch.object(_HAAPI, "_get")
    def test_sync_type_filter(self, mock_get, connector, store):
        connector._config["sync_types"] = "automations"
        mock_get.return_value = MOCK_STATES
        result = connector.sync(store)
        keys = [m.key for m in store.list()]
        assert all("automation" in k for k in keys)
        assert not any("scene" in k for k in keys)

    @patch.object(_HAAPI, "_get")
    def test_sync_with_area(self, mock_get, connector, store):
        mock_get.return_value = MOCK_STATES
        connector.sync(store)
        scene_mem = store.get("homeassistant/scene.movie_time")
        assert "living room" in scene_mem.tags
