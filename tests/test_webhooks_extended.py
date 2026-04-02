"""Extended tests for WebhookManager — add, list, remove, notify."""
from __future__ import annotations

import pytest

from src.core.webhooks import WebhookManager


@pytest.fixture
def wm(tmp_path):
    return WebhookManager(tmp_path)


class TestWebhookManager:
    def test_empty_list(self, wm):
        assert wm.list() == []

    def test_add_and_list(self, wm):
        wm.add("test-hook", "generic", "http://example.com/hook")
        hooks = wm.list()
        assert len(hooks) == 1
        assert hooks[0].name == "test-hook"
        assert hooks[0].type == "generic"
        assert hooks[0].url == "http://example.com/hook"

    def test_add_with_events(self, wm):
        wm.add("filtered", "generic", "http://example.com/hook", events=["memory.create"])
        hooks = wm.list()
        assert hooks[0].events == ["memory.create"]

    def test_add_waha(self, wm):
        wm.add("waha-hook", "waha", "http://localhost:3000",
               chat_id="123456@c.us", session="default")
        hooks = wm.list()
        assert hooks[0].type == "waha"
        assert hooks[0].chat_id == "123456@c.us"

    def test_remove(self, wm):
        wm.add("removeme", "generic", "http://example.com/hook")
        wm.remove("removeme")
        assert wm.list() == []

    def test_remove_not_found(self, wm):
        with pytest.raises(KeyError):
            wm.remove("nonexistent")

    def test_notify_no_hooks(self, wm):
        results = wm.notify("test", "Hello!")
        assert results == []

    def test_notify_skips_filtered_events(self, wm):
        wm.add("filtered", "generic", "http://example.com/hook", events=["memory.create"])
        results = wm.notify("sync.error", "Something failed")
        assert results == []

    def test_persistence(self, tmp_path):
        wm1 = WebhookManager(tmp_path)
        wm1.add("persist", "generic", "http://example.com/hook")
        wm2 = WebhookManager(tmp_path)
        hooks = wm2.list()
        assert len(hooks) == 1
        assert hooks[0].name == "persist"

    def test_disable_hook(self, wm):
        wm.add("disabled", "generic", "http://example.com/hook")
        wm._config["hooks"]["disabled"]["enabled"] = False
        wm._save()
        hooks = wm.list()
        assert hooks[0].enabled is False
