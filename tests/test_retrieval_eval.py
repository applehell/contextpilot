"""Tests for src.core.retrieval_eval — ranking metrics and case generation."""
from __future__ import annotations

import json

import pytest

from src.core.retrieval_eval import (
    EvalCase,
    evaluate,
    load_cases,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    self_eval_cases,
)
from src.storage.memory import Memory


class TestMetrics:
    def test_precision(self) -> None:
        assert precision_at_k(["a", "b", "c"], {"a", "c"}, 3) == pytest.approx(2 / 3)
        assert precision_at_k([], {"a"}, 3) == 0.0

    def test_recall(self) -> None:
        assert recall_at_k(["a", "x"], {"a", "b"}, 2) == pytest.approx(0.5)
        assert recall_at_k(["a"], set(), 2) == 0.0

    def test_reciprocal_rank(self) -> None:
        assert reciprocal_rank(["x", "a"], {"a"}) == pytest.approx(0.5)
        assert reciprocal_rank(["x", "y"], {"a"}) == 0.0

    def test_ndcg_perfect(self) -> None:
        assert ndcg_at_k(["a", "b"], {"a", "b"}, 2) == pytest.approx(1.0)

    def test_ndcg_no_hits(self) -> None:
        assert ndcg_at_k(["x"], {"a"}, 2) == 0.0


class TestEvaluate:
    def test_empty_cases(self) -> None:
        r = evaluate([], lambda q: [], k=5)
        assert r["cases"] == 0

    def test_perfect_search(self) -> None:
        cases = [EvalCase("find a", ["a"]), EvalCase("find b", ["b"])]
        r = evaluate(cases, lambda q: [q.split()[-1]], k=5)
        assert r["precision"] == 1.0
        assert r["mrr"] == 1.0

    def test_useless_search(self) -> None:
        cases = [EvalCase("find a", ["a"])]
        r = evaluate(cases, lambda q: ["z"], k=5)
        assert r["precision"] == 0.0
        assert r["recall"] == 0.0


class TestSelfEvalCases:
    def test_generates_query_per_memory(self) -> None:
        mems = [
            Memory(key="k1", value="# Title One\nThis is a reasonably long description here"),
            Memory(key="k2", value="Another sufficiently long memory body for evaluation"),
        ]
        cases = self_eval_cases(mems)
        assert len(cases) == 2
        assert all(c.relevant_keys for c in cases)
        # markdown header stripped, query non-empty
        assert all(not c.query.startswith("#") for c in cases)

    def test_skips_short(self) -> None:
        assert self_eval_cases([Memory(key="k", value="too short")]) == []

    def test_deterministic_sample(self) -> None:
        mems = [Memory(key=f"k{i:02d}", value=f"Memory number {i} with enough content to qualify here")
                for i in range(20)]
        a = self_eval_cases(mems, sample=5)
        b = self_eval_cases(mems, sample=5)
        assert len(a) == 5
        assert [c.relevant_keys for c in a] == [c.relevant_keys for c in b]


class TestLoadCases:
    def test_load(self, tmp_path) -> None:
        p = tmp_path / "eval_cases.json"
        p.write_text(json.dumps([
            {"query": "how to deploy", "relevant_keys": ["deploy/guide"]},
            {"query": "ignored", "keys": ["alt/key"]},
            {"query": "", "relevant_keys": ["x"]},  # skipped
        ]))
        cases = load_cases(p)
        assert len(cases) == 2
        assert cases[0].query == "how to deploy"
        assert cases[1].relevant_keys == ["alt/key"]
