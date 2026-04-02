"""Shared dependencies for all web routers."""
from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from src.connectors.registry import ConnectorRegistry
from src.core.assembler import Assembler
from src.core.block import Block, Priority
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.code_compact import CodeCompactCompressor
from src.core.compressors.mermaid import MermaidCompressor
from src.core.compressors.yaml_struct import YamlStructCompressor
from src.core.compress_detect import detect_compress_hint as _detect_compress_hint
from src.core.events import EventBus
from src.core.secrets import SecretDetector
from src.core.token_budget import TokenBudget
from src.storage.db import Database
from src.storage.folders import FolderManager
from src.storage.memory import Memory, MemoryStore
from src.storage.profiles import ProfileManager, DEFAULT_ID
from src.storage.project import ContextConfig, ProjectMeta, ProjectStore
from src.core.log import get_logger
from src.storage.usage import UsageStore, FeedbackRecord, block_hash

logger = get_logger("web.deps")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

API_KEY = os.environ.get("CONTEXTPILOT_API_KEY")

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


_secret_detector = SecretDetector()


def _estimate_total_tokens(db: Database) -> int:
    row = db.conn.execute("SELECT SUM(LENGTH(value)) FROM memories").fetchone()
    total_chars = row[0] if row and row[0] else 0
    return int(total_chars / 3.5)


def _init_db(db_path: Optional[Path] = None) -> None:
    global _db, _project_store, _memory_store, _usage_store
    if _db is not None:
        try:
            _db.close()
        except Exception:
            pass
    logger.info("Initializing database at %s", db_path)
    _db = Database(db_path, check_same_thread=False)
    _project_store = ProjectStore(_db)
    _memory_store = MemoryStore(_db)
    _usage_store = UsageStore(_db)


def _get_profile_dir() -> Path:
    pm = ProfileManager()
    return pm.active_data_dir


def _get_connectors():
    return ConnectorRegistry.instance(_get_profile_dir())


def _get_connector(name: str):
    c = _get_connectors().get(name)
    if not c:
        raise HTTPException(404, f"Connector '{name}' not found")
    return c


_events = EventBus.instance()

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


class InboundPayload(BaseModel):
    key: str
    value: str
    tags: List[str] = []


class ContextCreate(BaseModel):
    name: str


class MemoryIn(BaseModel):
    key: str
    value: str
    tags: List[str] = []
    ttl_seconds: Optional[float] = None
    category: str = "persistent"


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
    conflict_resolution: str = "skip"


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


# --- Embeddings / Indexing ---

from src.core.embeddings import (
    index_memories as _index_memories,
    semantic_search as _semantic_search,
    get_backend as _embed_backend,
    index_single_memory as _index_single,
    remove_from_index as _remove_from_index,
    get_active_dir as _embed_active_dir,
    hybrid_search as _hybrid_search,
)

_index_lock = threading.Lock()
_index_state = {"status": "idle", "indexed": 0, "skipped": 0, "total": 0, "backend": _embed_backend()}


def _run_index_background(profile_dir=None):
    if not _index_lock.acquire(blocking=False):
        return
    try:
        target_dir = profile_dir or _embed_active_dir()
        _index_state.update(status="running", indexed=0, skipped=0, total=0)
        logger.info("Background indexing started for %s", target_dir.name)
        _events.emit("system", "index-start", "embeddings", f"Background indexing started ({target_dir.name})")
        store = _get_memory_store()
        memories = store.list()
        _index_state["total"] = len(memories)
        stats = _index_memories(memories, profile_dir=target_dir)
        if stats.get("aborted"):
            _index_state.update(status="aborted")
            logger.warning("Indexing aborted — profile changed during run")
            _events.emit("system", "index-abort", "embeddings", "Profile changed during indexing")
        else:
            _index_state.update(status="done", indexed=stats["indexed"], skipped=stats["skipped"], backend=stats["backend"])
            logger.info("Indexing complete: %d indexed, %d skipped (%s)", stats["indexed"], stats["skipped"], stats["backend"])
            _events.emit("system", "index", "embeddings", f"{stats['indexed']} indexed, {stats['skipped']} skipped ({stats['backend']})")
    except Exception as e:
        _index_state["status"] = "error"
        logger.error("Background indexing failed: %s", e, exc_info=True)
        _events.emit("system", "index-error", "embeddings", str(e))
    finally:
        _index_lock.release()


def _trigger_background_index():
    t = threading.Thread(target=_run_index_background, daemon=True)
    t.start()
