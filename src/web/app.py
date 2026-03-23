"""Context Pilot Web App — FastAPI backend with HTMX frontend."""
from __future__ import annotations

import json
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
from src.storage.profiles import ProfileManager
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


class EstimateRequest(BaseModel):
    text: str


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


def create_app(db_path: Optional[Path] = None) -> FastAPI:
    _init_db(db_path)

    app = FastAPI(title="Context Pilot", version="0.5.0")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    # --- HTML ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

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
    async def list_memories():
        store = _get_memory_store()
        return [m.to_dict() for m in store.list()]

    @app.get("/api/memories/search")
    async def search_memories(
        q: str = Query(""),
        tags: str = Query(""),
    ):
        store = _get_memory_store()
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        results = store.search(q, tag_list)
        return [m.to_dict() for m in results]

    @app.get("/api/memories/{key}")
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
        return {"status": "saved", "key": req.key}

    @app.put("/api/memories/{key}")
    async def update_memory(key: str, req: MemoryIn):
        store = _get_memory_store()
        try:
            store.get(key)  # Verify exists
        except KeyError:
            raise HTTPException(404, f"Memory '{key}' not found.")
        store.set(Memory(key=key, value=req.value, tags=req.tags))
        return {"status": "updated", "key": key}

    @app.delete("/api/memories/{key}")
    async def delete_memory(key: str):
        store = _get_memory_store()
        try:
            store.delete(key)
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
            "active": pm.active_name,
            "profiles": [
                {
                    "name": p.name,
                    "description": p.description,
                    "memory_count": p.memory_count,
                    "created_at": p.created_at,
                    "is_default": p.is_default,
                    "is_active": p.name == pm.active_name,
                }
                for p in profiles
            ],
        }

    @app.post("/api/profiles", status_code=201)
    async def create_profile(req: ProfileCreate):
        pm = ProfileManager()
        try:
            p = pm.create(req.name, req.description)
            return {"status": "created", "name": p.name}
        except ValueError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/profiles/{name}/switch")
    async def switch_profile(name: str):
        pm = ProfileManager()
        try:
            new_path = pm.switch(name)
            _init_db(new_path)
            return {"status": "switched", "active": name, "db_path": str(new_path)}
        except KeyError as e:
            raise HTTPException(404, str(e))

    @app.put("/api/profiles/{name}")
    async def rename_profile(name: str, new_name: str = Query(...), description: str = Query("")):
        pm = ProfileManager()
        try:
            pm.rename(name, new_name, description)
            return {"status": "renamed", "old_name": name, "new_name": new_name}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.post("/api/profiles/{name}/duplicate")
    async def duplicate_profile(name: str, new_name: str = Query(...), description: str = Query("")):
        pm = ProfileManager()
        try:
            p = pm.duplicate(name, new_name, description)
            return {"status": "duplicated", "name": p.name}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

    @app.delete("/api/profiles/{name}")
    async def delete_profile(name: str):
        pm = ProfileManager()
        try:
            pm.delete(name)
            if pm.active_name == "default":
                _init_db(pm.active_db_path)
            return {"status": "deleted", "name": name}
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))

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

    @app.get("/api/memories/{key}/redacted")
    async def get_memory_redacted(key: str):
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

    return app


app = create_app(DEFAULT_DB_PATH)
