"""System endpoints: maintenance, backups, MCP, scheduler, embeddings, semantic search, webhooks, setup."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from src.core.log import get_logger

logger = get_logger("routers.system")

from src.connectors.registry import ConnectorRegistry
from src.core.skill_registry import SkillRegistry
from src.storage.folders import FolderManager
from src.storage.memory_activity import MemoryActivityLog
from src.storage.profiles import ProfileManager
from src.web.deps import (
    _events,
    _get_connectors,
    _get_db,
    _get_memory_store,
    _get_profile_dir,
    _estimate_total_tokens,
    _index_state,
    _trigger_background_index,
    _semantic_search,
    _hybrid_search,
)

router = APIRouter(tags=["system"])


# --- Setup Status ---

@router.get("/api/setup-status")
async def setup_status():
    pm = ProfileManager()
    profiles = pm.list()
    store = _get_memory_store()
    memory_count = store.count()
    connectors = ConnectorRegistry.instance(_get_profile_dir())
    configured_connectors = [c.name for c in connectors.list() if c.configured]
    folders = FolderManager(_get_profile_dir())
    folder_sources = folders.list()
    return {
        "profiles": [p.name for p in profiles],
        "profile_count": len(profiles),
        "memory_count": memory_count,
        "configured_connectors": configured_connectors,
        "folder_count": len(folder_sources),
        "data_dir": str(Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))),
        "is_fresh": memory_count == 0 and len(configured_connectors) == 0 and len(folder_sources) == 0,
    }


# --- Dashboard ---

@router.get("/api/dashboard")
async def dashboard():
    store = _get_memory_store()
    memory_count = store.count()
    total_tokens = _estimate_total_tokens(_get_db())
    all_tags = store.tags()

    registry = SkillRegistry.instance()
    all_skills = registry.list_all()
    alive_skills = registry.list_alive()

    activity_entries = MemoryActivityLog(_get_db()).recent(10)

    return {
        "memory_count": memory_count,
        "memory_tokens": total_tokens,
        "tag_count": len(all_tags),
        "skill_total": len(all_skills),
        "skill_alive": len(alive_skills),
        "skills": [s.to_dict() for s in all_skills],
        "activity": [
            {
                "operation": e.operation,
                "memory_key": e.memory_key,
                "detail": e.detail,
                "age": e.age_label,
            }
            for e in activity_entries
        ],
    }


# --- Skills ---

@router.get("/api/skills")
async def list_skills():
    registry = SkillRegistry.instance()
    return [s.to_dict() for s in registry.list_all()]


# --- Global Search ---

@router.get("/api/global-search")
async def global_search(q: str = Query("", min_length=1)):
    from typing import Dict
    results: Dict[str, list] = {"memories": [], "templates": [], "connectors": [], "folders": []}
    ql = q.lower()
    store = _get_memory_store()
    for m in store.search(q, limit=10):
        results["memories"].append({"key": m.key, "preview": m.value[:100], "type": "memory"})
    from src.storage.templates import TemplateStore as _TS
    for t in _TS(_get_db()).list():
        if ql in t.name.lower() or ql in t.description.lower():
            results["templates"].append({"name": t.name, "description": t.description, "type": "template"})
    for c in _get_connectors().list():
        status = c.get_status()
        if ql in status.get("name", "").lower() or ql in status.get("display_name", "").lower():
            results["connectors"].append({"name": status["name"], "display_name": status.get("display_name", ""), "type": "connector"})
    fm = FolderManager(_get_profile_dir())
    for f in fm.list():
        if ql in f.name.lower() or ql in f.path.lower():
            results["folders"].append({"name": f.name, "path": f.path, "type": "folder"})
    return results


# --- MCP Server Status ---

@router.get("/api/mcp-status")
async def mcp_status():
    from src.core.claude_config import is_registered, get_current_config
    config = get_current_config()
    return {
        "registered": is_registered(),
        "config": config,
    }


@router.post("/api/mcp/register")
async def mcp_register(request: Request):
    from src.core.claude_config import register_mcp
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    port = int(body.get("port", 8400))
    transport = body.get("transport", "sse")
    register_mcp(port=port, transport=transport)
    logger.info("MCP registered: port=%d, transport=%s", port, transport)
    _events.emit("system", "mcp-register", f"port={port} transport={transport}")
    return {"status": "registered", "port": port, "transport": transport}


@router.post("/api/mcp/deregister")
async def mcp_deregister():
    from src.core.claude_config import deregister_mcp
    deregister_mcp()
    logger.info("MCP deregistered")
    _events.emit("system", "mcp-deregister", "removed from ~/.claude.json")
    return {"status": "deregistered"}


# --- Maintenance ---

@router.post("/api/maintenance/vacuum")
async def db_vacuum():
    conn = _get_db().conn
    await asyncio.to_thread(conn.execute, "VACUUM")
    _events.emit("system", "vacuum", "database compacted")
    return {"status": "vacuumed"}


@router.post("/api/maintenance/rebuild-fts")
async def rebuild_fts():
    _get_db().conn.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")
    _get_db().conn.commit()
    _events.emit("system", "rebuild-fts", "search index rebuilt")
    return {"status": "rebuilt"}


@router.get("/api/maintenance/db-stats")
async def db_stats():
    import shutil
    db = _get_db()
    store = _get_memory_store()
    data_dir = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
    db_size = 0
    embeddings_size = 0
    for f in data_dir.rglob("*.db"):
        sz = f.stat().st_size
        if "embedding" in f.name.lower():
            embeddings_size += sz
        else:
            db_size += sz
    disk = shutil.disk_usage(str(data_dir)) if data_dir.exists() else None
    page_count = db.conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = db.conn.execute("PRAGMA page_size").fetchone()[0]
    freelist = db.conn.execute("PRAGMA freelist_count").fetchone()[0]
    return {
        "data_dir": str(data_dir),
        "db_size_bytes": db_size,
        "db_size_mb": round(db_size / 1048576, 2),
        "embeddings_size_mb": round(embeddings_size / 1048576, 2),
        "page_count": page_count,
        "page_size": page_size,
        "freelist_pages": freelist,
        "fragmentation_pct": round(freelist / max(page_count, 1) * 100, 1),
        "disk_total_gb": round(disk.total / 1073741824, 1) if disk else None,
        "disk_free_gb": round(disk.free / 1073741824, 1) if disk else None,
        "disk_used_pct": round((disk.total - disk.free) / disk.total * 100, 1) if disk else None,
        "memory_count": store.count(),
        "schema_version": db.conn.execute("PRAGMA user_version").fetchone()[0],
    }


@router.post("/api/maintenance/trash-cleanup")
async def trash_cleanup(days: int = Query(30, ge=1)):
    store = _get_memory_store()
    removed = store.trash_cleanup(days=days)
    _events.emit("system", "trash-cleanup", f"{removed} old trash entries removed (>{days}d)")
    return {"status": "cleaned", "removed": removed}


# --- Backup & Restore ---

@router.post("/api/backups", status_code=201)
async def create_backup():
    from src.core.backup import BackupManager
    pm = ProfileManager()
    bm = BackupManager(pm.active_data_dir)
    try:
        path = bm.create_backup()
        stat = path.stat()
        logger.info("Backup created: %s (%d bytes)", path.name, stat.st_size)
        return {"filename": path.name, "size_bytes": stat.st_size}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/api/backups")
async def list_backups():
    from src.core.backup import BackupManager
    pm = ProfileManager()
    bm = BackupManager(pm.active_data_dir)
    return bm.list_backups()


@router.post("/api/backups/{filename}/restore")
async def restore_backup(filename: str):
    from src.core.backup import BackupManager
    pm = ProfileManager()
    bm = BackupManager(pm.active_data_dir)
    try:
        bm.restore_backup(filename)
        logger.info("Backup restored: %s", filename)
        return {"status": "restored", "filename": filename}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/backups/{filename}")
async def delete_backup(filename: str):
    from src.core.backup import BackupManager
    pm = ProfileManager()
    bm = BackupManager(pm.active_data_dir)
    try:
        bm.delete_backup(filename)
        return {"status": "deleted", "filename": filename}
    except ValueError as e:
        raise HTTPException(400, str(e))


# --- Webhooks ---

@router.get("/api/webhooks")
async def list_webhooks():
    from src.core.webhooks import WebhookManager
    wm = WebhookManager(_get_profile_dir())
    return [{"name": h.name, "type": h.type, "url": h.url, "enabled": h.enabled,
             "events": h.events, "chat_id": h.chat_id} for h in wm.list()]


@router.post("/api/webhooks", status_code=201)
async def add_webhook(request: Request):
    from src.core.webhooks import WebhookManager
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    wm = WebhookManager(_get_profile_dir())
    wm.add(body["name"], body["type"], body["url"],
           chat_id=body.get("chat_id", ""), session=body.get("session", "default"),
           events=body.get("events", []))
    return {"status": "created", "name": body["name"]}


@router.delete("/api/webhooks/{name}")
async def remove_webhook(name: str):
    from src.core.webhooks import WebhookManager
    wm = WebhookManager(_get_profile_dir())
    try:
        wm.remove(name)
        return {"status": "deleted"}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/webhooks/test")
async def test_webhook(request: Request):
    from src.core.webhooks import WebhookManager
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    wm = WebhookManager(_get_profile_dir())
    results = wm.notify(body.get("event", "test"), body.get("message", "Context Pilot test notification"))
    return {"results": results}


# --- Scheduler ---

@router.get("/api/scheduler")
async def scheduler_status():
    from src.core.scheduler import SyncScheduler
    s = SyncScheduler.instance()
    return s.get_status()


@router.post("/api/scheduler/start")
async def scheduler_start(interval: int = Query(30, ge=1, le=1440)):
    from src.core.scheduler import SyncScheduler
    s = SyncScheduler.instance(interval)
    s.set_interval(interval)
    s.start(_get_memory_store, lambda: _get_db(), _get_profile_dir)
    logger.info("Scheduler started with %dm interval", interval)
    _events.emit("scheduler", "start", f"{interval}m interval")
    return {"status": "started", "interval_minutes": interval}


@router.post("/api/scheduler/stop")
async def scheduler_stop():
    from src.core.scheduler import SyncScheduler
    s = SyncScheduler.instance()
    s.stop()
    logger.info("Scheduler stopped")
    _events.emit("scheduler", "stop", "manual")
    return {"status": "stopped"}


@router.post("/api/scheduler/run-now")
async def scheduler_run_now():
    from src.core.scheduler import SyncScheduler
    s = SyncScheduler.instance()
    s._get_store = _get_memory_store
    s._get_db = lambda: _get_db()
    s._get_profile_dir = _get_profile_dir
    results = await s.run_once()
    _events.emit("scheduler", "manual-run", "complete")
    return results


# --- Semantic Search ---

@router.post("/api/embeddings/index")
async def index_embeddings():
    if _index_state["status"] == "running":
        return {"status": "already_running", **_index_state}
    logger.info("Embedding index requested")
    _trigger_background_index()
    return {"status": "started"}


@router.get("/api/embeddings/index/status")
async def index_status():
    return _index_state


@router.get("/api/embeddings/stats")
async def embedding_stats():
    from src.core.embeddings import _get_store as _get_embed_store
    return _get_embed_store().stats()


@router.get("/api/semantic-search")
async def semantic_search_api(
    q: str = Query("", min_length=1),
    limit: int = Query(10, ge=1, le=50),
    mode: str = Query("hybrid", pattern="^(keyword|semantic|hybrid)$"),
):
    store = _get_memory_store()

    if mode == "keyword":
        memories = store.search(q, limit=limit)
        return [
            {**m.to_dict(), "similarity": 0, "method": "keyword"}
            for m in memories
        ]

    if mode == "semantic":
        results = _semantic_search(q, limit)
        output = []
        for key, score in results:
            try:
                m = store.get(key)
                output.append({**m.to_dict(), "similarity": score, "method": "semantic"})
            except KeyError:
                pass
        return output

    # mode == "hybrid"
    hybrid_results = _hybrid_search(q, store, top_k=limit)
    output = []
    for r in hybrid_results:
        try:
            m = store.get(r["key"])
            output.append({**m.to_dict(), "similarity": r["score"], "method": r["method"]})
        except KeyError:
            pass
    return output
