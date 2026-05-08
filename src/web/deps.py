"""Shared dependencies for all web routers."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel

from src.connectors.registry import ConnectorRegistry
from src.core.assembler import Assembler
from src.core.block import Block
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.code_compact import CodeCompactCompressor
from src.core.compressors.mermaid import MermaidCompressor
from src.core.compressors.yaml_struct import YamlStructCompressor
from src.core.events import EventBus
from src.core.secrets import SecretDetector
from src.storage.db import Database
from src.storage.memory import MemoryStore
from src.storage.profiles import ProfileManager
from src.storage.project import ProjectStore
from src.core.log import get_logger
from src.storage.usage import UsageStore

logger = get_logger("web.deps")

MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

API_KEY = os.environ.get("CONTEXTPILOT_API_KEY")

WEB_DIR = Path(__file__).parent

_db_path: Optional[Path] = None
_db: Optional[Database] = None
_project_store: Optional[ProjectStore] = None
_memory_store: Optional[MemoryStore] = None
_usage_store: Optional[UsageStore] = None
_db_lock = threading.Lock()
_db_explicit_path: bool = False  # True after _init_db with explicit path; suppresses ProfileManager check


def _get_db() -> Database:
    """Return the active-profile DB. Reconnects on profile switch.

    SQLite WAL mode automatically gives each new read a fresh snapshot
    of the latest committed state — no manual snapshot refresh needed
    when the Python sqlite3 module is in default autocommit mode (which
    Database() uses).

    If `_init_db` was called with an explicit path (e.g. tests passing
    None for in-memory), we never auto-switch to ProfileManager.
    """
    global _db, _db_path, _project_store, _memory_store, _usage_store
    with _db_lock:
        if _db is None:
            target = ProfileManager().active_db_path
            _db_path = target
            _db = Database(_db_path, check_same_thread=False)
            _project_store = None
            _memory_store = None
            _usage_store = None
            logger.info("Web DB connected to %s", _db_path)
            return _db
        if _db_explicit_path:
            return _db
        current_path = ProfileManager().active_db_path
        if _db_path != current_path:
            try:
                _db.close()
            except Exception as e:
                logger.warning("Failed to close previous DB: %s", e)
            _db_path = current_path
            _db = Database(_db_path, check_same_thread=False)
            _project_store = None
            _memory_store = None
            _usage_store = None
            logger.info("Web DB switched to %s", _db_path)
        return _db


def _get_project_store() -> ProjectStore:
    global _project_store
    db = _get_db()
    with _db_lock:
        if _project_store is None:
            _project_store = ProjectStore(db)
        return _project_store


def _get_memory_store() -> MemoryStore:
    global _memory_store
    db = _get_db()
    with _db_lock:
        if _memory_store is None:
            _memory_store = MemoryStore(db)
        return _memory_store


def _get_usage_store() -> UsageStore:
    global _usage_store
    db = _get_db()
    with _db_lock:
        if _usage_store is None:
            _usage_store = UsageStore(db)
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
    """Force re-init the DB connection.

    - When called with an explicit path (incl. None for tests/in-memory),
      pins to that path; ProfileManager auto-switching is disabled.
    - When called with `db_path` omitted, leaves _db unset so the next
      `_get_db()` consults ProfileManager.

    Waits for any in-flight background indexing to finish so we don't close
    the SQLite connection out from under the indexer thread (segfault risk).
    """
    global _db, _db_path, _project_store, _memory_store, _usage_store, _db_explicit_path
    if not _index_lock.acquire(timeout=10.0):
        logger.warning("Index lock not released within 10s — proceeding with DB re-init")
    try:
        with _db_lock:
            if _db is not None:
                try:
                    _db.close()
                except Exception as e:
                    logger.warning("Failed to close DB during re-init: %s", e)
            logger.info("Initializing database at %s", db_path)
            _db = Database(db_path, check_same_thread=False)
            _db_path = db_path
            _db_explicit_path = True
            _project_store = None
            _memory_store = None
            _usage_store = None
    finally:
        try:
            _index_lock.release()
        except RuntimeError:
            pass


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
