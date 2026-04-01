"""Tests for H8: ZIP path traversal protection in profile import."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.storage.profiles import ProfileManager, PROFILES_DIR, _DATA_DIR


@pytest.fixture(autouse=True)
def _isolate_profiles(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.storage.profiles._DATA_DIR", tmp_path)
    monkeypatch.setattr("src.storage.profiles.PROFILES_DIR", tmp_path / "profiles")
    monkeypatch.setattr("src.storage.profiles.CONFIG_FILE", tmp_path / "profiles.json")
    monkeypatch.setattr("src.storage.profiles.DEFAULT_DB", tmp_path / "data.db")
    ProfileManager.invalidate()


def _make_zip(entries: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


def test_traversal_entry_is_skipped(tmp_path: Path) -> None:
    meta = json.dumps({"name": "evil_profile", "description": "test"})
    zip_data = _make_zip({
        "profile.json": meta,
        "../../evil.txt": "MALICIOUS CONTENT",
        "connector_rss.json": '{"ok": true}',
    })
    mgr = ProfileManager()
    profile = mgr.import_profile(zip_data)

    profile_dir = tmp_path / "profiles" / profile.id
    assert (profile_dir / "connector_rss.json").exists()

    evil_path = (tmp_path / "evil.txt")
    assert not evil_path.exists(), "Path traversal entry should have been skipped"

    evil_in_profiles = (tmp_path / "profiles" / "evil.txt")
    assert not evil_in_profiles.exists()


def test_normal_entries_still_extracted(tmp_path: Path) -> None:
    meta = json.dumps({"name": "normal", "description": ""})
    zip_data = _make_zip({
        "profile.json": meta,
        "connector_email.json": '{"host": "imap.example.com"}',
        "webhooks.json": '{"hooks": {}}',
    })
    mgr = ProfileManager()
    profile = mgr.import_profile(zip_data)
    profile_dir = tmp_path / "profiles" / profile.id
    assert (profile_dir / "connector_email.json").exists()
    assert (profile_dir / "webhooks.json").exists()
