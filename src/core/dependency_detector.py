"""Auto-detect dependencies between memories based on content analysis."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Dict, List

from src.storage.memory import Memory

IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_RE = re.compile(r"https?://[^\s)<>\"']+")
HOSTNAME_RE = re.compile(r"\b(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}\b")


def detect_dependencies(memories: List[Memory]) -> List[Dict]:
    """Detect relations between memories. Returns list of dicts with
    source_key, target_key, relation_type, confidence."""
    results = []
    keys = {m.key for m in memories}
    key_index = {m.key: m for m in memories}

    # 1. Key references — memory value mentions another memory's key
    for m in memories:
        for other_key in keys:
            if other_key == m.key:
                continue
            if other_key in m.value:
                results.append({
                    "source_key": m.key,
                    "target_key": other_key,
                    "relation_type": "references",
                    "confidence": 0.9,
                })

    # 2. Shared entities — IPs, URLs, hostnames appearing in multiple memories
    entity_map: Dict[str, List[str]] = defaultdict(list)
    for m in memories:
        entities = set()
        entities.update(IP_RE.findall(m.value))
        entities.update(URL_RE.findall(m.value))
        for e in entities:
            entity_map[e].append(m.key)

    seen_entity_pairs = set()
    for entity, mem_keys in entity_map.items():
        if len(mem_keys) < 2 or len(mem_keys) > 20:
            continue
        for i, k1 in enumerate(mem_keys):
            for k2 in mem_keys[i + 1:]:
                pair = tuple(sorted([k1, k2]))
                if pair not in seen_entity_pairs:
                    seen_entity_pairs.add(pair)
                    results.append({
                        "source_key": pair[0],
                        "target_key": pair[1],
                        "relation_type": "shared_entity",
                        "confidence": 0.7,
                    })

    # 3. Tag clusters — memories sharing >= 2 tags
    seen_tag_pairs = set()
    for i, m1 in enumerate(memories):
        if not m1.tags:
            continue
        s1 = set(m1.tags)
        for m2 in memories[i + 1:]:
            if not m2.tags:
                continue
            shared = s1 & set(m2.tags)
            if len(shared) >= 2:
                pair = tuple(sorted([m1.key, m2.key]))
                if pair not in seen_tag_pairs:
                    seen_tag_pairs.add(pair)
                    confidence = min(1.0, len(shared) * 0.3)
                    results.append({
                        "source_key": pair[0],
                        "target_key": pair[1],
                        "relation_type": "tag_cluster",
                        "confidence": confidence,
                    })

    # Deduplicate — keep highest confidence per (source, target, type)
    best = {}
    for r in results:
        key = (r["source_key"], r["target_key"], r["relation_type"])
        if key not in best or r["confidence"] > best[key]["confidence"]:
            best[key] = r

    return list(best.values())
