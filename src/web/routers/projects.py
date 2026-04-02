"""Project endpoints: list, create, get, delete, add context."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from src.storage.project import ContextConfig, ProjectMeta
from src.web.deps import (
    _get_project_store,
    ContextCreate,
    ProjectCreate,
)

router = APIRouter(tags=["projects"])


@router.get("/api/projects")
async def list_projects():
    store = _get_project_store()
    return [m.to_dict() for m in store.list_projects()]


@router.post("/api/projects", status_code=201)
async def create_project(req: ProjectCreate):
    store = _get_project_store()
    try:
        store.create(ProjectMeta(name=req.name, description=req.description))
        return {"status": "created", "name": req.name}
    except FileExistsError as e:
        raise HTTPException(409, str(e))


@router.get("/api/projects/{name}")
async def get_project(name: str):
    store = _get_project_store()
    try:
        meta, contexts = store.load(name)
        return {
            "meta": meta.to_dict(),
            "contexts": [c.to_dict() for c in contexts],
        }
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.delete("/api/projects/{name}")
async def delete_project(name: str):
    store = _get_project_store()
    try:
        store.delete(name)
        return {"status": "deleted", "name": name}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/api/projects/{name}/contexts", status_code=201)
async def add_context(name: str, req: ContextCreate):
    store = _get_project_store()
    try:
        store.add_context(name, ContextConfig(name=req.name))
        return {"status": "created", "project": name, "context": req.name}
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))
