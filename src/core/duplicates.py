"""Duplicate detection — find similar memories using content fingerprinting."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import List, Tuple

from ..storage.memory import Memory


@dataclass
class DuplicateGroup:
    keys: List[str]
    similarity: float
    sample: str


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _shingles(text: str, k: int = 5) -> set:
    words = _normalize(text).split()
    if len(words) < k:
        return {" ".join(words)}
    return {" ".join(words[i:i+k]) for i in range(len(words) - k + 1)}


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_duplicates(memories: List[Memory], threshold: float = 0.6) -> List[DuplicateGroup]:
    """Find groups of memories with content similarity above threshold."""
    if len(memories) < 2:
        return []

    # Pre-compute shingles
    shingle_map = {}
    for m in memories:
        if len(m.value) > 50:  # skip very short memories
            shingle_map[m.key] = _shingles(m.value)

    keys = list(shingle_map.keys())
    groups = []
    seen = set()

    for i in range(len(keys)):
        if keys[i] in seen:
            continue
        group_keys = [keys[i]]
        for j in range(i + 1, len(keys)):
            if keys[j] in seen:
                continue
            sim = _jaccard(shingle_map[keys[i]], shingle_map[keys[j]])
            if sim >= threshold:
                group_keys.append(keys[j])
                seen.add(keys[j])
        if len(group_keys) > 1:
            seen.add(keys[i])
            # Calculate average similarity within group
            avg_sim = 0
            count = 0
            for a in range(len(group_keys)):
                for b in range(a + 1, len(group_keys)):
                    avg_sim += _jaccard(shingle_map[group_keys[a]], shingle_map[group_keys[b]])
                    count += 1
            avg_sim = avg_sim / count if count else 0

            sample_mem = next(m for m in memories if m.key == group_keys[0])
            groups.append(DuplicateGroup(
                keys=group_keys,
                similarity=round(avg_sim, 2),
                sample=sample_mem.value[:200],
            ))

    return sorted(groups, key=lambda g: -g.similarity)


def find_similar(target: Memory, memories: List[Memory], threshold: float = 0.5, limit: int = 10) -> List[Tuple[str, float]]:
    """Find memories similar to a target. Returns [(key, similarity), ...]."""
    target_shingles = _shingles(target.value)
    if not target_shingles:
        return []

    results = []
    for m in memories:
        if m.key == target.key:
            continue
        if len(m.value) < 50:
            continue
        sim = _jaccard(target_shingles, _shingles(m.value))
        if sim >= threshold:
            results.append((m.key, round(sim, 2)))

    results.sort(key=lambda x: -x[1])
    return results[:limit]
