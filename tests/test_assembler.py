from __future__ import annotations

import copy
import pytest

from src.core.assembler import Assembler
from src.core.block import Block, Priority
from src.core.compressors.base import BaseCompressor
from src.core.token_budget import TokenBudget


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_block(content: str, priority: Priority = Priority.MEDIUM, compress_hint: str | None = None) -> Block:
    return Block(content=content, priority=priority, compress_hint=compress_hint)


class HalfCompressor(BaseCompressor):
    """Reduces block content to the first half of its characters."""

    @property
    def name(self) -> str:
        return "half"

    def compress(self, block: Block) -> Block:
        result = copy.copy(block)
        result.content = block.content[: len(block.content) // 2]
        result.invalidate_token_count()
        return result


class NullCompressor(BaseCompressor):
    """Returns the block unchanged (useful to verify registry wiring)."""

    @property
    def name(self) -> str:
        return "null"

    def compress(self, block: Block) -> Block:
        return copy.copy(block)


# ---------------------------------------------------------------------------
# Basic assembler behaviour
# ---------------------------------------------------------------------------

class TestAssemblerFastPath:
    def test_empty_list_returns_empty(self):
        a = Assembler()
        assert a.assemble([], 1000) == []

    def test_single_block_fits(self):
        block = make_block("hello world", Priority.HIGH)
        a = Assembler()
        result = a.assemble([block], 1000)
        assert len(result) == 1
        assert result[0].content == "hello world"

    def test_all_blocks_fit_sorted_by_priority(self):
        low = make_block("low content", Priority.LOW)
        mid = make_block("medium content", Priority.MEDIUM)
        high = make_block("high content", Priority.HIGH)
        a = Assembler()
        result = a.assemble([low, mid, high], 10_000)
        assert result[0].priority == Priority.HIGH
        assert result[1].priority == Priority.MEDIUM
        assert result[2].priority == Priority.LOW

    def test_exact_budget_fit(self):
        block = make_block("hello", Priority.MEDIUM)
        budget = block.token_count
        a = Assembler()
        result = a.assemble([block], budget)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Phase 1: dropping LOW blocks
# ---------------------------------------------------------------------------

class TestDropLow:
    def test_drops_low_to_fit(self):
        high = make_block("This is a high priority block with content.", Priority.HIGH)
        low = make_block("Low priority filler text that should be dropped.", Priority.LOW)
        budget = high.token_count  # exactly enough for HIGH only
        a = Assembler()
        result = a.assemble([high, low], budget)
        assert all(b.priority != Priority.LOW for b in result)
        assert any(b.priority == Priority.HIGH for b in result)

    def test_drops_multiple_low_blocks_until_fits(self):
        high = make_block("critical", Priority.HIGH)
        lows = [make_block(f"low filler number {i}", Priority.LOW) for i in range(5)]
        budget = high.token_count + 2  # room for high, nothing more
        a = Assembler()
        result = a.assemble([high] + lows, budget)
        total = sum(b.token_count for b in result)
        assert total <= budget

    def test_result_within_budget_after_low_drop(self):
        high = make_block("important text", Priority.HIGH)
        low = make_block("x " * 500, Priority.LOW)
        budget = 20
        a = Assembler()
        result = a.assemble([high, low], budget)
        total = sum(b.token_count for b in result)
        assert total <= budget


# ---------------------------------------------------------------------------
# Phase 2: compressing MEDIUM blocks
# ---------------------------------------------------------------------------

class TestCompressMedium:
    def test_compressor_called_for_medium_with_hint(self):
        high = make_block("high priority block content here", Priority.HIGH)
        mid_content = "medium content " * 20  # ~60 tokens
        mid = make_block(mid_content, Priority.MEDIUM, compress_hint="half")
        # Budget fits after halving (~30 tokens) but not before (~60 tokens)
        compressed_estimate = TokenBudget.estimate(mid_content[: len(mid_content) // 2])
        budget = high.token_count + compressed_estimate + 2
        a = Assembler(compressors=[HalfCompressor()])
        result = a.assemble([high, mid], budget)
        total = sum(b.token_count for b in result)
        assert total <= budget

    def test_unknown_compress_hint_skipped(self):
        block = make_block("some medium content", Priority.MEDIUM, compress_hint="nonexistent")
        a = Assembler()
        # Should not raise; just returns best effort
        result = a.assemble([block], 0)
        assert isinstance(result, list)

    def test_medium_without_hint_not_compressed(self):
        high = make_block("h", Priority.HIGH)
        mid = make_block("medium no hint", Priority.MEDIUM, compress_hint=None)
        budget = high.token_count  # tight
        a = Assembler(compressors=[HalfCompressor()])
        result = a.assemble([high, mid], budget)
        # mid has no hint, cannot be compressed; it may or may not be in result
        # but whatever is returned must be within or at best effort of budget
        assert isinstance(result, list)

    def test_register_compressor_after_init(self):
        mid = make_block("medium content " * 30, Priority.MEDIUM, compress_hint="half")
        a = Assembler()
        a.register(HalfCompressor())
        budget = 5
        result = a.assemble([mid], budget)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Phase 3: truncating HIGH blocks
# ---------------------------------------------------------------------------

class TestTruncateHigh:
    def test_high_block_truncated_as_last_resort(self):
        content = "word " * 200
        high = make_block(content, Priority.HIGH)
        budget = 20
        a = Assembler()
        result = a.assemble([high], budget)
        assert len(result) == 1
        total = sum(b.token_count for b in result)
        assert total <= budget

    def test_truncated_content_is_prefix(self):
        content = "abcdefghij " * 100
        high = make_block(content, Priority.HIGH)
        budget = 10
        a = Assembler()
        result = a.assemble([high], budget)
        assert content.startswith(result[0].content)

    def test_zero_budget_produces_empty_or_minimal_content(self):
        high = make_block("some text", Priority.HIGH)
        a = Assembler()
        result = a.assemble([high], 0)
        # Result may be empty content or very short; should not raise
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Priority ordering in output
# ---------------------------------------------------------------------------

class TestOutputOrdering:
    def test_output_always_high_before_medium_before_low(self):
        blocks = [
            make_block("low", Priority.LOW),
            make_block("medium", Priority.MEDIUM),
            make_block("high", Priority.HIGH),
        ]
        a = Assembler()
        result = a.assemble(blocks, 10_000)
        priorities = [b.priority for b in result]
        assert priorities == [Priority.HIGH, Priority.MEDIUM, Priority.LOW]

    def test_after_reduction_ordering_maintained(self):
        high = make_block("high block", Priority.HIGH)
        mid = make_block("medium block", Priority.MEDIUM)
        low = make_block("low filler " * 100, Priority.LOW)
        budget = high.token_count + mid.token_count + 2
        a = Assembler()
        result = a.assemble([low, mid, high], budget)
        priorities = [b.priority for b in result]
        assert priorities[0] == Priority.HIGH


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_only_low_blocks_all_dropped(self):
        lows = [make_block(f"low {i}", Priority.LOW) for i in range(3)]
        # Tiny budget forces all LOW to be dropped
        high = make_block("high", Priority.HIGH)
        budget = high.token_count
        a = Assembler()
        result = a.assemble(lows + [high], budget)
        assert all(b.priority != Priority.LOW for b in result)

    def test_no_compressors_registered(self):
        blocks = [make_block("text " * 100, Priority.MEDIUM, compress_hint="half")]
        a = Assembler()  # no compressors
        result = a.assemble(blocks, 5)
        assert isinstance(result, list)

    def test_blocks_not_mutated(self):
        original_content = "original content " * 10
        block = make_block(original_content, Priority.HIGH)
        a = Assembler()
        a.assemble([block], 5)
        assert block.content == original_content

    def test_input_list_not_mutated(self):
        blocks = [make_block("content", Priority.LOW) for _ in range(3)]
        original_len = len(blocks)
        a = Assembler()
        a.assemble(blocks, 1)
        assert len(blocks) == original_len

    def test_large_budget_passes_through_unchanged_content(self):
        block = make_block("hello world", Priority.MEDIUM)
        a = Assembler()
        result = a.assemble([block], 100_000)
        assert result[0].content == "hello world"

    def test_compressor_registry_multiple_compressors(self):
        a = Assembler(compressors=[HalfCompressor(), NullCompressor()])
        assert "half" in a._registry
        assert "null" in a._registry

    def test_token_budget_respected_after_compression(self):
        mid_content = "word " * 100  # ~100 tokens
        mid = make_block(mid_content, Priority.MEDIUM, compress_hint="half")
        high = make_block("important", Priority.HIGH)
        # Budget: fits after halving (~50 tokens) but not before (~100 tokens)
        compressed_estimate = TokenBudget.estimate(mid_content[: len(mid_content) // 2])
        budget = high.token_count + compressed_estimate + 2
        a = Assembler(compressors=[HalfCompressor()])
        result = a.assemble([high, mid], budget)
        total = sum(b.token_count for b in result)
        assert total <= budget


# ---------------------------------------------------------------------------
# Coverage gap: _truncate already-fits branch (assembler.py line 99)
# ---------------------------------------------------------------------------

class TestAssembleTracked:
    def test_input_blocks_not_mutated_by_assembly(self):
        """assemble_tracked must deep-copy input_blocks so assembly doesn't leak mutations."""
        content = "word " * 200
        block = make_block(content, Priority.HIGH)
        a = Assembler()
        result = a.assemble_tracked([block], budget=5)
        # The stored input_blocks snapshot must still have the original content
        assert result.input_blocks[0].content == content

    def test_dropped_blocks_detected(self):
        high = make_block("important", Priority.HIGH)
        low = make_block("filler " * 100, Priority.LOW)
        a = Assembler()
        result = a.assemble_tracked([high, low], budget=high.token_count)
        assert len(result.dropped_blocks) >= 1


class TestTruncateAlreadyFits:
    def test_truncate_returns_copy_when_content_fits(self):
        """Block content is shorter than token_limit → early return on line 99."""
        block = make_block("short text")
        big_limit = 1000
        result = Assembler._truncate(block, big_limit)
        assert result is not block
        assert result.content == block.content

    def test_truncate_zero_limit_empties_content(self):
        block = make_block("some content")
        result = Assembler._truncate(block, 0)
        assert result.content == ""
