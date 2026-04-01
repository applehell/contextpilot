"""Tests for K2: SSRF protection in webhooks and WebhookManager operations."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.core.webhooks import (
    WebhookManager,
    _validate_url,
    _BLOCKED_HOSTS,
)


class TestValidateUrl:

    def test_blocks_private_ipv4(self) -> None:
        for ip in ["192.168.1.1", "10.0.0.1", "172.16.0.1"]:
            with pytest.raises(ValueError, match="Blocked private address"):
                _validate_url(f"http://{ip}/hook")

    def test_blocks_loopback(self) -> None:
        with pytest.raises(ValueError, match="Blocked private address"):
            _validate_url("http://127.0.0.1/hook")

    def test_blocks_link_local(self) -> None:
        with pytest.raises(ValueError, match="Blocked private address"):
            _validate_url("http://169.254.1.1/hook")

    def test_blocks_metadata_hosts(self) -> None:
        for host in _BLOCKED_HOSTS:
            with pytest.raises(ValueError, match="Blocked host"):
                _validate_url(f"http://{host}/latest/meta-data")

    def test_blocks_non_http_scheme(self) -> None:
        with pytest.raises(ValueError, match="Blocked scheme"):
            _validate_url("ftp://example.com/file")
        with pytest.raises(ValueError, match="Blocked scheme"):
            _validate_url("file:///etc/passwd")

    def test_allows_valid_public_url(self) -> None:
        _validate_url("https://hooks.slack.com/services/T00/B00/xxx")
        _validate_url("http://example.com/webhook")

    def test_allows_public_ip(self) -> None:
        _validate_url("http://8.8.8.8/hook")


class TestWebhookManager:

    def test_add_list_remove(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        assert mgr.list() == []

        mgr.add("slack", "generic", "https://hooks.slack.com/x")
        hooks = mgr.list()
        assert len(hooks) == 1
        assert hooks[0].name == "slack"
        assert hooks[0].url == "https://hooks.slack.com/x"

        mgr.remove("slack")
        assert mgr.list() == []

    def test_remove_nonexistent_raises(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        with pytest.raises(KeyError):
            mgr.remove("nope")

    def test_add_persists(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        mgr.add("test", "generic", "https://example.com/hook")
        mgr2 = WebhookManager(data_dir=tmp_path)
        assert len(mgr2.list()) == 1

    def test_notify_filters_by_event(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        mgr.add("only_errors", "generic", "https://example.com/hook", events=["sync.error"])
        with patch("src.core.webhooks._send_generic") as mock_send:
            results = mgr.notify("sync.success", "all good")
            mock_send.assert_not_called()
            assert results == []

    def test_notify_calls_matching_hook(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        mgr.add("all", "generic", "https://example.com/hook")
        with patch("src.core.webhooks._send_generic") as mock_send:
            results = mgr.notify("sync.error", "something broke")
            mock_send.assert_called_once()
            assert results == [{"name": "all", "ok": True}]

    def test_notify_ssrf_blocked(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        mgr.add("evil", "generic", "http://169.254.169.254/latest")
        results = mgr.notify("test", "msg")
        assert len(results) == 1
        assert results[0]["ok"] is False
        assert "Blocked" in results[0]["error"]

    def test_save_file_permissions(self, tmp_path: Path) -> None:
        mgr = WebhookManager(data_dir=tmp_path)
        mgr.add("test", "generic", "https://example.com/hook")
        cfg = tmp_path / "webhooks.json"
        mode = cfg.stat().st_mode & 0o777
        assert mode == 0o600
