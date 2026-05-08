"""Tests for web deps — shared state init, helpers."""
from __future__ import annotations

import pytest

from src.storage.db import Database
from src.web.deps import (
    _estimate_total_tokens,
    _get_connector,
    _init_db,
    _make_assembler,
    _block_to_dict,
)
from src.core.compress_detect import detect_compress_hint as _detect_compress_hint
from src.storage.usage import block_hash
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


