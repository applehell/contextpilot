"""Memory endpoints: CRUD, search, TTL, pinning, trash, bulk ops, tags, presets, sensitivity, export."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Dict, List

from fastapi import APIRouter, HTTPException, Query, Request

from src.core.log import get_logger

logger = get_logger("routers.memories")

from src.core.token_budget import TokenBudget
from src.storage.memory import Memory
from src.web.deps import (
    _db,
    _events,
    _get_db,
    _get_memory_store,
    _get_usage_store,
    _index_single,
    _remove_from_index,
    _secret_detector,
    _estimate_total_tokens,
    block_hash,
    FeedbackIn,
    FeedbackRecord,
    MemoryIn,
)

router = APIRouter(tags=["memories"])


@router.get("/api/memories")
async def list_memories(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    source: str = Query(""),
    sort: str = Query("key"),
    order: str = Query("asc"),
    category: str = Query(""),
):
    store = _get_memory_store()
    offset = (page - 1) * page_size
    cat = category if category else None
    memories = store.list(limit=page_size, offset=offset, source=source, sort=sort, order=order, category=cat)
    total = store.count(source=source)
    return {
        "memories": [{**m.to_dict(), "tokens": TokenBudget.estimate(m.value), "bytes": len(m.value.encode("utf-8"))} for m in memories],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/api/memories/sources")
async def memory_sources():
    store = _get_memory_store()
    return store.sources()


@router.get("/api/memories/search")
async def search_memories(
    q: str = Query(""),
    tags: str = Query(""),
    source: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    store = _get_memory_store()
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    offset = (page - 1) * page_size
    results = store.search(q, tag_list, source=source, limit=page_size, offset=offset)
    total = store.search_count(q, tag_list, source=source)
    _events.emit("memory", "search", q or "(all)", f"{total} results" + (f", source={source}" if source else ""))
    return {
        "memories": [{**m.to_dict(), "tokens": TokenBudget.estimate(m.value), "bytes": len(m.value.encode("utf-8"))} for m in results],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.get("/api/memories/expiring")
async def expiring_memories(hours: float = Query(24.0, ge=1)):
    store = _get_memory_store()
    memories = store.expiring_soon(within_hours=hours)
    return [m.to_dict() for m in memories]


@router.get("/api/memories/ttl-stats")
async def ttl_stats():
    store = _get_memory_store()
    expired = store.expired_count()
    expiring_24h = len(store.expiring_soon(24))
    expiring_7d = len(store.expiring_soon(168))
    total_with_ttl = 0
    if store._has_expires_column():
        row = store._db.conn.execute(
            "SELECT count(*) FROM memories WHERE expires_at IS NOT NULL"
        ).fetchone()
        total_with_ttl = row[0] if row else 0
    return {
        "total_with_ttl": total_with_ttl,
        "expired": expired,
        "expiring_24h": expiring_24h,
        "expiring_7d": expiring_7d,
    }


@router.get("/api/memories/category-stats")
async def category_stats():
    store = _get_memory_store()
    return store.category_stats()


@router.get("/api/memories/{key:path}/related")
async def get_related_memories(key: str):
    from src.storage.relations import RelationStore
    from src.web.deps import _db
    rs = RelationStore(_db)
    store = _get_memory_store()
    relations = rs.get_relations(key)
    items = []
    for r in relations:
        other_key = r.target_key if r.source_key == key else r.source_key
        try:
            m = store.get(other_key)
            items.append({
                "key": other_key,
                "value": m.value[:200],
                "tags": m.tags,
                "relation_type": r.relation_type,
                "direction": "outgoing" if r.source_key == key else "incoming",
            })
        except KeyError:
            items.append({
                "key": other_key,
                "value": "(deleted)",
                "tags": [],
                "relation_type": r.relation_type,
                "direction": "outgoing" if r.source_key == key else "incoming",
            })
    return {"key": key, "related": items, "count": len(items)}


@router.get("/api/memories/{key:path}/versions")
async def memory_versions(key: str, limit: int = Query(20, ge=1, le=100)):
    from src.storage.versions import VersionStore
    from src.web.deps import _db
    vs = VersionStore(_db)
    versions = vs.history(key, limit)
    return [{"id": v.id, "value": v.value, "tags": v.tags,
             "changed_by": v.changed_by, "created_at": v.created_at} for v in versions]


@router.get("/api/memories/{key:path}")
async def get_memory(key: str):
    store = _get_memory_store()
    try:
        return store.get(key).to_dict()
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/memories", status_code=201)
async def set_memory(req: MemoryIn):
    store = _get_memory_store()
    expires_at = None
    metadata: Dict[str, any] = {}
    if req.ttl_seconds and req.ttl_seconds > 0:
        expires_at = time.time() + req.ttl_seconds
        metadata["ttl_seconds"] = req.ttl_seconds
    m = Memory(key=req.key, value=req.value, tags=req.tags,
               metadata=metadata, expires_at=expires_at, category=req.category)
    store.set(m)
    _index_single(m)
    _events.emit("memory", "create", req.key, f"tags={req.tags}")
    return {"status": "saved", "key": req.key}


@router.put("/api/memories/{key:path}")
async def update_memory(key: str, req: MemoryIn):
    store = _get_memory_store()
    try:
        old = store.get(key)
    except KeyError:
        raise HTTPException(404, f"Memory '{key}' not found.")
    from src.storage.versions import VersionStore
    from src.web.deps import _db
    VersionStore(_db).record(key, old.value, old.tags, old.metadata, changed_by="web")
    expires_at = old.expires_at
    metadata = old.metadata.copy()
    if req.ttl_seconds is not None:
        if req.ttl_seconds > 0:
            expires_at = time.time() + req.ttl_seconds
            metadata["ttl_seconds"] = req.ttl_seconds
        else:
            expires_at = None
            metadata.pop("ttl_seconds", None)
    elif old.metadata.get("ttl_seconds"):
        expires_at = time.time() + old.metadata["ttl_seconds"]
    m = Memory(key=key, value=req.value, tags=req.tags,
               metadata=metadata, expires_at=expires_at)
    store.set(m, reset_ttl=False)
    _index_single(m)
    _events.emit("memory", "update", key)
    return {"status": "updated", "key": key}


@router.delete("/api/memories/{key:path}")
async def delete_memory(key: str):
    store = _get_memory_store()
    try:
        store.delete(key)
        _remove_from_index(key)
        _events.emit("memory", "delete", key)
        return {"status": "deleted", "key": key}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/memories/bulk-delete")
async def bulk_delete_memories(keys: List[str]):
    store = _get_memory_store()

    def _do_bulk_delete():
        deleted = 0
        for key in keys:
            try:
                store.delete(key)
                deleted += 1
            except KeyError:
                pass
        return deleted

    deleted = await asyncio.to_thread(_do_bulk_delete)
    logger.info("Bulk delete: %d/%d memories deleted", deleted, len(keys))
    _events.emit("memory", "bulk-delete", f"{deleted} memories")
    return {"status": "deleted", "count": deleted}


# --- Memory TTL ---

@router.post("/api/memories/{key:path}/ttl")
async def set_memory_ttl(key: str, request: Request):
    store = _get_memory_store()
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    ttl_seconds = body.get("ttl_seconds")
    try:
        store.get(key)
    except KeyError:
        raise HTTPException(404, f"Memory '{key}' not found.")
    store.set_ttl(key, ttl_seconds)
    _events.emit("memory", "ttl", key, f"ttl={ttl_seconds}")
    return {"status": "updated", "key": key, "ttl_seconds": ttl_seconds}


@router.post("/api/memories/cleanup-expired")
async def cleanup_expired():
    store = _get_memory_store()
    count = store.cleanup_expired()
    if count > 0:
        _events.emit("memory", "ttl-cleanup", f"{count} expired memories removed")
    return {"status": "cleaned", "removed": count}


@router.post("/api/memories/suggest-tags")
async def suggest_tags(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    text = f"{body.get('key', '')} {body.get('value', '')}"
    from src.core.embeddings import _tokenize
    words = _tokenize(text)
    if not words:
        return {"tags": []}
    store = _get_memory_store()
    all_tags = set()
    tag_scores: Dict[str, int] = {}
    for m in store.list(limit=200, sort="updated", order="desc"):
        for tag in m.tags:
            all_tags.add(tag)
            tag_words = set(_tokenize(f"{m.key} {m.value}"))
            overlap = len(set(words) & tag_words)
            if overlap > 0:
                tag_scores[tag] = tag_scores.get(tag, 0) + overlap
    ranked = sorted(tag_scores.items(), key=lambda x: -x[1])
    return {"tags": [t for t, _ in ranked[:5]]}


# --- Pinning ---

@router.post("/api/memories/{key:path}/pin")
async def pin_memory(key: str, pinned: bool = Query(True)):
    store = _get_memory_store()
    try:
        store.get(key)
    except KeyError:
        raise HTTPException(404, f"Memory '{key}' not found")
    store.pin(key, pinned)
    _events.emit("memory", "pin" if pinned else "unpin", key)
    return {"status": "ok", "pinned": pinned}


# --- Trash ---

@router.get("/api/trash")
async def list_trash():
    store = _get_memory_store()
    return store.trash_list()


@router.post("/api/trash/{key:path}/restore")
async def restore_from_trash(key: str):
    store = _get_memory_store()
    try:
        store.trash_restore(key)
        _events.emit("memory", "restore", key)
        return {"status": "restored", "key": key}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.delete("/api/trash/{key:path}")
async def purge_from_trash(key: str):
    store = _get_memory_store()
    store.trash_purge(key)
    return {"status": "purged", "key": key}


@router.delete("/api/trash")
async def empty_trash():
    store = _get_memory_store()
    count = store.trash_purge()
    return {"status": "emptied", "count": count}


# --- Bulk Tag Operations ---

@router.post("/api/memories/bulk-tags")
async def bulk_tag_memories(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    keys = body.get("keys", [])
    add_tags = body.get("add", [])
    remove_tags = body.get("remove", [])
    store = _get_memory_store()

    def _do_bulk_tags():
        updated = 0
        for key in keys:
            try:
                m = store.get(key)
                changed = False
                for t in add_tags:
                    if t not in m.tags:
                        m.tags.append(t)
                        changed = True
                for t in remove_tags:
                    if t in m.tags:
                        m.tags.remove(t)
                        changed = True
                if changed:
                    store.set(m)
                    updated += 1
            except KeyError:
                pass
        return updated

    updated = await asyncio.to_thread(_do_bulk_tags)
    logger.info("Bulk tags: %d/%d updated, +%s -%s", updated, len(keys), add_tags, remove_tags)
    _events.emit("memory", "bulk-tags", f"{updated} updated, +{add_tags} -{remove_tags}")
    return {"status": "ok", "updated": updated}


# --- Memory Presets ---

@router.get("/api/memory-presets")
async def list_memory_presets():
    from src.web.deps import _db
    try:
        rows = _db.conn.execute("SELECT name, key_prefix, default_tags, description, created_at FROM memory_presets ORDER BY name").fetchall()
        return [{"name": r["name"], "key_prefix": r["key_prefix"], "default_tags": json.loads(r["default_tags"]),
                 "description": r["description"]} for r in rows]
    except Exception:
        return []


@router.post("/api/memory-presets", status_code=201)
async def save_memory_preset(request: Request):
    from src.web.deps import _db
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(400, "Name required")
    _db.conn.execute(
        "INSERT OR REPLACE INTO memory_presets (name, key_prefix, default_tags, description, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, body.get("key_prefix", ""), json.dumps(body.get("default_tags", [])),
         body.get("description", ""), time.time()),
    )
    _db.conn.commit()
    return {"status": "saved", "name": name}


@router.delete("/api/memory-presets/{name}")
async def delete_memory_preset(name: str):
    from src.web.deps import _db
    _db.conn.execute("DELETE FROM memory_presets WHERE name = ?", (name,))
    _db.conn.commit()
    return {"status": "deleted"}


# --- Memory Tags ---

@router.get("/api/memory-tags")
async def memory_tags():
    store = _get_memory_store()
    return store.tags()


# --- Sensitivity ---

@router.get("/api/sensitivity")
async def memory_sensitivity(
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
):
    store = _get_memory_store()
    offset = (page - 1) * page_size
    memories = store.list(limit=page_size, offset=offset)
    results = []
    for m in memories:
        report = _secret_detector.scan(f"{m.key}\n{m.value}")
        results.append({
            "key": m.key,
            "severity": report.max_severity,
            "finding_count": len(report.findings),
            "findings": [
                {"pattern": f.pattern_name, "severity": f.severity, "preview": f.matched_text}
                for f in report.findings[:5]
            ],
        })
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "none": 4}
    results.sort(key=lambda r: order.get(r["severity"], 99))
    return {
        "total": len(memories),
        "sensitive": sum(1 for r in results if r["severity"] != "none"),
        "by_severity": {
            s: sum(1 for r in results if r["severity"] == s)
            for s in ["critical", "high", "medium", "low"]
            if any(r["severity"] == s for r in results)
        },
        "memories": results,
    }


@router.get("/api/redacted")
async def get_memory_redacted(key: str = Query(...)):
    store = _get_memory_store()
    try:
        m = store.get(key)
        redacted_value = _secret_detector.redact(m.value)
        report = _secret_detector.scan(f"{m.key}\n{m.value}")
        return {
            "key": m.key,
            "value": redacted_value,
            "tags": m.tags,
            "severity": report.max_severity,
            "findings": [
                {"pattern": f.pattern_name, "severity": f.severity}
                for f in report.findings
            ],
        }
    except KeyError as e:
        raise HTTPException(404, str(e))


# --- Export Memories ---

@router.get("/api/export-memories")
async def export_memories(tag: str = Query("")):
    store = _get_memory_store()
    if tag:
        memories = store.search("", tags=[tag])
    else:
        memories = store.list()
    return {"memories": [m.to_dict() for m in memories]}


# --- Memory Activity ---

@router.get("/api/memory-activity")
async def get_memory_activity(limit: int = Query(20, ge=1, le=100)):
    from src.storage.memory_activity import MemoryActivityLog
    from src.web.deps import _db
    _activity_log = MemoryActivityLog(_db)
    entries = _activity_log.recent(limit)
    return [
        {
            "operation": e.operation,
            "memory_key": e.memory_key,
            "detail": e.detail,
            "created_at": e.created_at,
            "age": e.age_label,
        }
        for e in entries
    ]


# --- Feedback ---

@router.post("/api/feedback")
async def submit_feedback(req: FeedbackIn):
    store = _get_usage_store()
    bh = block_hash(req.block_content)
    store.record_feedback(FeedbackRecord(
        assembly_id=req.assembly_id,
        block_hash=bh,
        helpful=req.helpful,
    ))
    return {"status": "recorded", "block_hash": bh}
