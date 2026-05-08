"""Knowledge graph endpoints: graph visualization, dependency detection, relations."""
from __future__ import annotations

import html
import json
from collections import defaultdict
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request

from src.core.token_budget import TokenBudget
from src.web.deps import (
    _events,
    _get_db,
    _get_memory_store,
)

router = APIRouter(tags=["graph"])


def _build_knowledge_graph() -> Dict[str, Any]:
    store = _get_memory_store()
    memories = store.list()

    CATEGORY_COLORS = [
        "#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7",
        "#fab387", "#94e2d5", "#74c7ec", "#f5c2e7", "#b4befe",
    ]

    nodes = []
    groups_seen: Dict[str, int] = {}
    tag_index: Dict[str, List[str]] = defaultdict(list)

    for m in memories:
        parts = m.key.split("/")
        if len(parts) >= 2:
            group = "/".join(parts[:2])
            label = "/".join(parts[2:]) or parts[-1]
        else:
            group = parts[0]
            label = parts[0]

        if group not in groups_seen:
            groups_seen[group] = len(groups_seen)

        tokens = TokenBudget.estimate(m.value)
        size = max(8, min(40, 8 + tokens // 50))

        if label == "_preamble":
            label = "(preamble)"

        nodes.append({
            "id": m.key,
            "label": label,
            "group": group,
            "title": f"<b>{html.escape(m.key)}</b><br>Tags: {html.escape(', '.join(m.tags) or 'none')}<br>{tokens} tokens",
            "value": size,
            "tags": m.tags,
        })

        for tag in m.tags:
            tag_index[tag].append(m.key)

    edges = []
    edge_set: set = set()
    for tag, keys in tag_index.items():
        if len(keys) > 20:
            continue
        for i, k1 in enumerate(keys):
            g1 = "/".join(k1.split("/")[:2])
            for k2 in keys[i + 1:]:
                g2 = "/".join(k2.split("/")[:2])
                if g1 == g2:
                    continue
                pair = tuple(sorted([k1, k2]))
                if pair not in edge_set:
                    edge_set.add(pair)
                    edges.append({
                        "from": k1,
                        "to": k2,
                        "title": f"Tag: {tag}",
                        "color": {"color": "#585b70", "opacity": 0.4},
                        "width": 1,
                    })

    from src.storage.relations import RelationStore
    rel_store = RelationStore(_get_db())
    memory_keys = {m.key for m in memories}
    RELATION_COLORS = {
        "references": "#89b4fa",
        "shared_entity": "#a6e3a1",
        "tag_cluster": "#cba6f7",
        "related": "#f9e2af",
    }
    for rel in rel_store.list_all():
        if rel.source_key not in memory_keys or rel.target_key not in memory_keys:
            continue
        pair = tuple(sorted([rel.source_key, rel.target_key]))
        rel_edge_key = (*pair, rel.relation_type)
        if rel_edge_key not in edge_set:
            edge_set.add(rel_edge_key)
            color = RELATION_COLORS.get(rel.relation_type, "#f9e2af")
            edges.append({
                "from": rel.source_key,
                "to": rel.target_key,
                "title": rel.relation_type + (" (auto)" if rel.auto else ""),
                "color": {"color": color, "opacity": 0.7},
                "width": 2,
                "dashes": rel.auto,
            })

    group_config = {}
    for group_name, idx in groups_seen.items():
        color = CATEGORY_COLORS[idx % len(CATEGORY_COLORS)]
        group_config[group_name] = {
            "color": {"background": color, "border": color, "highlight": {"background": color, "border": "#fff"}},
            "font": {"color": "#cdd6f4"},
        }

    categories = defaultdict(int)
    for g in groups_seen:
        categories[g.split("/")[0]] += 1

    return {
        "nodes": nodes,
        "edges": edges,
        "groups": group_config,
        "stats": {
            "total_memories": len(memories),
            "total_groups": len(groups_seen),
            "total_edges": len(edges),
            "categories": dict(categories),
        },
    }


@router.get("/api/knowledge-graph")
async def knowledge_graph():
    return _build_knowledge_graph()


@router.post("/api/dependencies/detect")
async def detect_dependencies_endpoint():
    from src.core.dependency_detector import detect_dependencies
    from src.storage.relations import RelationStore
    store = _get_memory_store()
    memories = store.list()
    relations = detect_dependencies(memories)
    rel_store = RelationStore(_get_db())
    cleared = rel_store.clear_auto()
    added = rel_store.bulk_add_auto(relations)
    _events.emit("graph", "detect", "dependencies", f"{added} detected, {cleared} previous cleared")
    return {"detected": len(relations), "added": added, "cleared": cleared}


# --- Memory Relations ---

@router.get("/api/relations/{key:path}")
async def get_relations(key: str):
    from src.storage.relations import RelationStore
    rs = RelationStore(_get_db())
    return [{"id": r.id, "source_key": r.source_key, "target_key": r.target_key,
             "relation_type": r.relation_type, "created_at": r.created_at} for r in rs.get_relations(key)]


@router.post("/api/relations", status_code=201)
async def add_relation(request: Request):
    from src.storage.relations import RelationStore
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    if not body.get("source_key") or not body.get("target_key"):
        raise HTTPException(400, "source_key and target_key are required")
    rs = RelationStore(_get_db())
    try:
        r = rs.add(body["source_key"], body["target_key"], body.get("relation_type", "related"))
        _events.emit("memory", "link", f"{r.source_key} -> {r.target_key}", r.relation_type)
        return {"id": r.id, "source_key": r.source_key, "target_key": r.target_key}
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.delete("/api/relations/{relation_id}")
async def remove_relation(relation_id: int):
    from src.storage.relations import RelationStore
    rs = RelationStore(_get_db())
    try:
        rs.remove(relation_id)
        return {"status": "deleted"}
    except KeyError as e:
        raise HTTPException(404, str(e))
