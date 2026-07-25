"""Memory consolidation — confidence scoring, contradiction detection, merging.

Builds on the lexical duplicate detection in ``duplicates.py`` to provide the
"act on it" layer: a derived confidence score per memory, a conservative
contradiction heuristic for topically-related memories that disagree, and a
merge operation that folds a group of memories into a single surviving record.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory
from .duplicates import _jaccard, find_duplicates

_NUM_RE = re.compile(r"-?\d+(?:[.,]\d+)?")
_WORD_RE = re.compile(r"[a-zäöü]+")
_TOKEN_RE = re.compile(r"[a-z0-9äöü]+")

# Opposite-polarity word pairs (English + German) used for contradiction hints.
_POLARITY = [
    ("enabled", "disabled"), ("active", "inactive"), ("true", "false"),
    ("yes", "no"), ("on", "off"), ("open", "closed"), ("up", "down"),
    ("success", "failure"), ("allowed", "denied"), ("present", "absent"),
    ("aktiv", "inaktiv"), ("ja", "nein"), ("an", "aus"), ("offen", "geschlossen"),
]

_CONFIDENCE_HALF_LIFE_DAYS = 180.0


@dataclass
class Contradiction:
    key_a: str
    key_b: str
    similarity: float
    reason: str


def _recency(updated_at: float, now: float, half_life: float) -> float:
    age_days = max(0.0, (now - updated_at) / 86400.0)
    return 0.5 ** (age_days / half_life)


def confidence_score(memory: Memory, corroboration: int = 0,
                     now: Optional[float] = None) -> float:
    """Derive a 0..1 trust score from pinned/source/recency/corroboration signals."""
    now = now if now is not None else time.time()
    score = 0.5
    if memory.pinned:
        score += 0.2
    score += 0.15 * _recency(memory.updated_at, now, _CONFIDENCE_HALF_LIFE_DAYS)
    if memory.metadata.get("source") or any(t.startswith("source:") for t in memory.tags):
        score += 0.1
    score += min(0.15, 0.05 * corroboration)
    if memory.category in ("ephemeral", "session"):
        score -= 0.1
    if memory.is_expired:
        score -= 0.2
    return round(max(0.0, min(1.0, score)), 3)


def _numbers(text: str) -> List[float]:
    out = []
    for raw in _NUM_RE.findall(text):
        try:
            out.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return out


def _related(a: Memory, b: Memory) -> bool:
    """True when two memories plausibly describe the same thing."""
    if set(a.tags) & set(b.tags):
        return True
    pa = a.key.rsplit("/", 1)[0]
    pb = b.key.rsplit("/", 1)[0]
    return bool(pa) and pa == pb


def _conflict(va: str, vb: str) -> Optional[str]:
    na, nb = _numbers(va), _numbers(vb)
    if na and nb and set(na) != set(nb):
        return f"numeric: {na[:3]} vs {nb[:3]}"
    wa = set(_WORD_RE.findall(va.lower()))
    wb = set(_WORD_RE.findall(vb.lower()))
    for p, q in _POLARITY:
        if (p in wa and q in wb) or (q in wa and p in wb):
            return f"polarity: {p}/{q}"
    return None


def find_contradictions(memories: List[Memory], min_similarity: float = 0.4,
                        max_results: Optional[int] = None) -> List[Contradiction]:
    """Flag topically-related memory pairs whose values numerically or
    polaritically disagree. Conservative — gated on text similarity to avoid
    flagging unrelated facts that merely share a tag.

    ``max_results`` stops the O(n²) scan early once that many pairs are
    collected — pathological corpora can otherwise produce hundreds of
    thousands of Contradiction objects."""
    cand = [m for m in memories if len(m.value) >= 20]
    words = {m.key: set(_TOKEN_RE.findall(m.value.lower())) for m in cand}
    out: List[Contradiction] = []
    for i in range(len(cand)):
        if max_results is not None and len(out) >= max_results:
            break
        for j in range(i + 1, len(cand)):
            a, b = cand[i], cand[j]
            if not _related(a, b):
                continue
            sim = _jaccard(words[a.key], words[b.key])
            if sim < min_similarity or sim >= 0.95:
                continue
            reason = _conflict(a.value, b.value)
            if reason:
                out.append(Contradiction(a.key, b.key, round(sim, 2), reason))
                if max_results is not None and len(out) >= max_results:
                    break
    return sorted(out, key=lambda c: -c.similarity)


def merge_group(store, keys: List[str], into: Optional[str] = None) -> str:
    """Fold a group of memories into one surviving record.

    The survivor is ``into`` if given, else the most recently updated. Tags and
    metadata are unioned (survivor wins on conflict), distinct values are
    concatenated, and the other memories are soft-deleted. Returns survivor key.
    """
    seen: set = set()
    mems: List[Memory] = []
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        try:
            mems.append(store.get(k))
        except KeyError:
            continue
    if len(mems) < 2:
        raise ValueError("merge needs at least 2 distinct existing memories")

    survivor: Optional[Memory] = None
    if into:
        survivor = next((m for m in mems if m.key == into), None)
        if survivor is None:
            raise ValueError(f"'into' key '{into}' not among the existing memories to merge")
    else:
        survivor = max(mems, key=lambda m: m.updated_at)
    others = [m for m in mems if m.key != survivor.key]

    tags = list(survivor.tags)
    for m in others:
        for t in m.tags:
            if t not in tags:
                tags.append(t)

    parts = [survivor.value.strip()]
    for m in others:
        v = m.value.strip()
        if v and v not in parts:
            parts.append(v)

    meta: Dict[str, Any] = {}
    for m in others:
        meta.update(m.metadata)
    meta.update(survivor.metadata)
    meta["merged_from"] = [m.key for m in others]

    survivor.value = "\n\n---\n\n".join(parts)
    survivor.tags = tags
    survivor.metadata = meta
    survivor.pinned = survivor.pinned or any(m.pinned for m in others)
    store.set(survivor)
    for m in others:
        store.delete(m.key)
    return survivor.key


def consolidation_report(memories: List[Memory], dup_threshold: float = 0.6) -> Dict[str, Any]:
    """Aggregate dedup / contradiction / low-confidence findings for a profile."""
    now = time.time()
    dups = find_duplicates(memories, dup_threshold)
    contras = find_contradictions(memories)
    low_conf = []
    for m in memories:
        c = confidence_score(m, now=now)
        if c < 0.4:
            low_conf.append({"key": m.key, "confidence": c})
    low_conf.sort(key=lambda x: x["confidence"])
    return {
        "total": len(memories),
        "duplicate_groups": len(dups),
        "duplicate_memories": sum(len(g.keys) for g in dups),
        "contradictions": len(contras),
        "low_confidence": len(low_conf),
        "low_confidence_samples": low_conf[:20],
    }
