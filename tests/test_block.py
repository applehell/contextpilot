import pytest
from src.core.block import Block, Priority


def test_block_defaults():
    b = Block(content="hello world")
    assert b.content == "hello world"
    assert b.priority == Priority.MEDIUM
    assert b.compress_hint is None


def test_block_token_count_lazy():
    b = Block(content="hello world")
    assert b._token_count is None
    count = b.token_count
    assert count > 0
    assert b._token_count == count


def test_block_token_count_cached():
    b = Block(content="hello world")
    c1 = b.token_count
    c2 = b.token_count
    assert c1 == c2


def test_block_invalidate_token_count():
    b = Block(content="hello world")
    _ = b.token_count
    b.invalidate_token_count()
    assert b._token_count is None


def test_block_priority_high():
    b = Block(content="urgent", priority=Priority.HIGH)
    assert b.priority == Priority.HIGH


def test_block_compress_hint():
    b = Block(content="- item1\n- item2", compress_hint="bullet_extract")
    assert b.compress_hint == "bullet_extract"


def test_block_priority_enum_values():
    assert Priority.HIGH == "high"
    assert Priority.MEDIUM == "medium"
    assert Priority.LOW == "low"
