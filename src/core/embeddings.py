"""Semantic search engine — embedding-based similarity search for memories.

Uses sentence-transformers if available (best quality), falls back to
TF-IDF (pure Python, no dependencies) for lightweight deployments.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))

# Try to import sentence-transformers
_model = None
_backend = "tfidf"

try:
    from sentence_transformers import SentenceTransformer
    _backend = "transformer"
except ImportError:
    pass


def get_backend() -> str:
    return _backend


def _get_model():
    global _model
    if _model is None and _backend == "transformer":
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


# ═══════════════════════════════════════════════════════════════
# Vector storage in SQLite
# ═══════════════════════════════════════════════════════════════

def _pack_vector(vec: List[float]) -> bytes:
    return struct.pack(f'{len(vec)}f', *vec)


def _unpack_vector(data: bytes) -> List[float]:
    n = len(data) // 4
    return list(struct.unpack(f'{n}f', data))


def _cosine_sim(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class EmbeddingStore:
    """Stores and queries embeddings in SQLite (thread-safe)."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        path = db_path or (_DATA_DIR / "embeddings.db")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS embeddings (
            key TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            vector BLOB NOT NULL,
            backend TEXT NOT NULL,
            updated_at REAL NOT NULL
        )""")
        self._conn.commit()
        self._db_lock = threading.Lock()

    def close(self) -> None:
        with self._db_lock:
            self._conn.close()

    def has(self, key: str, content_hash: str) -> bool:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT content_hash, backend FROM embeddings WHERE key = ?", (key,)
            ).fetchone()
        return row is not None and row[0] == content_hash and row[1] == _backend

    def store(self, key: str, content_hash: str, vector: List[float]) -> None:
        import time
        with self._db_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO embeddings (key, content_hash, vector, backend, updated_at) VALUES (?, ?, ?, ?, ?)",
                (key, content_hash, _pack_vector(vector), _backend, time.time()),
            )
            self._conn.commit()

    def get(self, key: str) -> Optional[List[float]]:
        with self._db_lock:
            row = self._conn.execute("SELECT vector FROM embeddings WHERE key = ?", (key,)).fetchone()
        return _unpack_vector(row[0]) if row else None

    def all_vectors(self) -> List[Tuple[str, List[float]]]:
        with self._db_lock:
            rows = self._conn.execute("SELECT key, vector FROM embeddings").fetchall()
        return [(r[0], _unpack_vector(r[1])) for r in rows]

    def remove(self, key: str) -> None:
        with self._db_lock:
            self._conn.execute("DELETE FROM embeddings WHERE key = ?", (key,))
            self._conn.commit()

    def count(self) -> int:
        with self._db_lock:
            row = self._conn.execute("SELECT count(*) FROM embeddings").fetchone()
        return row[0] if row else 0

    def stats(self) -> Dict[str, Any]:
        with self._db_lock:
            row = self._conn.execute("SELECT count(*), max(updated_at) FROM embeddings").fetchone()
        return {
            "count": row[0] if row else 0,
            "last_updated": row[1] if row else None,
            "backend": _backend,
        }


# ═══════════════════════════════════════════════════════════════
# TF-IDF Fallback (zero dependencies)
# ═══════════════════════════════════════════════════════════════

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "and", "but", "or", "nor", "not", "so", "yet", "both", "either",
    "neither", "each", "every", "all", "any", "few", "more", "most",
    "other", "some", "such", "no", "only", "own", "same", "than", "too",
    "very", "just", "because", "as", "until", "while", "of", "at", "by",
    "for", "with", "about", "against", "between", "through", "during",
    "before", "after", "above", "below", "to", "from", "up", "down",
    "in", "out", "on", "off", "over", "under", "again", "further",
    "then", "once", "here", "there", "when", "where", "why", "how",
    "this", "that", "these", "those", "i", "me", "my", "myself", "we",
    "our", "ours", "you", "your", "yours", "he", "him", "his", "she",
    "her", "hers", "it", "its", "they", "them", "their", "what", "which",
    "who", "whom", "if", "also", "into", "der", "die", "das", "und",
    "ist", "von", "fuer", "mit", "auf", "den", "ein", "eine", "nicht",
}


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    words = re.findall(r'[a-z0-9äöü]+', text)
    return [w for w in words if w not in _STOP_WORDS and len(w) > 1]


class TFIDFEngine:
    """Lightweight TF-IDF engine for semantic-like search without ML dependencies."""

    def __init__(self) -> None:
        self._idf: Dict[str, float] = {}
        self._doc_count = 0

    def build_idf(self, documents: List[str]) -> None:
        self._doc_count = len(documents)
        df = Counter()
        for doc in documents:
            words = set(_tokenize(doc))
            for w in words:
                df[w] += 1
        self._idf = {w: math.log((self._doc_count + 1) / (count + 1)) + 1 for w, count in df.items()}

    def vectorize(self, text: str) -> List[float]:
        words = _tokenize(text)
        if not words:
            return [0.0] * max(len(self._idf), 1)

        tf = Counter(words)
        vocab = sorted(self._idf.keys())
        vec = []
        for w in vocab:
            tfidf = (tf.get(w, 0) / len(words)) * self._idf.get(w, 0)
            vec.append(tfidf)

        # Normalize
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec


# ═══════════════════════════════════════════════════════════════
# Per-profile caching & thread safety
# ═══════════════════════════════════════════════════════════════

_lock = threading.Lock()
_tfidf_cache: Dict[str, TFIDFEngine] = {}
_embedding_stores: Dict[str, EmbeddingStore] = {}
_embedding_data_dir: Optional[Path] = None


def _dir_key(data_dir: Optional[Path] = None) -> str:
    return str(data_dir or _embedding_data_dir or _DATA_DIR)


def _get_tfidf() -> TFIDFEngine:
    key = _dir_key()
    with _lock:
        if key not in _tfidf_cache:
            _tfidf_cache[key] = TFIDFEngine()
        return _tfidf_cache[key]


def set_data_dir(data_dir: Path) -> None:
    """Switch to a different profile's data directory.

    The old store stays in the cache so switching back is instant.
    """
    global _embedding_data_dir
    with _lock:
        _embedding_data_dir = data_dir
        # Pre-warm: ensure store exists in cache (lazy-opened on next access)


def get_active_dir() -> Path:
    return _embedding_data_dir or _DATA_DIR


def _get_store() -> EmbeddingStore:
    key = _dir_key()
    with _lock:
        if key not in _embedding_stores:
            path = Path(key) / "embeddings.db"
            _embedding_stores[key] = EmbeddingStore(path)
        return _embedding_stores[key]


def close_all_stores() -> None:
    """Close all cached stores (for cleanup in tests)."""
    with _lock:
        for store in _embedding_stores.values():
            try:
                store.close()
            except Exception:
                pass
        _embedding_stores.clear()
        _tfidf_cache.clear()


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def embed_text(text: str) -> List[float]:
    """Compute embedding for a text string."""
    if _backend == "transformer":
        model = _get_model()
        return model.encode(text).tolist()
    else:
        return _get_tfidf().vectorize(text)


def index_memories(memories: list, profile_dir: Optional[Path] = None) -> Dict[str, int]:
    """Index all memories for the current (or given) profile. Returns stats.

    If profile_dir is provided, it's compared to the active dir —
    if they differ the call is a no-op (profile switched mid-index).
    """
    with _lock:
        active = get_active_dir()
    if profile_dir is not None and str(profile_dir) != str(active):
        return {"indexed": 0, "skipped": 0, "total": 0, "backend": _backend, "aborted": True}

    store = _get_store()
    indexed = 0
    skipped = 0

    if _backend == "tfidf":
        _get_tfidf().build_idf([f"{m.key} {m.value}" for m in memories])

    for m in memories:
        # Check for profile switch mid-loop
        with _lock:
            if profile_dir is not None and str(profile_dir) != str(get_active_dir()):
                return {"indexed": indexed, "skipped": skipped, "total": len(memories),
                        "backend": _backend, "aborted": True}

        text = f"{m.key} {' '.join(m.tags)} {m.value}"
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

        if store.has(m.key, content_hash):
            skipped += 1
            continue

        vec = embed_text(text)
        store.store(m.key, content_hash, vec)
        indexed += 1

    return {"indexed": indexed, "skipped": skipped, "total": len(memories), "backend": _backend}


def index_single_memory(memory) -> None:
    """Index or re-index a single memory (after create/update)."""
    store = _get_store()
    text = f"{memory.key} {' '.join(memory.tags)} {memory.value}"
    content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
    if store.has(memory.key, content_hash):
        return
    vec = embed_text(text)
    store.store(memory.key, content_hash, vec)


def remove_from_index(key: str) -> None:
    """Remove a memory from the embedding index."""
    _get_store().remove(key)


def semantic_search(query: str, limit: int = 10) -> List[Tuple[str, float]]:
    """Search memories by semantic similarity. Returns [(key, score), ...]."""
    store = _get_store()

    if _backend == "tfidf" and _get_tfidf()._doc_count == 0:
        return []

    query_vec = embed_text(query)
    all_vecs = store.all_vectors()

    results = []
    for key, vec in all_vecs:
        sim = _cosine_sim(query_vec, vec)
        if sim > 0.05:
            results.append((key, round(sim, 4)))

    results.sort(key=lambda x: -x[1])
    return results[:limit]


def hybrid_search(
    query: str,
    store,
    top_k: int = 20,
    fts_weight: float = 0.4,
    semantic_weight: float = 0.6,
) -> List[Dict[str, Any]]:
    """Fuse FTS and semantic search results into a single ranked list.

    Args:
        query: Search text.
        store: A MemoryStore instance (used for FTS via store.search()).
        top_k: Number of results to return.
        fts_weight: Weight for FTS scores (0-1).
        semantic_weight: Weight for semantic scores (0-1).

    Returns:
        List of dicts with keys: key, value, score, tags, method.
    """
    if not query or not query.strip():
        return []

    # Step 1: FTS results
    fts_memories = store.search(query, limit=top_k * 2)
    fts_scores: Dict[str, float] = {}
    memory_data: Dict[str, Any] = {}
    for i, m in enumerate(fts_memories):
        # FTS rank: first result gets highest score, linearly decreasing
        fts_scores[m.key] = max(0.0, 1.0 - i / max(len(fts_memories), 1))
        memory_data[m.key] = {"value": m.value, "tags": m.tags}

    # Step 2: Semantic results
    sem_results = semantic_search(query, limit=top_k * 2)
    sem_scores: Dict[str, float] = {}
    for key, score in sem_results:
        sem_scores[key] = score

    # If semantic search returned nothing, fall back to FTS-only
    if not sem_scores:
        results = []
        for key, fts_s in sorted(fts_scores.items(), key=lambda x: -x[1]):
            data = memory_data.get(key, {})
            results.append({
                "key": key,
                "value": data.get("value", ""),
                "score": round(fts_s, 4),
                "tags": data.get("tags", []),
                "method": "fts",
            })
        return results[:top_k]

    # Step 3: Normalize both score sets to 0-1 range
    def _normalize(scores: Dict[str, float]) -> Dict[str, float]:
        if not scores:
            return {}
        min_s = min(scores.values())
        max_s = max(scores.values())
        rng = max_s - min_s
        if rng == 0:
            return {k: 1.0 for k in scores}
        return {k: (v - min_s) / rng for k, v in scores.items()}

    norm_fts = _normalize(fts_scores)
    norm_sem = _normalize(sem_scores)

    # Step 4: Fuse scores
    all_keys = set(norm_fts.keys()) | set(norm_sem.keys())
    fused: Dict[str, float] = {}
    for key in all_keys:
        f = norm_fts.get(key, 0.0)
        s = norm_sem.get(key, 0.0)
        fused[key] = fts_weight * f + semantic_weight * s

    # Step 5: Sort and build output
    # Load memory data for keys found only via semantic search
    for key in all_keys:
        if key not in memory_data:
            try:
                m = store.get(key)
                memory_data[key] = {"value": m.value, "tags": m.tags}
            except (KeyError, Exception):
                memory_data[key] = {"value": "", "tags": []}

    sorted_keys = sorted(fused.keys(), key=lambda k: -fused[k])
    results = []
    for key in sorted_keys[:top_k]:
        data = memory_data.get(key, {})
        in_fts = key in norm_fts
        in_sem = key in norm_sem
        if in_fts and in_sem:
            method = "hybrid"
        elif in_fts:
            method = "fts"
        else:
            method = "semantic"
        results.append({
            "key": key,
            "value": data.get("value", ""),
            "score": round(fused[key], 4),
            "tags": data.get("tags", []),
            "method": method,
        })

    return results
