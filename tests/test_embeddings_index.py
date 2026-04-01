"""Tests for embeddings index_memories — profile switch race guard."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import pytest

import src.core.embeddings as emb


@dataclass
class FakeMemory:
    key: str
    value: str
    tags: List[str] = field(default_factory=list)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(emb, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(emb, "_embedding_data_dir", tmp_path)
    emb.close_all_stores()
    yield
    emb.close_all_stores()


def test_index_memories_basic(tmp_path):
    memories = [FakeMemory(key=f"m/{i}", value=f"value {i}") for i in range(5)]
    result = emb.index_memories(memories, profile_dir=tmp_path)
    assert result["indexed"] == 5
    assert result["skipped"] == 0


def test_index_memories_skips_existing(tmp_path):
    memories = [FakeMemory(key="m/1", value="value 1")]
    emb.index_memories(memories, profile_dir=tmp_path)
    result = emb.index_memories(memories, profile_dir=tmp_path)
    assert result["skipped"] == 1
    assert result["indexed"] == 0


def test_index_memories_no_crash_empty():
    result = emb.index_memories([])
    assert result["total"] == 0
