"""Tests for H4: Telegram offset persistence."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.connectors.telegram import TelegramConnector
from src.storage.db import Database
from src.storage.memory import MemoryStore


def _make_update(update_id: int, chat_id: int, text: str, msg_id: int) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": msg_id,
            "chat": {"id": chat_id, "title": "TestChat"},
            "from": {"first_name": "Alice"},
            "text": text,
            "date": 1700000000,
        },
    }


@pytest.fixture
def setup(tmp_path: Path):
    conn = TelegramConnector(data_dir=tmp_path)
    conn._config = {
        "_configured": True,
        "_enabled": True,
        "bot_token": "123:ABC",
        "chat_ids": "",
        "message_limit": 100,
        "include_media_captions": True,
        "ttl_days": 0,
    }
    db = Database(tmp_path / "test.db")
    store = MemoryStore(db)
    return conn, store, db, tmp_path


def test_offset_persisted_after_sync(setup) -> None:
    conn, store, db, tmp_path = setup
    updates = [_make_update(100, 1, "hello", 1), _make_update(101, 1, "world", 2)]

    with patch("src.connectors.telegram._api_call", return_value=updates):
        conn.sync(store)

    assert conn._config["_last_offset"] == 102
    db.close()


def test_offset_passed_to_api(setup) -> None:
    conn, store, db, tmp_path = setup
    conn._config["_last_offset"] = 50

    with patch("src.connectors.telegram._api_call", return_value=[]) as mock_api:
        conn.sync(store)
        call_args = mock_api.call_args
        params = call_args[0][2]
        assert params["offset"] == 50

    db.close()


def test_offset_increments_across_syncs(setup) -> None:
    conn, store, db, tmp_path = setup

    updates_1 = [_make_update(200, 1, "first", 10)]
    updates_2 = [_make_update(300, 1, "second", 11)]

    with patch("src.connectors.telegram._api_call", return_value=updates_1):
        conn.sync(store)
    assert conn._config["_last_offset"] == 201

    with patch("src.connectors.telegram._api_call", return_value=updates_2) as mock_api:
        conn.sync(store)
        params = mock_api.call_args[0][2]
        assert params["offset"] == 201

    assert conn._config["_last_offset"] == 301
    db.close()


def test_no_updates_offset_unchanged(setup) -> None:
    conn, store, db, tmp_path = setup
    conn._config["_last_offset"] = 42

    with patch("src.connectors.telegram._api_call", return_value=[]):
        conn.sync(store)

    assert conn._config["_last_offset"] == 42
    db.close()
