"""Tests for the Telegram connector with mocked API."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.connectors.telegram import TelegramConnector, _api_call, _format_date, _safe_key
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


@pytest.fixture
def connector(tmp_path):
    c = TelegramConnector(data_dir=tmp_path)
    c.configure({"bot_token": "123:ABC"})
    return c


MOCK_UPDATES = [
    {
        "update_id": 100,
        "message": {
            "message_id": 1,
            "chat": {"id": -1001, "title": "Test Group"},
            "from": {"first_name": "Alice", "last_name": "Smith", "username": "alice"},
            "date": 1700000000,
            "text": "Hello from Telegram!",
        },
    },
    {
        "update_id": 101,
        "message": {
            "message_id": 2,
            "chat": {"id": -1001, "title": "Test Group"},
            "from": {"first_name": "Bob"},
            "date": 1700000100,
            "text": "Reply message",
        },
    },
    {
        "update_id": 102,
        "message": {
            "message_id": 3,
            "chat": {"id": -1001, "title": "Test Group"},
            "from": {"username": "noname"},
            "date": 1700000200,
            "photo": [{"file_id": "x"}],
            "caption": "Photo caption",
        },
    },
]


class TestHelpers:
    def test_format_date(self):
        result = _format_date(1700000000)
        assert "2023" in result

    def test_safe_key(self):
        assert _safe_key("Hello World!") == "Hello_World_"
        assert len(_safe_key("x" * 100)) <= 80


class TestTelegramConnector:
    def test_not_configured(self, tmp_path):
        c = TelegramConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured(self, connector):
        assert connector.configured

    def test_config_schema(self, connector):
        schema = connector.config_schema()
        names = [f.name for f in schema]
        assert "bot_token" in names

    def test_get_chat_ids_empty(self, connector):
        assert connector._get_chat_ids() == []

    def test_get_chat_ids(self, connector):
        connector._config["chat_ids"] = "-1001, -1002"
        assert connector._get_chat_ids() == ["-1001", "-1002"]

    @patch("src.connectors.telegram._api_call")
    def test_test_connection_ok(self, mock_api, connector):
        mock_api.return_value = {"first_name": "TestBot", "username": "testbot"}
        result = connector.test_connection()
        assert result["ok"] is True
        assert result["bot_username"] == "testbot"

    def test_test_connection_no_token(self, tmp_path):
        c = TelegramConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    @patch("src.connectors.telegram._api_call")
    def test_test_connection_error(self, mock_api, connector):
        mock_api.side_effect = ConnectionError("fail")
        result = connector.test_connection()
        assert result["ok"] is False

    @patch("src.connectors.telegram._api_call")
    def test_sync(self, mock_api, connector, store):
        mock_api.return_value = MOCK_UPDATES
        result = connector.sync(store)
        assert result.added >= 2
        assert result.errors == []

    def test_sync_no_token(self, tmp_path, store):
        c = TelegramConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["No bot token configured"]

    @patch("src.connectors.telegram._api_call")
    def test_sync_api_error(self, mock_api, connector, store):
        mock_api.side_effect = ConnectionError("network")
        result = connector.sync(store)
        assert len(result.errors) >= 1

    @patch("src.connectors.telegram._api_call")
    def test_sync_with_chat_filter(self, mock_api, connector, store):
        connector._config["chat_ids"] = "-9999"
        mock_api.return_value = MOCK_UPDATES
        result = connector.sync(store)
        assert result.skipped >= 2

    @patch("src.connectors.telegram._api_call")
    def test_sync_media_caption(self, mock_api, connector, store):
        mock_api.return_value = MOCK_UPDATES
        result = connector.sync(store)
        mems = store.list()
        captions = [m for m in mems if "caption" in m.value.lower()]
        assert len(captions) >= 1

    @patch("src.connectors.telegram._api_call")
    def test_sync_media_no_text(self, mock_api, connector, store):
        updates = [{
            "update_id": 200,
            "message": {
                "message_id": 10,
                "chat": {"id": -5, "title": "Media Chat"},
                "from": {"first_name": "Carol"},
                "date": 1700001000,
                "video": {"file_id": "v123"},
            },
        }]
        connector._config["include_media_captions"] = True
        mock_api.return_value = updates
        result = connector.sync(store)
        assert result.added >= 1
        mem = list(store.list())[0]
        assert "[video]" in mem.value

    @patch("src.connectors.telegram._api_call")
    def test_sync_empty_message_skipped(self, mock_api, connector, store):
        updates = [{
            "update_id": 300,
            "message": {
                "message_id": 20,
                "chat": {"id": -10, "title": "Empty"},
                "from": {"first_name": "Dave"},
                "date": 1700002000,
            },
        }]
        mock_api.return_value = updates
        result = connector.sync(store)
        assert result.added == 0
