"""Profile endpoints: list, create, switch, rename, duplicate, delete, import, export."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile

from src.core.log import get_logger

logger = get_logger("routers.profiles")

from src.connectors.registry import ConnectorRegistry
from src.storage.profiles import ProfileManager, DEFAULT_ID
from src.web.deps import (
    MAX_UPLOAD_BYTES,
    _events,
    _get_profile_dir,
    _init_db,
    _trigger_background_index,
    ImportMemoriesRequest,
    ProfileCreate,
)

router = APIRouter(tags=["profiles"])


def _reload_profile_deps():
    profile_dir = _get_profile_dir()
    ConnectorRegistry.reload(profile_dir)
    from src.core.embeddings import set_data_dir
    set_data_dir(profile_dir)
    from src.core.scheduler import SyncScheduler
    s = SyncScheduler.instance()
    if s.running:
        s.stop()


@router.get("/api/profiles")
async def list_profiles():
    pm = ProfileManager()
    profiles = pm.list()
    return {
        "active": pm.active_id,
        "active_name": pm.active_name,
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "description": p.description,
                "memory_count": p.memory_count,
                "created_at": p.created_at,
                "is_default": p.is_default,
                "is_active": p.id == pm.active_id,
            }
            for p in profiles
        ],
    }


@router.post("/api/profiles", status_code=201)
async def create_profile(req: ProfileCreate):
    if not req.name or not req.name.strip():
        raise HTTPException(400, "name must be a non-empty string")
    pm = ProfileManager()
    try:
        p = pm.create(req.name, req.description)
        imported = 0
        if req.copy_from:
            tags = req.copy_tags if req.copy_tags else None
            result = pm.import_memories_from(p.id, req.copy_from, tags)
            imported = result["imported"]
        logger.info("Profile '%s' created (imported %d memories)", p.name, imported)
        _events.emit("profile", "create", p.name, f"imported {imported} memories" if imported else "")
        return {"status": "created", "id": p.id, "name": p.name, "imported": imported}
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.post("/api/profiles/{pid}/switch")
async def switch_profile(pid: str):
    pm = ProfileManager()
    try:
        new_path = pm.switch(pid)
        _init_db(new_path)
        _reload_profile_deps()
        logger.info("Switched to profile '%s'", pm.active_name)
        _events.emit("profile", "switch", pm.active_name)
        _trigger_background_index()
        return {"status": "switched", "active": pid, "name": pm.active_name}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.put("/api/profiles/{pid}")
async def rename_profile(pid: str, new_name: str = Query(...), description: str = Query("")):
    pm = ProfileManager()
    try:
        pm.rename(pid, new_name, description)
        return {"status": "renamed", "id": pid, "new_name": new_name}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.post("/api/profiles/{pid}/duplicate")
async def duplicate_profile(pid: str, new_name: str = Query(...), description: str = Query("")):
    pm = ProfileManager()
    try:
        p = pm.duplicate(pid, new_name, description)
        return {"status": "duplicated", "id": p.id, "name": p.name}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.delete("/api/profiles/{pid}")
async def delete_profile(pid: str):
    pm = ProfileManager()
    try:
        pm.delete(pid)
        logger.info("Profile '%s' deleted", pid)
        if pm.active_id == DEFAULT_ID:
            _init_db(pm.active_db_path)
        return {"status": "deleted", "id": pid}
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))


@router.get("/api/profiles/{pid}/tags")
async def get_profile_tags(pid: str):
    pm = ProfileManager()
    try:
        return pm.get_profile_tags(pid)
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/profiles/{pid}/import-memories")
async def import_memories_into_profile(pid: str, req: ImportMemoriesRequest):
    pm = ProfileManager()
    tags = req.tags if req.tags else None
    try:
        result = pm.import_memories_from(pid, req.source_id, tags, req.conflict_resolution)
        detail = f"{result['imported']} imported"
        if result['overwritten']:
            detail += f", {result['overwritten']} overwritten"
        if result['skipped']:
            detail += f", {result['skipped']} skipped"
        _events.emit("profile", "import", pm.get(pid).name,
                     f"{detail} from {pm.get(req.source_id).name}")
        if pid == pm.active_id:
            _init_db(pm.active_db_path)
        return {"status": "imported", **result}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/profiles/{pid}/preview-import")
async def preview_import(pid: str, req: ImportMemoriesRequest):
    pm = ProfileManager()
    tags = req.tags if req.tags else None
    try:
        return pm.preview_import(pid, req.source_id, tags)
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.get("/api/profiles/{pid}/export")
async def export_profile(pid: str):
    pm = ProfileManager()
    try:
        data = pm.export_profile(pid)
        profile = pm.get(pid)
        filename = f"contextpilot-{profile.name}.zip"
        _events.emit("profile", "export", profile.name)
        return Response(
            content=data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/profiles/import-zip", status_code=201)
async def import_profile_zip(file: UploadFile = File(...), name: str = Query("")):
    pm = ProfileManager()
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 50 MB)")
    try:
        p = pm.import_profile(content, name or None)
        _events.emit("profile", "import-zip", p.name, f"from {file.filename}")
        return {"status": "imported", "id": p.id, "name": p.name}
    except ValueError as e:
        raise HTTPException(400, str(e))
