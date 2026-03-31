"""Tests for src.core.scheduler — SyncScheduler."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from src.core.scheduler import SyncScheduler


@pytest.fixture(autouse=True)
def reset_singleton():
    SyncScheduler._instance = None
    yield
    SyncScheduler._instance = None


class TestSingleton:
    def test_instance_returns_same_object(self) -> None:
        a = SyncScheduler.instance()
        b = SyncScheduler.instance()
        assert a is b

    def test_instance_accepts_interval(self) -> None:
        s = SyncScheduler.instance(interval_minutes=10)
        assert s.interval == 600


class TestStartStop:
    def test_initial_not_running(self) -> None:
        s = SyncScheduler()
        assert s.running is False

    def test_stop_sets_running_false(self) -> None:
        s = SyncScheduler()
        s._running = True
        s._task = MagicMock()
        s._task.cancel = MagicMock()
        s.stop()
        assert s.running is False
        assert s._task is None

    def test_stop_without_start(self) -> None:
        s = SyncScheduler()
        s.stop()  # should not raise
        assert s.running is False


class TestSetInterval:
    def test_set_interval(self) -> None:
        s = SyncScheduler(interval_minutes=10)
        assert s.interval == 600
        s.set_interval(5)
        assert s.interval == 300


class TestGetStatus:
    def test_status_fields(self) -> None:
        s = SyncScheduler(interval_minutes=15)
        status = s.get_status()
        assert status["running"] is False
        assert status["interval_minutes"] == 15
        assert status["last_run"] is None

    def test_status_after_running_change(self) -> None:
        s = SyncScheduler()
        s._running = True
        assert s.get_status()["running"] is True


class TestRunOnce:
    def test_run_once_calls_folder_manager(self) -> None:
        s = SyncScheduler()
        s._get_store = MagicMock()
        s._get_db = MagicMock()
        s._get_profile_dir = MagicMock(return_value="/tmp/test")

        mock_result = MagicMock()
        mock_result.added = 2
        mock_result.updated = 1
        mock_result.removed = 0

        with patch("src.storage.folders.FolderManager") as MockFM, \
             patch("src.connectors.registry.ConnectorRegistry") as MockCR:
            MockFM.return_value.scan_all.return_value = {"test_folder": mock_result}
            MockCR.instance.return_value.list.return_value = []

            results = asyncio.new_event_loop().run_until_complete(s.run_once())

        assert "test_folder" in results["folders"]
        assert results["folders"]["test_folder"]["added"] == 2
        assert s.last_run is not None

    def test_run_once_handles_folder_error(self) -> None:
        s = SyncScheduler()
        s._get_store = MagicMock()
        s._get_db = MagicMock()
        s._get_profile_dir = None

        with patch("src.storage.folders.FolderManager", side_effect=Exception("boom")):
            with patch("src.connectors.registry.ConnectorRegistry", side_effect=Exception("no conn")):
                results = asyncio.new_event_loop().run_until_complete(s.run_once())

        assert "_error" in results["folders"]
