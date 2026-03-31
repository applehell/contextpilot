"""Tests for src.storage.settings — JSON settings persistence."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.storage.settings import (
    get_last_project,
    load_settings,
    save_settings,
    set_last_project,
)


@pytest.fixture
def settings_dir(tmp_path):
    settings_file = tmp_path / "settings.json"
    with patch("src.storage.settings._settings_path", return_value=settings_file):
        yield settings_file


class TestLoadSettings:
    def test_nonexistent_file_returns_empty(self, settings_dir) -> None:
        assert load_settings() == {}

    def test_corrupt_json_returns_empty(self, settings_dir) -> None:
        settings_dir.write_text("{invalid json", encoding="utf-8")
        assert load_settings() == {}

    def test_valid_json(self, settings_dir) -> None:
        settings_dir.write_text('{"key": "value"}', encoding="utf-8")
        result = load_settings()
        assert result == {"key": "value"}


class TestSaveSettings:
    def test_roundtrip(self, settings_dir) -> None:
        data = {"theme": "dark", "interval": 30}
        save_settings(data)
        loaded = load_settings()
        assert loaded == data

    def test_overwrites_existing(self, settings_dir) -> None:
        save_settings({"a": 1})
        save_settings({"b": 2})
        loaded = load_settings()
        assert loaded == {"b": 2}


class TestLastProject:
    def test_get_returns_none_initially(self, settings_dir) -> None:
        assert get_last_project() is None

    def test_set_and_get_roundtrip(self, settings_dir) -> None:
        set_last_project("/path/to/project.db")
        assert get_last_project() == "/path/to/project.db"

    def test_set_preserves_other_settings(self, settings_dir) -> None:
        save_settings({"theme": "dark"})
        set_last_project("/db.sqlite")
        loaded = load_settings()
        assert loaded["theme"] == "dark"
        assert loaded["last_project_db"] == "/db.sqlite"
