"""Spreading activation — associative recall over the knowledge graph.

Retrieval hits activate their graph neighbors with decaying strength, the way
one memory cues another: a hit on the wallbox config also surfaces the note
about its RFID reset card, two hops away. Model-free and cheap — a bounded
BFS over the relations table.
"""
from __future__ import annotations

from typing import Dict

DEFAULT_DECAY = 0.5
DEFAULT_MIN_ACTIVATION = 0.05
DEFAULT_MAX_HOPS = 2
DEFAULT_MAX_NODES = 8


def spread_activation(seeds: Dict[str, float], rel_store,
                      max_hops: int = DEFAULT_MAX_HOPS,
                      decay: float = DEFAULT_DECAY,
                      min_activation: float = DEFAULT_MIN_ACTIVATION,
                      max_nodes: int = DEFAULT_MAX_NODES) -> Dict[str, float]:
    """Activate keys related to the seed keys via graph edges.

    Each hop multiplies the source activation by ``decay`` and the edge
    confidence. A node keeps its strongest activation. Returns the top
    ``max_nodes`` activated keys that are NOT seeds, as {key: activation}.
    """
    activation: Dict[str, float] = dict(seeds)
    frontier = dict(seeds)

    for _ in range(max_hops):
        next_frontier: Dict[str, float] = {}
        for key, act in frontier.items():
            try:
                relations = rel_store.get_relations(key)
            except Exception:
                continue
            for rel in relations:
                other = rel.target_key if rel.source_key == key else rel.source_key
                if other == key:
                    continue
                a = act * decay * (rel.confidence if rel.confidence else 1.0)
                if a < min_activation or a <= activation.get(other, 0.0):
                    continue
                activation[other] = a
                next_frontier[other] = max(next_frontier.get(other, 0.0), a)
        frontier = next_frontier
        if not frontier:
            break

    associated = {k: round(v, 4) for k, v in activation.items() if k not in seeds}
    top = sorted(associated.items(), key=lambda x: -x[1])[:max_nodes]
    return dict(top)


def expand_results(results, store, rel_store, seed_count: int = 10,
                   max_nodes: int = DEFAULT_MAX_NODES) -> list:
    """Associatively expand ranked search results.

    Takes the top ``seed_count`` results as activation seeds, spreads over the
    knowledge graph, and returns additional result dicts (method
    ``"associated"``) for activated memories not already in the results.
    """
    if not results:
        return []
    seeds = {r["key"]: float(r.get("score") or 0.5) or 0.5
             for r in results[:seed_count]}
    activated = spread_activation(seeds, rel_store, max_nodes=max_nodes + len(results))
    existing = {r["key"] for r in results}
    extras = []
    for key, act in activated.items():
        if len(extras) >= max_nodes:
            break
        if key in existing:
            continue
        try:
            m = store.get(key)
        except KeyError:
            continue
        if getattr(m, "archived", False) or m.is_expired:
            continue
        extras.append({"key": m.key, "value": m.value, "score": act,
                       "tags": m.tags, "method": "associated"})
    return extras
