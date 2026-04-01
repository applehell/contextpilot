"""Tests for H1: connector config file permissions after save."""
from __future__ import annotations

import os
import platform
import stat
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.connectors.base import ConfigField, ConnectorPlugin, SyncResult
from src.storage.memory import MemoryStore


class _MinimalConnector(ConnectorPlugin):
    name = "permtest"
    display_name = "Permission Test"

    def config_schema(self) -> List[ConfigField]:
        return [ConfigField("token", "Token", type="password")]

    def test_connection(self) -> Dict[str, Any]:
        return {"ok": True}

    def sync(self, store: MemoryStore) -> SyncResult:
        return SyncResult()


def test_save_sets_permissions_0600(tmp_path: Path) -> None:
    conn = _MinimalConnector(data_dir=tmp_path)
    conn.configure({"token": "secret123"})
    cfg = tmp_path / "connector_permtest.json"
    assert cfg.exists()
    mode = cfg.stat().st_mode & 0o777
    assert mode == 0o600, f"Expected 0600, got {oct(mode)}"


def test_save_after_update_keeps_permissions(tmp_path: Path) -> None:
    conn = _MinimalConnector(data_dir=tmp_path)
    conn.configure({"token": "secret"})
    conn.update({"token": "new_secret"})
    cfg = tmp_path / "connector_permtest.json"
    mode = cfg.stat().st_mode & 0o777
    assert mode == 0o600
