"""Context Pilot Web App — FastAPI backend with HTMX frontend."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from src.core.assembler import Assembler
from src.core.block import Block, Priority
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.mermaid import MermaidCompressor
from src.core.compressors.yaml_struct import YamlStructCompressor
from collections import defaultdict

from src.core.token_budget import TokenBudget
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.storage.project import ContextConfig, ProjectMeta, ProjectStore
from src.core.compressors.code_compact import CodeCompactCompressor
from src.core.secrets import SecretDetector
from src.core.skill_registry import SkillRegistry
from src.storage.memory_activity import MemoryActivityLog
from src.connectors.registry import ConnectorRegistry
from src.core.events import EventBus
from src.storage.folders import FolderManager
from src.storage.profiles import ProfileManager, DEFAULT_ID
from src.storage.usage import UsageStore, FeedbackRecord, block_hash

import os

WEB_DIR = Path(__file__).parent
_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
DEFAULT_DB_PATH = _DATA_DIR / "data.db"

_db: Optional[Database] = None
_project_store: Optional[ProjectStore] = None
_memory_store: Optional[MemoryStore] = None
_usage_store: Optional[UsageStore] = None


def _get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(DEFAULT_DB_PATH)
    return _db


def _get_project_store() -> ProjectStore:
    global _project_store
    if _project_store is None:
        _project_store = ProjectStore(_get_db())
    return _project_store


def _get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore(_get_db())
    return _memory_store


def _get_usage_store() -> UsageStore:
    global _usage_store
    if _usage_store is None:
        _usage_store = UsageStore(_get_db())
    return _usage_store


def _make_assembler() -> Assembler:
    return Assembler(compressors=[
        BulletExtractCompressor(),
        YamlStructCompressor(),
        MermaidCompressor(),
        CodeCompactCompressor(),
    ])


def _block_to_dict(b: Block) -> Dict[str, Any]:
    return {
        "content": b.content,
        "priority": b.priority.value,
        "compress_hint": b.compress_hint,
        "token_count": b.token_count,
    }


# --- Pydantic models ---

class BlockIn(BaseModel):
    content: str
    priority: str = "medium"
    compress_hint: Optional[str] = None


class AssembleRequest(BaseModel):
    blocks: List[BlockIn]
    budget: int


class ProjectCreate(BaseModel):
    name: str
    description: str = ""


class ContextCreate(BaseModel):
    name: str


class MemoryIn(BaseModel):
    key: str
    value: str
    tags: List[str] = []


class FeedbackIn(BaseModel):
    assembly_id: str
    block_content: str
    helpful: bool


class CompressRequest(BaseModel):
    content: str
    compress_hint: str


class ProfileCreate(BaseModel):
    name: str
    description: str = ""
    copy_from: str = ""
    copy_tags: List[str] = []


class ImportMemoriesRequest(BaseModel):
    source_id: str
    tags: List[str] = []


class EstimateRequest(BaseModel):
    text: str


class FolderSourceCreate(BaseModel):
    name: str
    path: str
    extensions: List[str] = []
    recursive: bool = True
    description: str = ""


class FolderSourceUpdate(BaseModel):
    path: Optional[str] = None
    extensions: Optional[List[str]] = None
    recursive: Optional[bool] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


# --- App ---

_secret_detector = SecretDetector()


def _init_db(db_path: Optional[Path] = None) -> None:
    global _db, _project_store, _memory_store, _usage_store
    if _db is not None:
        try:
            _db.close()
        except Exception:
            pass
    _db = Database(db_path, check_same_thread=False)
    _project_store = ProjectStore(_db)
    _memory_store = MemoryStore(_db)
    _usage_store = UsageStore(_db)


def _get_profile_dir() -> Path:
    pm = ProfileManager()
    return pm.active_data_dir


def create_app(db_path: Optional[Path] = None) -> FastAPI:
    _init_db(db_path)

    app = FastAPI(title="Context Pilot", version="3.1.0")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    # --- HTML ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    # --- Health ---

    _start_time = time.time()
    _request_count = {"total": 0, "errors": 0}
    _events = EventBus.instance()

    @app.middleware("http")
    async def _count_requests(request: Request, call_next):
        _request_count["total"] += 1
        response = await call_next(request)
        if response.status_code >= 500:
            _request_count["errors"] += 1
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/events/stream", "/api/events"):
            _events.emit("api", request.method.lower(), path)
        return response

    @app.get("/health")
    async def health():
        import platform
        import os
        import shutil

        store = _get_memory_store()
        memories = store.list()
        total_tokens = sum(TokenBudget.estimate(m.value) for m in memories)

        registry = SkillRegistry.instance()
        all_skills = registry.list_all()
        alive_skills = registry.list_alive()

        pm = ProfileManager()
        profiles = pm.list()

        uptime = time.time() - _start_time
        days, rem = divmod(int(uptime), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        uptime_str = f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"

        data_dir = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
        db_size = 0
        if data_dir.exists():
            for f in data_dir.rglob("*.db"):
                db_size += f.stat().st_size
        disk = shutil.disk_usage(str(data_dir)) if data_dir.exists() else None

        return {
            "status": "healthy",
            "version": app.version,
            "uptime": uptime_str,
            "uptime_seconds": int(uptime),
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "pid": os.getpid(),
            "requests": {
                "total": _request_count["total"],
                "errors": _request_count["errors"],
            },
            "memories": {
                "count": len(memories),
                "tokens": total_tokens,
                "tags": len(store.tags()),
            },
            "skills": {
                "total": len(all_skills),
                "alive": len(alive_skills),
            },
            "profiles": {
                "count": len(profiles),
                "active": pm.active_name,
            },
            "storage": {
                "db_size_bytes": db_size,
                "db_size_mb": round(db_size / (1024 * 1024), 2),
                "disk_free_gb": round(disk.free / (1024**3), 2) if disk else None,
                "disk_total_gb": round(disk.total / (1024**3), 2) if disk else None,
            },
        }

    # --- Events (SSE + REST) ---

    from fastapi.responses import StreamingResponse

    @app.get("/api/events")
    async def get_events(limit: int = Query(50, ge=1, le=200), category: str = Query("")):
        cat = category if category else None
        return [e.to_dict() for e in _events.recent(limit, cat)]

    @app.get("/api/events/stats")
    async def event_stats():
        return _events.stats()

    @app.get("/api/events/stream")
    async def event_stream():
        q = _events.subscribe()

        async def generate():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(q.get(), timeout=30)
                        data = json.dumps(event.to_dict())
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                _events.unsubscribe(q)

        import asyncio
        return StreamingResponse(generate(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # --- Token estimation ---

    @app.post("/api/estimate")
    async def estimate_tokens(req: EstimateRequest):
        return {"tokens": TokenBudget.estimate(req.text)}

    # --- Assemble ---

    @app.post("/api/assemble")
    async def assemble(req: AssembleRequest):
        blocks = [
            Block(
                content=b.content,
                priority=Priority(b.priority),
                compress_hint=b.compress_hint,
            )
            for b in req.blocks
        ]
        assembler = _make_assembler()
        result = assembler.assemble_tracked(blocks, req.budget)

        store = _get_usage_store()
        from src.storage.usage import UsageRecord
        import time
        records = [
            UsageRecord(
                block_hash=block_hash(b.content),
                project_name=None,
                context_name=None,
                skill_name=None,
                model_id=None,
                included=True,
                token_count=b.token_count,
            )
            for b in result.blocks
        ]
        store.record_usage(records)

        return {
            "assembly_id": result.assembly_id,
            "budget": result.budget,
            "used_tokens": result.used_tokens,
            "block_count": len(result.blocks),
            "blocks": [_block_to_dict(b) for b in result.blocks],
            "dropped_count": len(result.dropped_blocks),
            "dropped": [_block_to_dict(b) for b in result.dropped_blocks],
        }

    # --- Projects ---

    @app.get("/api/projects")
    async def list_projects():
        store = _get_project_store()
        return [m.to_dict() for m in store.list_projects()]

    @app.post("/api/projects", status_code=201)
    async def create_project(req: ProjectCreate):
        store = _get_project_store()
        try:
            store.create(ProjectMeta(name=req.name, description=req.description))
            return {"status": "created", "name": req.name}
        except FileExistsError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/projects/{name}")
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

    @app.delete("/api/projects/{name}")
    async def delete_project(name: str):
        store = _get_project_store()
        try:
            store.delete(name)
            return {"status": "deleted", "name": name}
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/projects/{name}/contexts", status_code=201)
    async def add_context(name: str, req: ContextCreate):
        store = _get_project_store()
        try:
            store.add_context(name, ContextConfig(name=req.name))
            return {"status": "created", "project": name, "context": req.name}
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))

    # --- Memories ---

    @app.get("/api/memories")
    async def list_memories(
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        source: str = Query(""),
        sort: str = Query("key"),
        order: str = Query("asc"),
    ):
        store = _get_memory_store()
        offset = (page - 1) * page_size
        memories = store.list(limit=page_size, offset=offset, source=source, sort=sort, order=order)
        total = store.count(source=source)
        return {
            "memories": [m.to_dict() for m in memories],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    @app.get("/api/memories/sources")
    async def memory_sources():
        store = _get_memory_store()
        return store.sources()

    @app.get("/api/memories/search")
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
        # Count total without pagination for UI
        total_results = store.search(q, tag_list, source=source)
        total = len(total_results)
        _events.emit("memory", "search", q or "(all)", f"{total} results" + (f", source={source}" if source else ""))
        return {
            "memories": [m.to_dict() for m in results],
            "total": total,
            "page": page,
            "page_size": page_size,
            "pages": max(1, (total + page_size - 1) // page_size),
        }

    @app.get("/api/memories/{key:path}")
    async def get_memory(key: str):
        store = _get_memory_store()
        try:
            return store.get(key).to_dict()
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/memories", status_code=201)
    async def set_memory(req: MemoryIn):
        store = _get_memory_store()
        store.set(Memory(key=req.key, value=req.value, tags=req.tags))
        _events.emit("memory", "create", req.key, f"tags={req.tags}")
        return {"status": "saved", "key": req.key}

    @app.put("/api/memories/{key:path}")
    async def update_memory(key: str, req: MemoryIn):
        store = _get_memory_store()
        try:
            old = store.get(key)
        except KeyError:
            raise HTTPException(404, f"Memory '{key}' not found.")
        # Save version before overwriting
        from src.storage.versions import VersionStore
        VersionStore(_db).record(key, old.value, old.tags, old.metadata, changed_by="web")
        store.set(Memory(key=key, value=req.value, tags=req.tags))
        _events.emit("memory", "update", key)
        return {"status": "updated", "key": key}

    @app.delete("/api/memories/{key:path}")
    async def delete_memory(key: str):
        store = _get_memory_store()
        try:
            store.delete(key)
            _events.emit("memory", "delete", key)
            return {"status": "deleted", "key": key}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/memories/bulk-delete")
    async def bulk_delete_memories(keys: List[str]):
        store = _get_memory_store()
        deleted = 0
        for key in keys:
            try:
                store.delete(key)
                deleted += 1
            except KeyError:
                pass
        _events.emit("memory", "bulk-delete", f"{deleted} memories")
        return {"status": "deleted", "count": deleted}

    @app.get("/api/export-memories")
    async def export_memories(tag: str = Query("")):
        store = _get_memory_store()
        if tag:
            memories = store.search("", tags=[tag])
        else:
            memories = store.list()
        return {"memories": [m.to_dict() for m in memories]}

    # --- Knowledge Graph ---

    def _build_knowledge_graph() -> Dict[str, Any]:
        store = _get_memory_store()
        memories = store.list()

        # Category colors (Catppuccin Mocha palette)
        CATEGORY_COLORS = [
            "#89b4fa", "#a6e3a1", "#f9e2af", "#f38ba8", "#cba6f7",
            "#fab387", "#94e2d5", "#74c7ec", "#f5c2e7", "#b4befe",
        ]

        # Build nodes and detect groups
        nodes = []
        groups_seen: Dict[str, int] = {}
        tag_index: Dict[str, List[str]] = defaultdict(list)  # tag -> [memory_keys]

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

            # Skip _preamble duplicates in label
            if label == "_preamble":
                label = "(preamble)"

            nodes.append({
                "id": m.key,
                "label": label,
                "group": group,
                "title": f"<b>{m.key}</b><br>Tags: {', '.join(m.tags) or 'keine'}<br>{tokens} tokens",
                "value": size,
                "tags": m.tags,
            })

            for tag in m.tags:
                tag_index[tag].append(m.key)

        # Build edges: shared tags (cross-group connections)
        edges = []
        edge_set: set = set()
        for tag, keys in tag_index.items():
            if len(keys) > 20:
                continue  # skip overly common tags
            for i, k1 in enumerate(keys):
                g1 = "/".join(k1.split("/")[:2])
                for k2 in keys[i + 1:]:
                    g2 = "/".join(k2.split("/")[:2])
                    if g1 == g2:
                        continue  # skip within-group (vis.js handles that)
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

        # Build vis.js group config
        group_config = {}
        for group_name, idx in groups_seen.items():
            color = CATEGORY_COLORS[idx % len(CATEGORY_COLORS)]
            category = group_name.split("/")[0]
            group_config[group_name] = {
                "color": {"background": color, "border": color, "highlight": {"background": color, "border": "#fff"}},
                "font": {"color": "#cdd6f4"},
            }

        # Stats
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

    @app.get("/api/knowledge-graph")
    async def knowledge_graph():
        return _build_knowledge_graph()

    # --- Memory Activity ---

    @app.get("/api/memory-activity")
    async def get_memory_activity(limit: int = Query(20, ge=1, le=100)):
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

    # --- Dashboard ---

    @app.get("/api/dashboard")
    async def dashboard():
        store = _get_memory_store()
        memories = store.list()
        total_tokens = sum(TokenBudget.estimate(m.value) for m in memories)
        all_tags = store.tags()

        registry = SkillRegistry.instance()
        all_skills = registry.list_all()
        alive_skills = registry.list_alive()

        activity_entries = MemoryActivityLog(_db).recent(10)

        return {
            "memory_count": len(memories),
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

    @app.get("/api/skills")
    async def list_skills():
        registry = SkillRegistry.instance()
        return [s.to_dict() for s in registry.list_all()]

    # --- Memory Preview as Context ---

    @app.post("/api/preview-context")
    async def preview_context(budget: int = Query(8000, ge=100)):
        import re as _re

        _CODE = _re.compile(r"(```|def |class |function |import |from |curl |export |const |let |var )")
        _STEP = _re.compile(r"^(\d+[.)]\s|[-*]\s|#{1,3}\s)", _re.MULTILINE)
        _KV = _re.compile(r"^[A-Za-z][^:=\n]{0,40}(?::[ \t]|[ \t]*=[ \t])", _re.MULTILINE)

        def _detect_hint(text: str):
            if len(_CODE.findall(text)) >= 3: return "code_compact"
            if len(_STEP.findall(text)) >= 3: return "mermaid"
            if len(_KV.findall(text)) >= 3: return "yaml_struct"
            if len(text) > 200: return "bullet_extract"
            return None

        store = _get_memory_store()
        memories = store.list()
        if not memories:
            return {"blocks": [], "dropped": [], "used_tokens": 0, "budget": budget,
                    "input_count": 0, "block_count": 0, "dropped_count": 0}

        blocks = []
        for m in memories:
            content = f"[{m.key}] {m.value}"
            hint = _detect_hint(m.value)
            blocks.append(Block(content=content, priority=Priority.MEDIUM, compress_hint=hint))

        # Select blocks that fit within budget (by token count, greedy)
        selected = []
        dropped = []
        remaining = budget
        for b in blocks:
            if b.token_count <= remaining:
                selected.append(b)
                remaining -= b.token_count
            else:
                dropped.append(b)

        # Assemble selected (may compress further)
        assembler = _make_assembler()
        if selected:
            assembled = assembler.assemble(selected, budget)
        else:
            assembled = []

        return {
            "budget": budget,
            "used_tokens": sum(b.token_count for b in assembled),
            "input_count": len(blocks),
            "block_count": len(assembled),
            "dropped_count": len(dropped),
            "blocks": [_block_to_dict(b) for b in assembled],
            "dropped": [
                {"content_preview": b.content[:80], "token_count": b.token_count}
                for b in dropped[:20]
            ],
        }

    # --- Test Compression ---

    @app.post("/api/test-compress")
    async def test_compress(req: CompressRequest):
        block = Block(content=req.content, priority=Priority.MEDIUM, compress_hint=req.compress_hint)
        assembler = _make_assembler()
        compressor = assembler._registry.get(req.compress_hint)
        if not compressor:
            return {"error": f"Compressor '{req.compress_hint}' not found."}
        original_tokens = block.token_count
        compressed = compressor.compress(block)
        return {
            "original_tokens": original_tokens,
            "compressed_tokens": compressed.token_count,
            "savings_pct": round((1 - compressed.token_count / max(1, original_tokens)) * 100, 1),
            "compressed_content": compressed.content,
        }

    # --- Memory Tags ---

    @app.get("/api/memory-tags")
    async def memory_tags():
        store = _get_memory_store()
        return store.tags()

    # --- Feedback ---

    @app.post("/api/feedback")
    async def submit_feedback(req: FeedbackIn):
        store = _get_usage_store()
        bh = block_hash(req.block_content)
        store.record_feedback(FeedbackRecord(
            assembly_id=req.assembly_id,
            block_hash=bh,
            helpful=req.helpful,
        ))
        return {"status": "recorded", "block_hash": bh}

    # --- MCP Server Status ---

    @app.get("/api/mcp-status")
    async def mcp_status():
        from src.core.claude_config import is_registered, get_current_config
        config = get_current_config()
        return {
            "registered": is_registered(),
            "config": config,
        }

    # --- Import ---

    @app.post("/api/import/claude-md")
    async def import_claude_md(file: UploadFile = File(...)):
        from src.importers.claude import import_claude_file
        import tempfile
        store = _get_memory_store()
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)
        try:
            memories = import_claude_file(tmp_path)
            count = 0
            for m in memories:
                store.set(m)
                count += 1
            _events.emit("import", "claude-md", file.filename, f"{count} memories")
            return {"status": "imported", "count": count, "filename": file.filename}
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.post("/api/import/copilot-md")
    async def import_copilot_md(file: UploadFile = File(...)):
        from src.importers.copilot import import_copilot_file
        import tempfile
        store = _get_memory_store()
        content = await file.read()
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as f:
            f.write(content)
            tmp_path = Path(f.name)
        try:
            memories = import_copilot_file(tmp_path)
            count = 0
            for m in memories:
                store.set(m)
                count += 1
            _events.emit("import", "copilot-md", file.filename, f"{count} memories")
            return {"status": "imported", "count": count, "filename": file.filename}
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.post("/api/import/sqlite")
    async def import_sqlite_db(file: UploadFile = File(...)):
        from src.importers.sqlite import detect_sqlite_type, import_memory_mcp
        import tempfile
        store = _get_memory_store()
        content = await file.read()
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

    # --- Profiles ---

    @app.get("/api/profiles")
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

    @app.post("/api/profiles", status_code=201)
    async def create_profile(req: ProfileCreate):
        pm = ProfileManager()
        try:
            p = pm.create(req.name, req.description)
            imported = 0
            if req.copy_from:
                tags = req.copy_tags if req.copy_tags else None
                imported = pm.import_memories_from(p.id, req.copy_from, tags)
            _events.emit("profile", "create", p.name, f"imported {imported} memories" if imported else "")
            return {"status": "created", "id": p.id, "name": p.name, "imported": imported}
        except ValueError as e:
            raise HTTPException(409, str(e))

    def _reload_profile_deps():
        profile_dir = _get_profile_dir()
        ConnectorRegistry.reload(profile_dir)
        from src.core.embeddings import set_data_dir
        set_data_dir(profile_dir)
        from src.core.scheduler import SyncScheduler
        s = SyncScheduler.instance()
        if s.running:
            s.stop()

    @app.post("/api/profiles/{pid}/switch")
    async def switch_profile(pid: str):
        pm = ProfileManager()
        try:
            new_path = pm.switch(pid)
            _init_db(new_path)
            _reload_profile_deps()
            _events.emit("profile", "switch", pm.active_name)
            return {"status": "switched", "active": pid, "name": pm.active_name}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.put("/api/profiles/{pid}")
    async def rename_profile(pid: str, new_name: str = Query(...), description: str = Query("")):
        pm = ProfileManager()
        try:
            pm.rename(pid, new_name, description)
            return {"status": "renamed", "id": pid, "new_name": new_name}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/profiles/{pid}/duplicate")
    async def duplicate_profile(pid: str, new_name: str = Query(...), description: str = Query("")):
        pm = ProfileManager()
        try:
            p = pm.duplicate(pid, new_name, description)
            return {"status": "duplicated", "id": p.id, "name": p.name}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/profiles/{pid}")
    async def delete_profile(pid: str):
        pm = ProfileManager()
        try:
            pm.delete(pid)
            if pm.active_id == DEFAULT_ID:
                _init_db(pm.active_db_path)
            return {"status": "deleted", "id": pid}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.get("/api/profiles/{pid}/tags")
    async def get_profile_tags(pid: str):
        pm = ProfileManager()
        try:
            return pm.get_profile_tags(pid)
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/profiles/{pid}/import-memories")
    async def import_memories_into_profile(pid: str, req: ImportMemoriesRequest):
        pm = ProfileManager()
        tags = req.tags if req.tags else None
        try:
            count = pm.import_memories_from(pid, req.source_id, tags)
            _events.emit("profile", "import", pm.get(pid).name,
                         f"{count} memories imported from {pm.get(req.source_id).name}")
            if pid == pm.active_id:
                _init_db(pm.active_db_path)
            return {"status": "imported", "count": count}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/profiles/{pid}/preview-import")
    async def preview_import(pid: str, req: ImportMemoriesRequest):
        pm = ProfileManager()
        tags = req.tags if req.tags else None
        try:
            return pm.preview_import(pid, req.source_id, tags)
        except KeyError as e:
            raise HTTPException(404, str(e))

    # --- Secrets / Sensitivity ---

    @app.get("/api/sensitivity")
    async def memory_sensitivity():
        store = _get_memory_store()
        memories = store.list()
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
        # Sort: critical first, then high, medium, low, none
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

    @app.get("/api/redacted")
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

    # --- Folder Sources ---

    @app.get("/api/folders")
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

    @app.post("/api/folders", status_code=201)
    async def add_folder(req: FolderSourceCreate):
        fm = FolderManager(_get_profile_dir())
        try:
            s = fm.add(req.name, req.path, req.extensions, req.recursive, req.description)
            return {"status": "created", "name": s.name}
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.put("/api/folders/{name}")
    async def update_folder(name: str, req: FolderSourceUpdate):
        fm = FolderManager(_get_profile_dir())
        updates = {k: v for k, v in req.model_dump().items() if v is not None}
        try:
            fm.update(name, **updates)
            return {"status": "updated", "name": name}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.delete("/api/folders/{name}")
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

    @app.post("/api/folders/{name}/scan")
    async def scan_folder(name: str):
        fm = FolderManager(_get_profile_dir())
        store = _get_memory_store()
        try:
            result = fm.scan(name, store)
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

    @app.post("/api/folders/scan-all")
    async def scan_all_folders():
        fm = FolderManager(_get_profile_dir())
        store = _get_memory_store()
        results = fm.scan_all(store)
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

    # --- Memory Versions ---

    from src.storage.versions import VersionStore
    from src.storage.relations import RelationStore
    from src.storage.templates import TemplateStore, ContextTemplate

    @app.get("/api/memories/{key:path}/versions")
    async def memory_versions(key: str, limit: int = Query(20, ge=1, le=100)):
        vs = VersionStore(_db)
        versions = vs.history(key, limit)
        return [{"id": v.id, "value": v.value[:500], "tags": v.tags,
                 "changed_by": v.changed_by, "created_at": v.created_at} for v in versions]

    # --- Memory Relations ---

    @app.get("/api/relations/{key:path}")
    async def get_relations(key: str):
        rs = RelationStore(_db)
        return [{"id": r.id, "source_key": r.source_key, "target_key": r.target_key,
                 "relation_type": r.relation_type, "created_at": r.created_at} for r in rs.get_relations(key)]

    @app.post("/api/relations", status_code=201)
    async def add_relation(request: Request):
        body = await request.json()
        rs = RelationStore(_db)
        try:
            r = rs.add(body["source_key"], body["target_key"], body.get("relation_type", "related"))
            _events.emit("memory", "link", f"{r.source_key} -> {r.target_key}", r.relation_type)
            return {"id": r.id, "source_key": r.source_key, "target_key": r.target_key}
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.delete("/api/relations/{relation_id}")
    async def remove_relation(relation_id: int):
        rs = RelationStore(_db)
        try:
            rs.remove(relation_id)
            return {"status": "deleted"}
        except KeyError as e:
            raise HTTPException(404, str(e))

    # --- Context Templates ---

    @app.get("/api/templates")
    async def list_templates():
        ts = TemplateStore(_db)
        return [{"name": t.name, "description": t.description, "tag_filter": t.tag_filter,
                 "key_filter": t.key_filter, "budget": t.budget} for t in ts.list()]

    @app.post("/api/templates", status_code=201)
    async def save_template(request: Request):
        body = await request.json()
        ts = TemplateStore(_db)
        t = ContextTemplate(
            name=body["name"], description=body.get("description", ""),
            tag_filter=body.get("tag_filter", []), key_filter=body.get("key_filter", ""),
            budget=body.get("budget", 4000),
        )
        ts.save(t)
        _events.emit("template", "save", t.name)
        return {"status": "saved", "name": t.name}

    @app.delete("/api/templates/{name}")
    async def delete_template(name: str):
        ts = TemplateStore(_db)
        try:
            ts.delete(name)
            return {"status": "deleted"}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/templates/{name}/assemble")
    async def assemble_template(name: str):
        ts = TemplateStore(_db)
        try:
            t = ts.get(name)
        except KeyError:
            raise HTTPException(404, f"Template '{name}' not found")

        store = _get_memory_store()
        memories = store.list()

        # Apply filters
        if t.tag_filter:
            memories = [m for m in memories if any(tag in m.tags for tag in t.tag_filter)]
        if t.key_filter:
            memories = [m for m in memories if t.key_filter.lower() in m.key.lower()]

        total_tokens = sum(TokenBudget.estimate(m.value) for m in memories)
        included = []
        used = 0
        for m in memories:
            tokens = TokenBudget.estimate(m.value)
            if used + tokens <= t.budget:
                included.append({"key": m.key, "tokens": tokens, "preview": m.value[:200]})
                used += tokens

        return {
            "template": t.name,
            "budget": t.budget,
            "used_tokens": used,
            "included": len(included),
            "total_matching": len(memories),
            "blocks": included,
        }

    # --- Export as CLAUDE.md ---

    @app.get("/api/export-claude-md")
    async def export_claude_md(tags: str = Query(""), key_prefix: str = Query("")):
        store = _get_memory_store()
        memories = store.list()

        if tags:
            tag_list = [t.strip() for t in tags.split(",") if t.strip()]
            memories = [m for m in memories if any(t in m.tags for t in tag_list)]
        if key_prefix:
            memories = [m for m in memories if m.key.startswith(key_prefix)]

        sections = []
        for m in sorted(memories, key=lambda x: x.key):
            heading = m.key.replace("/", " > ").title()
            sections.append(f"## {heading}\n\n{m.value}")

        content = "# Context Pilot Export\n\n" + "\n\n---\n\n".join(sections)
        return {"content": content, "memory_count": len(memories),
                "token_count": TokenBudget.estimate(content)}

    # --- Duplicate Detection ---

    @app.get("/api/duplicates")
    async def find_duplicates_api(threshold: float = Query(0.6, ge=0.3, le=1.0)):
        from src.core.duplicates import find_duplicates
        store = _get_memory_store()
        groups = find_duplicates(store.list(), threshold)
        return [{"keys": g.keys, "similarity": g.similarity, "sample": g.sample} for g in groups]

    @app.get("/api/similar/{key:path}")
    async def find_similar_api(key: str, threshold: float = Query(0.5, ge=0.3, le=1.0)):
        from src.core.duplicates import find_similar
        store = _get_memory_store()
        try:
            target = store.get(key)
        except KeyError:
            raise HTTPException(404, f"Memory '{key}' not found")
        results = find_similar(target, store.list(), threshold)
        return [{"key": k, "similarity": s} for k, s in results]

    # --- Webhooks ---

    from src.core.webhooks import WebhookManager

    @app.get("/api/webhooks")
    async def list_webhooks():
        wm = WebhookManager(_get_profile_dir())
        return [{"name": h.name, "type": h.type, "url": h.url, "enabled": h.enabled,
                 "events": h.events, "chat_id": h.chat_id} for h in wm.list()]

    @app.post("/api/webhooks", status_code=201)
    async def add_webhook(request: Request):
        body = await request.json()
        wm = WebhookManager(_get_profile_dir())
        wm.add(body["name"], body["type"], body["url"],
               chat_id=body.get("chat_id", ""), session=body.get("session", "default"),
               events=body.get("events", []))
        return {"status": "created", "name": body["name"]}

    @app.delete("/api/webhooks/{name}")
    async def remove_webhook(name: str):
        wm = WebhookManager(_get_profile_dir())
        try:
            wm.remove(name)
            return {"status": "deleted"}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.post("/api/webhooks/test")
    async def test_webhook(request: Request):
        body = await request.json()
        wm = WebhookManager(_get_profile_dir())
        results = wm.notify(body.get("event", "test"), body.get("message", "Context Pilot test notification"))
        return {"results": results}

    # --- Scheduler ---

    from src.core.scheduler import SyncScheduler

    @app.get("/api/scheduler")
    async def scheduler_status():
        s = SyncScheduler.instance()
        return s.get_status()

    @app.post("/api/scheduler/start")
    async def scheduler_start(interval: int = Query(30, ge=1, le=1440)):
        s = SyncScheduler.instance(interval)
        s.set_interval(interval)
        s.start(_get_memory_store, lambda: _db, _get_profile_dir)
        _events.emit("scheduler", "start", f"{interval}m interval")
        return {"status": "started", "interval_minutes": interval}

    @app.post("/api/scheduler/stop")
    async def scheduler_stop():
        s = SyncScheduler.instance()
        s.stop()
        _events.emit("scheduler", "stop", "manual")
        return {"status": "stopped"}

    @app.post("/api/scheduler/run-now")
    async def scheduler_run_now():
        s = SyncScheduler.instance()
        s._get_store = _get_memory_store
        s._get_db = lambda: _db
        s._get_profile_dir = _get_profile_dir
        results = await s.run_once()
        _events.emit("scheduler", "manual-run", "complete")
        return results

    # --- Semantic Search ---

    from src.core.embeddings import index_memories as _index_memories, semantic_search as _semantic_search, get_backend as _embed_backend

    @app.post("/api/embeddings/index")
    async def index_embeddings():
        store = _get_memory_store()
        memories = store.list()
        stats = _index_memories(memories)
        _events.emit("system", "index", "embeddings", f"{stats['indexed']} indexed, {stats['skipped']} skipped ({stats['backend']})")
        return stats

    @app.get("/api/embeddings/stats")
    async def embedding_stats():
        from src.core.embeddings import _get_store as _get_embed_store
        return _get_embed_store().stats()

    @app.get("/api/semantic-search")
    async def semantic_search_api(q: str = Query("", min_length=1), limit: int = Query(10, ge=1, le=50)):
        results = _semantic_search(q, limit)
        store = _get_memory_store()
        output = []
        for key, score in results:
            try:
                m = store.get(key)
                output.append({**m.to_dict(), "similarity": score})
            except KeyError:
                pass
        return output

    # --- Connectors (Plugin Architecture) ---

    def _get_connectors():
        return ConnectorRegistry.instance(_get_profile_dir())

    def _get_connector(name: str):
        c = _get_connectors().get(name)
        if not c:
            raise HTTPException(404, f"Connector '{name}' not found")
        return c

    @app.get("/api/connectors")
    async def list_connectors():
        return [c.get_status() for c in _get_connectors().list()]

    @app.get("/api/connectors/{name}")
    async def connector_status(name: str):
        return _get_connector(name).get_status()

    @app.post("/api/connectors/{name}/setup")
    async def connector_setup(name: str, request: Request):
        c = _get_connector(name)
        body = await request.json()
        c.configure(body)
        result = c.test_connection()
        _events.emit("connector", "setup", name, f"ok={result.get('ok')}")
        return {"status": "configured", "test": result}

    @app.put("/api/connectors/{name}")
    async def connector_update(name: str, request: Request):
        c = _get_connector(name)
        if not c.configured:
            raise HTTPException(400, f"Connector '{name}' not configured yet.")
        body = await request.json()
        c.update(body)
        return {"status": "updated"}

    @app.post("/api/connectors/{name}/test")
    async def connector_test(name: str):
        c = _get_connector(name)
        return c.test_connection()

    @app.post("/api/connectors/{name}/sync")
    async def connector_sync(name: str):
        c = _get_connector(name)
        store = _get_memory_store()
        result = c.sync(store)
        _events.emit("connector", "sync", name, f"+{result.added} ~{result.updated} -{result.removed}")
        return {"status": "synced", **result.to_dict()}

    @app.post("/api/connectors/{name}/enable")
    async def connector_enable(name: str, enabled: bool = Query(True)):
        c = _get_connector(name)
        c.set_enabled(enabled)
        return {"status": "updated", "enabled": enabled}

    @app.delete("/api/connectors/{name}")
    async def connector_remove(name: str, purge: bool = Query(False)):
        c = _get_connector(name)
        purged = 0
        if purge:
            store = _get_memory_store()
            purged = c.purge(store)
        c.remove()
        _events.emit("connector", "remove", name, f"purged={purged}")
        return {"status": "removed", "purged_memories": purged}

    return app


app = create_app(DEFAULT_DB_PATH)
