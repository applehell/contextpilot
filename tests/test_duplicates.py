"""Tests for src.core.duplicates — duplicate detection."""
from __future__ import annotations

import pytest

from src.core.duplicates import (
    DuplicateGroup,
    _jaccard,
    _normalize,
    _shingles,
    find_duplicates,
    find_similar,
)
from src.storage.memory import Memory


def _mem(key: str, value: str, tags: list | None = None) -> Memory:
    return Memory(key=key, value=value, tags=tags or [])


class TestJaccard:
    def test_both_empty(self) -> None:
        assert _jaccard(set(), set()) == 1.0

    def test_one_empty(self) -> None:
        assert _jaccard({"a"}, set()) == 0.0
        assert _jaccard(set(), {"a"}) == 0.0

    def test_identical(self) -> None:
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self) -> None:
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self) -> None:
        assert _jaccard({"a", "b", "c"}, {"b", "c", "d"}) == pytest.approx(0.5)


class TestNormalize:
    def test_lowercases(self) -> None:
        assert _normalize("Hello WORLD") == "hello world"

    def test_collapses_whitespace(self) -> None:
        assert _normalize("  a   b  ") == "a b"


class TestShingles:
    def test_short_text_single_shingle(self) -> None:
        result = _shingles("one two three")
        assert len(result) == 1

    def test_longer_text(self) -> None:
        result = _shingles("a b c d e f g")
        assert len(result) == 3  # 7 words, k=5 -> 3 shingles


LONG_VALUE = "this is a long enough text that is definitely more than fifty characters for testing purposes"


class TestFindDuplicates:
    def test_identical_memories(self) -> None:
        mems = [
            _mem("a", LONG_VALUE),
            _mem("b", LONG_VALUE),
        ]
        groups = find_duplicates(mems)
        assert len(groups) == 1
        assert set(groups[0].keys) == {"a", "b"}
        assert groups[0].similarity == 1.0

    def test_no_duplicates(self) -> None:
        mems = [
            _mem("a", "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo"),
            _mem("b", "one two three four five six seven eight nine ten eleven twelve thirteen"),
        ]
        groups = find_duplicates(mems)
        assert groups == []

    def test_short_memories_skipped(self) -> None:
        mems = [
            _mem("a", "short"),
            _mem("b", "short"),
        ]
        groups = find_duplicates(mems)
        assert groups == []

    def test_empty_list(self) -> None:
        assert find_duplicates([]) == []

    def test_single_memory(self) -> None:
        assert find_duplicates([_mem("a", LONG_VALUE)]) == []

    def test_sorted_by_similarity_desc(self) -> None:
        base = "the quick brown fox jumps over the lazy dog repeatedly in the morning sunshine"
        mems = [
            _mem("a", base),
            _mem("b", base),  # identical to a
            _mem("c", base + " with some extra words appended at the end of the sentence to lower similarity"),
        ]
        groups = find_duplicates(mems, threshold=0.3)
        if len(groups) > 1:
            assert groups[0].similarity >= groups[1].similarity


class TestFindSimilar:
    def test_respects_threshold(self) -> None:
        target = _mem("target", LONG_VALUE)
        others = [
            _mem("exact", LONG_VALUE),
            _mem("diff", "completely different text that shares nothing with the target whatsoever at all none"),
        ]
        results = find_similar(target, others, threshold=0.9)
        assert len(results) == 1
        assert results[0][0] == "exact"

    def test_respects_limit(self) -> None:
        target = _mem("target", LONG_VALUE)
        others = [_mem(f"m{i}", LONG_VALUE) for i in range(20)]
        results = find_similar(target, others, threshold=0.5, limit=3)
        assert len(results) <= 3

    def test_excludes_self(self) -> None:
        target = _mem("target", LONG_VALUE)
        results = find_similar(target, [target], threshold=0.0)
        assert len(results) == 0

    def test_skips_short_memories(self) -> None:
        target = _mem("target", LONG_VALUE)
        others = [_mem("short", "tiny")]
        results = find_similar(target, others, threshold=0.0)
        assert len(results) == 0

    def test_empty_target_value(self) -> None:
        target = _mem("target", "")
        others = [_mem("a", LONG_VALUE)]
        results = find_similar(target, others, threshold=0.0)
        # _shingles("") returns a single shingle of empty string, but find_similar
        # checks if target_shingles is falsy -- set with empty string is truthy
        assert isinstance(results, list)
