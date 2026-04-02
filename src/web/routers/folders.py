"""Folder source endpoints: list, add, update, delete, scan."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from src.storage.folders import FolderManager
from src.web.deps import (
    _events,
    _get_memory_store,
    _get_profile_dir,
    FolderSourceCreate,
    FolderSourceUpdate,
)

router = APIRouter(tags=["folders"])


@router.get("/api/folders")
async def list_folders():
    fm = FolderManager(_get_profile_dir())
    return [
        {
            "name": s.name,
            "path": s.path,
            "extensions": s.extensions,
            "recursive": s.recursive,
            "enabled": s.enabled,
            "created_at": s.created_at,
            "last_scan": s.last_scan,
            "indexed_files": s.indexed_files,
            "description": s.description,
        }
        for s in fm.list()
    ]


@router.post("/api/folders", status_code=201)
async def add_folder(req: FolderSourceCreate):
    fm = FolderManager(_get_profile_dir())
    try:
        s = fm.add(req.name, req.path, req.extensions, req.recursive, req.description)
        return {"status": "created", "name": s.name}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.put("/api/folders/{name}")
async def update_folder(name: str, req: FolderSourceUpdate):
    fm = FolderManager(_get_profile_dir())
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    try:
        fm.update(name, **updates)
        return {"status": "updated", "name": name}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.delete("/api/folders/{name}")
async def delete_folder(name: str, purge: bool = Query(False)):
    fm = FolderManager(_get_profile_dir())
    try:
        purged = 0
        if purge:
            store = _get_memory_store()
            purged = fm.purge(name, store)
        fm.remove(name)
        return {"status": "deleted", "name": name, "purged_memories": purged}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/folders/{name}/scan")
async def scan_folder(name: str):
    fm = FolderManager(_get_profile_dir())
    store = _get_memory_store()
    try:
        result = await asyncio.to_thread(fm.scan, name, store)
        _events.emit("folder", "scan", name, f"+{result.added} ~{result.updated} -{result.removed}")
        return {
            "status": "scanned",
            "name": name,
            "added": result.added,
            "updated": result.updated,
            "removed": result.removed,
            "skipped": result.skipped,
            "errors": result.errors,
        }
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/folders/scan-all")
async def scan_all_folders():
    fm = FolderManager(_get_profile_dir())
    store = _get_memory_store()
    results = await asyncio.to_thread(fm.scan_all, store)
    return {
        name: {
            "added": r.added,
            "updated": r.updated,
            "removed": r.removed,
            "skipped": r.skipped,
            "errors": r.errors,
        }
        for name, r in results.items()
    }
