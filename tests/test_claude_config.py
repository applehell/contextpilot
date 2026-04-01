"""Tests for src.core.claude_config — atomic config write, register/deregister MCP."""
from __future__ import annotations

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from src.core import claude_config


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    config_path = tmp_path / ".claude.json"
    monkeypatch.setattr(claude_config, "CLAUDE_CONFIG", config_path)
    yield config_path


class TestRegisterMcp:
    def test_register_sse(self, isolate_config):
        claude_config.register_mcp(port=9999, transport="sse")
        data = json.loads(isolate_config.read_text())
        entry = data["mcpServers"]["context-pilot"]
        assert entry["type"] == "sse"
        assert entry["url"] == "http://localhost:9999/sse"

    def test_register_streamable_http(self, isolate_config):
        claude_config.register_mcp(port=9999, transport="streamable-http")
        data = json.loads(isolate_config.read_text())
        entry = data["mcpServers"]["context-pilot"]
        assert entry["type"] == "url"
        assert entry["url"] == "http://localhost:9999/mcp"

    def test_register_overwrites_existing(self, isolate_config):
        claude_config.register_mcp(port=1111)
        claude_config.register_mcp(port=2222)
        data = json.loads(isolate_config.read_text())
        assert "2222" in data["mcpServers"]["context-pilot"]["url"]


class TestDeregisterMcp:
    def test_deregister_removes_entry(self, isolate_config):
        claude_config.register_mcp()
        assert claude_config.is_registered()
        claude_config.deregister_mcp()
        assert not claude_config.is_registered()

    def test_deregister_noop_when_not_registered(self, isolate_config):
        claude_config.deregister_mcp()  # should not raise


class TestIsRegistered:
    def test_false_when_no_config(self, isolate_config):
        assert not claude_config.is_registered()

    def test_true_after_register(self, isolate_config):
        claude_config.register_mcp()
        assert claude_config.is_registered()


class TestGetCurrentConfig:
    def test_none_when_not_registered(self, isolate_config):
        assert claude_config.get_current_config() is None

    def test_returns_config_after_register(self, isolate_config):
        claude_config.register_mcp(port=8400)
        cfg = claude_config.get_current_config()
        assert cfg is not None
        assert cfg["type"] == "sse"


class TestRemoveStdioEntry:
    def test_removes_stdio_entry(self, isolate_config):
        config = {"mcpServers": {"context-pilot": {"type": "stdio", "command": "foo"}}}
        isolate_config.write_text(json.dumps(config))
        assert claude_config.remove_stdio_entry() is True
        assert not claude_config.is_registered()

    def test_noop_for_sse_entry(self, isolate_config):
        claude_config.register_mcp()
        assert claude_config.remove_stdio_entry() is False
        assert claude_config.is_registered()

    def test_noop_when_no_entry(self, isolate_config):
        assert claude_config.remove_stdio_entry() is False


class TestAtomicWrite:
    def test_no_partial_write_on_error(self, isolate_config, monkeypatch):
        claude_config.register_mcp(port=8400)
        original = isolate_config.read_text()

        def bad_dump(*args, **kwargs):
            raise IOError("disk full")

        monkeypatch.setattr(json, "dump", bad_dump)
        with pytest.raises(IOError):
            claude_config.register_mcp(port=9999)

        # Original file should be unchanged
        assert isolate_config.read_text() == original
