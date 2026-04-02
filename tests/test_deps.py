"""Tests for web deps — shared state init, helpers, rate limiter."""
from __future__ import annotations

import time
import pytest

from src.storage.db import Database
from src.web.deps import (
    _estimate_total_tokens,
    _get_connector,
    _init_db,
    _make_assembler,
    _block_to_dict,
    _detect_compress_hint,
    block_hash,
)
from src.web.rate_limit import RateLimiter
from src.core.block import Block, Priority


class TestEstimateTotalTokens:
    def test_empty_db(self):
        db = Database(None)
        result = _estimate_total_tokens(db)
        assert result == 0

    def test_with_data(self):
        db = Database(None)
        from src.storage.memory import MemoryStore, Memory
        store = MemoryStore(db)
        store.set(Memory(key="tok/a", value="x" * 350, tags=[]))
        result = _estimate_total_tokens(db)
        assert result > 0


class TestInitDb:
    def test_init_db_none(self):
        _init_db(None)
        from src.web.deps import _db
        assert _db is not None

    def test_init_db_reinit(self):
        _init_db(None)
        _init_db(None)
        from src.web.deps import _db
        assert _db is not None


class TestMakeAssembler:
    def test_make_assembler(self):
        assembler = _make_assembler()
        assert assembler is not None


class TestBlockToDict:
    def test_block_to_dict(self):
        b = Block(content="hello", priority=Priority.HIGH, compress_hint="bullet_extract")
        d = _block_to_dict(b)
        assert d["content"] == "hello"
        assert d["priority"] == "high"
        assert d["compress_hint"] == "bullet_extract"
        assert d["token_count"] > 0


class TestDetectCompressHint:
    def test_code_detection(self):
        code = "import os\nfrom pathlib import Path\ndef hello():\n    pass\nclass Foo:\n    pass"
        hint = _detect_compress_hint(code)
        assert hint == "code_compact"

    def test_short_text(self):
        hint = _detect_compress_hint("hello")
        assert hint is None


class TestBlockHash:
    def test_deterministic(self):
        h1 = block_hash("hello world")
        h2 = block_hash("hello world")
        assert h1 == h2

    def test_different(self):
        h1 = block_hash("hello")
        h2 = block_hash("world")
        assert h1 != h2


class TestGetConnector:
    def test_not_found(self):
        _init_db(None)
        with pytest.raises(Exception):
            _get_connector("nonexistent_connector_xyz")


class TestRateLimiter:
    def test_allowed_within_limit(self):
        rl = RateLimiter(requests_per_minute=10, burst=5)
        for _ in range(14):
            assert rl.is_allowed("127.0.0.1") is True

    def test_blocked_over_limit(self):
        rl = RateLimiter(requests_per_minute=5, burst=2)
        for _ in range(7):
            rl.is_allowed("127.0.0.1")
        assert rl.is_allowed("127.0.0.1") is False

    def test_remaining(self):
        rl = RateLimiter(requests_per_minute=10, burst=5)
        rl.is_allowed("127.0.0.1")
        remaining = rl.remaining("127.0.0.1")
        assert remaining == 14  # 10+5 - 1

    def test_retry_after(self):
        rl = RateLimiter(requests_per_minute=2, burst=0)
        rl.is_allowed("127.0.0.1")
        rl.is_allowed("127.0.0.1")
        assert rl.is_allowed("127.0.0.1") is False
        retry = rl.get_retry_after("127.0.0.1")
        assert retry > 0

    def test_retry_after_empty(self):
        rl = RateLimiter(requests_per_minute=10, burst=5)
        retry = rl.get_retry_after("unknown_ip")
        assert retry == 0

    def test_separate_ips(self):
        rl = RateLimiter(requests_per_minute=2, burst=0)
        rl.is_allowed("10.0.0.1")
        rl.is_allowed("10.0.0.1")
        assert rl.is_allowed("10.0.0.1") is False
        assert rl.is_allowed("10.0.0.2") is True

    def test_cleanup(self):
        rl = RateLimiter(requests_per_minute=10, burst=5)
        rl._cleanup_interval = 0
        rl.is_allowed("stale_ip")
        rl._window["stale_ip"] = [time.monotonic() - 120]
        rl.is_allowed("other_ip")
        assert "stale_ip" not in rl._window
