"""Signal-fusion reranking for retrieved candidates.

Re-orders hybrid-search candidates by blending lexical/semantic relevance with
recency, pinned status and query/tag/key term overlap — no extra model needed,
so it runs on the same lightweight stack as the default TF-IDF backend.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory
from .embeddings import tokenize
from .log import get_logger

logger = get_logger("core.rerank")

DEFAULT_WEIGHTS = {
    "relevance": 0.6,
    "recency": 0.15,
    "pinned": 0.1,
    "tag_overlap": 0.1,
    "key_overlap": 0.05,
}

RECENCY_HALF_LIFE_DAYS = 30.0


def _recency_score(updated_at: float, now: float) -> float:
    age_days = max(0.0, (now - updated_at) / 86400.0)
    return 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)


def _coverage(query_terms: set, target_terms: set) -> float:
    """Fraction of query terms present in the target term set."""
    if not query_terms or not target_terms:
        return 0.0
    return len(query_terms & target_terms) / len(query_terms)


def rerank(
    query: str,
    candidates: List[Dict[str, Any]],
    memories_by_key: Dict[str, Memory],
    weights: Optional[Dict[str, float]] = None,
    now: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Return candidates reordered by a fused relevance score.

    Each candidate is a hybrid_search dict (key, value, score, tags). The
    original dict is copied and annotated with ``rerank_score`` and
    ``base_score``; the input list is left untouched.
    """
    if not candidates:
        return []
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    now = now if now is not None else time.time()
    q_terms = set(tokenize(query))

    scored: List[Dict[str, Any]] = []
    for c in candidates:
        rel = float(c.get("score", 0.0))
        m = memories_by_key.get(c["key"])
        if m is not None:
            rec = _recency_score(m.updated_at, now)
            pin = 1.0 if m.pinned else 0.0
            tag_terms = set(tokenize(" ".join(m.tags)))
        else:
            rec = 0.0
            pin = 0.0
            tag_terms = set(tokenize(" ".join(c.get("tags", []))))
        tag_ov = _coverage(q_terms, tag_terms)
        key_ov = _coverage(q_terms, set(tokenize(c["key"])))
        combined = (
            w["relevance"] * rel
            + w["recency"] * rec
            + w["pinned"] * pin
            + w["tag_overlap"] * tag_ov
            + w["key_overlap"] * key_ov
        )
        out = dict(c)
        out["base_score"] = round(rel, 4)
        out["rerank_score"] = round(combined, 4)
        scored.append(out)

    scored.sort(key=lambda x: -x["rerank_score"])
    return scored


def rerank_candidates(
    query: str,
    candidates: List[Dict[str, Any]],
    store,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """Convenience wrapper that loads Memory metadata for each candidate key."""
    by_key: Dict[str, Memory] = {}
    for c in candidates:
        try:
            by_key[c["key"]] = store.get(c["key"])
        except Exception as e:
            logger.debug("rerank: store.get failed for key %s: %s", c.get("key"), e)
    return rerank(query, candidates, by_key, weights=weights)
