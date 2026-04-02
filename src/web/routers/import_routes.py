"""Import endpoints: JSON, CLAUDE.md, Copilot .md, SQLite."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from src.core.log import get_logger

logger = get_logger("routers.import")

from src.web.deps import (
    MAX_UPLOAD_BYTES,
    _events,
    _get_memory_store,
)

router = APIRouter(tags=["import"])


@router.post("/api/import/json")
async def import_json(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 50 MB)")
    store = _get_memory_store()
    try:
        count = store.import_json(content.decode("utf-8"), merge=True)
        logger.info("JSON import: %d memories from %s", count, file.filename)
        _events.emit("import", "json", file.filename or "upload", f"{count} memories")
        return {"status": "imported", "count": count, "filename": file.filename}
    except Exception as e:
        raise HTTPException(400, f"Invalid JSON: {e}")


@router.post("/api/import/claude-md")
async def import_claude_md(file: UploadFile = File(...)):
    from src.importers.claude import import_claude_file
    import tempfile
    store = _get_memory_store()
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 50 MB)")
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(content)
        tmp_path = Path(f.name)
    try:
        memories = import_claude_file(tmp_path)
        count = 0
        for m in memories:
            store.set(m)
            count += 1
        logger.info("CLAUDE.md import: %d memories from %s", count, file.filename)
        _events.emit("import", "claude-md", file.filename, f"{count} memories")
        return {"status": "imported", "count": count, "filename": file.filename}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/api/import/copilot-md")
async def import_copilot_md(file: UploadFile = File(...)):
    from src.importers.copilot import import_copilot_file
    import tempfile
    store = _get_memory_store()
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 50 MB)")
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
        f.write(content)
        tmp_path = Path(f.name)
    try:
        memories = import_copilot_file(tmp_path)
        count = 0
        for m in memories:
            store.set(m)
            count += 1
        logger.info("Copilot .md import: %d memories from %s", count, file.filename)
        _events.emit("import", "copilot-md", file.filename, f"{count} memories")
        return {"status": "imported", "count": count, "filename": file.filename}
    finally:
        tmp_path.unlink(missing_ok=True)


@router.post("/api/import/sqlite")
async def import_sqlite_db(file: UploadFile = File(...)):
    from src.importers.sqlite import detect_sqlite_type, import_memory_mcp
    import tempfile
    store = _get_memory_store()
    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 50 MB)")
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        f.write(content)
        tmp_path = Path(f.name)
    try:
        db_type = detect_sqlite_type(tmp_path)
        if db_type != "memory-mcp":
            return {"status": "error", "message": "Unknown SQLite format"}
        memories = import_memory_mcp(tmp_path)
        count = 0
        for m in memories:
            store.set(m)
            count += 1
        return {"status": "imported", "count": count, "filename": file.filename}
    finally:
        tmp_path.unlink(missing_ok=True)
