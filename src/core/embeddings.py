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
    """Stores and queries embeddings in SQLite."""

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

    def close(self) -> None:
        self._conn.close()

    def has(self, key: str, content_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT content_hash, backend FROM embeddings WHERE key = ?", (key,)
        ).fetchone()
        return row is not None and row[0] == content_hash and row[1] == _backend

    def store(self, key: str, content_hash: str, vector: List[float]) -> None:
        import time
        self._conn.execute(
            "INSERT OR REPLACE INTO embeddings (key, content_hash, vector, backend, updated_at) VALUES (?, ?, ?, ?, ?)",
            (key, content_hash, _pack_vector(vector), _backend, time.time()),
        )
        self._conn.commit()

    def get(self, key: str) -> Optional[List[float]]:
        row = self._conn.execute("SELECT vector FROM embeddings WHERE key = ?", (key,)).fetchone()
        return _unpack_vector(row[0]) if row else None

    def all_vectors(self) -> List[Tuple[str, List[float]]]:
        rows = self._conn.execute("SELECT key, vector FROM embeddings").fetchall()
        return [(r[0], _unpack_vector(r[1])) for r in rows]

    def remove(self, key: str) -> None:
        self._conn.execute("DELETE FROM embeddings WHERE key = ?", (key,))
        self._conn.commit()

    def count(self) -> int:
        row = self._conn.execute("SELECT count(*) FROM embeddings").fetchone()
        return row[0] if row else 0

    def stats(self) -> Dict[str, Any]:
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
# Public API
# ═══════════════════════════════════════════════════════════════

_tfidf_engine = TFIDFEngine()
_embedding_store: Optional[EmbeddingStore] = None
_embedding_data_dir: Optional[Path] = None


def set_data_dir(data_dir: Path) -> None:
    """Set the data directory and reset the store."""
    global _embedding_store, _embedding_data_dir
    _embedding_data_dir = data_dir
    if _embedding_store is not None:
        _embedding_store.close()
    _embedding_store = None


def _get_store() -> EmbeddingStore:
    global _embedding_store
    if _embedding_store is None:
        path = (_embedding_data_dir or _DATA_DIR) / "embeddings.db"
        _embedding_store = EmbeddingStore(path)
    return _embedding_store


def embed_text(text: str) -> List[float]:
    """Compute embedding for a text string."""
    if _backend == "transformer":
        model = _get_model()
        return model.encode(text).tolist()
    else:
        return _tfidf_engine.vectorize(text)


def index_memories(memories: list) -> Dict[str, int]:
    """Index all memories. Returns stats."""
    store = _get_store()
    indexed = 0
    skipped = 0

    if _backend == "tfidf":
        _tfidf_engine.build_idf([f"{m.key} {m.value}" for m in memories])

    for m in memories:
        text = f"{m.key} {' '.join(m.tags)} {m.value}"
        content_hash = hashlib.sha256(text.encode()).hexdigest()[:16]

        if store.has(m.key, content_hash):
            skipped += 1
            continue

        vec = embed_text(text)
        store.store(m.key, content_hash, vec)
        indexed += 1

    return {"indexed": indexed, "skipped": skipped, "total": len(memories), "backend": _backend}


def semantic_search(query: str, limit: int = 10) -> List[Tuple[str, float]]:
    """Search memories by semantic similarity. Returns [(key, score), ...]."""
    store = _get_store()

    if _backend == "tfidf" and _tfidf_engine._doc_count == 0:
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
