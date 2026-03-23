import pytest
from src.core.block import Block, Priority
from src.core.context import Context


def test_context_empty():
    ctx = Context()
    assert len(ctx) == 0
    assert ctx.total_tokens == 0


def test_context_add():
    ctx = Context()
    b = Block(content="hello")
    ctx.add(b)
    assert len(ctx) == 1


def test_context_remove():
    ctx = Context()
    b = Block(content="hello")
    ctx.add(b)
    ctx.remove(b)
    assert len(ctx) == 0


def test_context_remove_missing():
    ctx = Context()
    b = Block(content="hello")
    with pytest.raises(ValueError):
        ctx.remove(b)


def test_context_clear():
    ctx = Context()
    ctx.add(Block(content="a"))
    ctx.add(Block(content="b"))
    ctx.clear()
    assert len(ctx) == 0


def test_context_total_tokens():
    ctx = Context()
    b1 = Block(content="hello world")
    b2 = Block(content="foo bar baz")
    ctx.add(b1)
    ctx.add(b2)
    assert ctx.total_tokens == b1.token_count + b2.token_count


def test_context_blocks_returns_copy():
    ctx = Context()
    b = Block(content="hello")
    ctx.add(b)
    blocks = ctx.blocks
    blocks.append(Block(content="injected"))
    assert len(ctx) == 1


def test_context_blocks_by_priority():
    ctx = Context()
    low = Block(content="low", priority=Priority.LOW)
    high = Block(content="high", priority=Priority.HIGH)
    med = Block(content="med", priority=Priority.MEDIUM)
    ctx.add(low)
    ctx.add(med)
    ctx.add(high)
    sorted_blocks = ctx.blocks_by_priority()
    assert sorted_blocks[0].priority == Priority.HIGH
    assert sorted_blocks[1].priority == Priority.MEDIUM
    assert sorted_blocks[2].priority == Priority.LOW


def test_context_iter():
    ctx = Context()
    blocks = [Block(content=f"block {i}") for i in range(3)]
    for b in blocks:
        ctx.add(b)
    assert list(ctx) == blocks
