"""Tests for the Paperless-ngx connector."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.connectors.paperless import PaperlessConnector, _PaperlessAPI
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def pc(tmp_path, monkeypatch):
    monkeypatch.setattr("src.connectors.base._DATA_DIR", tmp_path)
    return PaperlessConnector()


@pytest.fixture
def store(tmp_path):
    db = Database(tmp_path / "test.db")
    return MemoryStore(db)


MOCK_DOCUMENTS = [
    {
        "id": 1,
        "title": "Invoice 2025",
        "content": "Total: 150.00 EUR",
        "tags": [1, 2],
        "correspondent": 1,
        "document_type": 1,
        "created_date": "2025-06-15",
        "original_file_name": "invoice.pdf",
    },
    {
        "id": 2,
        "title": "Contract",
        "content": "This contract is between...",
        "tags": [2],
        "correspondent": 2,
        "document_type": 2,
        "created_date": "2025-07-01",
        "original_file_name": "contract.pdf",
    },
    {
        "id": 3,
        "title": "Empty Doc",
        "content": "",
        "tags": [],
        "correspondent": None,
        "document_type": None,
        "created_date": "2025-08-01",
        "original_file_name": "empty.pdf",
    },
]

MOCK_TAGS = {1: "finance", 2: "important"}
MOCK_CORRESPONDENTS = {1: "Stadtwerke", 2: "Landlord"}
MOCK_TYPES = {1: "Invoice", 2: "Contract"}


class TestConfigure:
    def test_not_configured_initially(self, pc):
        assert pc.configured is False

    def test_configure(self, pc):
        pc.configure({"url": "http://localhost:8000", "token": "mytoken"})
        assert pc.configured is True
        assert pc._config["url"] == "http://localhost:8000"
        assert pc._config["token"] == "mytoken"

    def test_configure_with_tags(self, pc):
        pc.configure({"url": "http://localhost:8000", "token": "mytoken", "sync_tags": "finance"})
        assert pc._config.get("sync_tags") == "finance"

    def test_configure_stores_url(self, pc):
        pc.configure({"url": "http://localhost:8000", "token": "token"})
        assert pc._config["url"] == "http://localhost:8000"

    def test_update(self, pc):
        pc.configure({"url": "http://localhost:8000", "token": "token"})
        pc.update({"sync_tags": "new-tag"})
        assert pc._config["sync_tags"] == "new-tag"

    def test_remove(self, pc):
        pc.configure({"url": "http://localhost:8000", "token": "token"})
        pc.remove()
        assert pc.configured is False


class TestTest:
    def test_not_configured(self, pc):
        result = pc.test_connection()
        assert result["ok"] is False
        assert "Not configured" in result["error"]


class TestSync:
    def _setup_pc(self, pc):
        pc.configure({"url": "http://fake:8000", "token": "faketoken"})
        mock = MagicMock(spec=_PaperlessAPI)
        mock.tags.return_value = MOCK_TAGS
        mock.correspondents.return_value = MOCK_CORRESPONDENTS
        mock.document_types.return_value = MOCK_TYPES
        mock.documents.return_value = MOCK_DOCUMENTS
        pc._api = lambda: mock
        return mock

    def test_sync_not_configured(self, pc, store):
        result = pc.sync(store)
        assert result.errors[0] == "Not configured"

    def test_sync_adds_documents(self, pc, store):
        self._setup_pc(pc)
        result = pc.sync(store)
        assert result.added == 2
        assert result.skipped == 1
        assert result.total_remote == 3

    def test_sync_creates_correct_keys(self, pc, store):
        self._setup_pc(pc)
        pc.sync(store)
        keys = [m.key for m in store.list()]
        assert "paperless/1" in keys
        assert "paperless/2" in keys

    def test_sync_content_includes_header(self, pc, store):
        self._setup_pc(pc)
        pc.sync(store)
        m = store.get("paperless/1")
        assert "# Invoice 2025" in m.value
        assert "Correspondent: Stadtwerke" in m.value
        assert "Type: Invoice" in m.value
        assert "Total: 150.00 EUR" in m.value

    def test_sync_tags(self, pc, store):
        self._setup_pc(pc)
        pc.sync(store)
        m = store.get("paperless/1")
        assert "paperless" in m.tags
        assert "finance" in m.tags
        assert "important" in m.tags
        assert "stadtwerke" in m.tags
        assert "invoice" in m.tags

    def test_sync_metadata(self, pc, store):
        self._setup_pc(pc)
        pc.sync(store)
        m = store.get("paperless/1")
        assert m.metadata["source"] == "paperless"
        assert m.metadata["paperless_id"] == 1
        assert m.metadata["correspondent"] == "Stadtwerke"
        assert "content_hash" in m.metadata

    def test_sync_idempotent(self, pc, store):
        self._setup_pc(pc)
        pc.sync(store)
        result = pc.sync(store)
        assert result.added == 0
        assert result.skipped == 3

    def test_sync_detects_changes(self, pc, store):
        mock = self._setup_pc(pc)
        pc.sync(store)
        updated_docs = [d.copy() for d in MOCK_DOCUMENTS]
        updated_docs[0]["content"] = "New total: 200.00 EUR"
        mock.documents.return_value = updated_docs
        result = pc.sync(store)
        assert result.updated == 1

    def test_sync_removes_deleted_docs(self, pc, store):
        mock = self._setup_pc(pc)
        pc.sync(store)
        mock.documents.return_value = [MOCK_DOCUMENTS[0]]
        result = pc.sync(store)
        assert result.removed == 1

    def test_sync_updates_stats(self, pc, store):
        self._setup_pc(pc)
        pc.sync(store)
        status = pc.get_status()
        assert status["last_sync"] is not None
        assert status["synced_count"] == 3


class TestPurge:
    def test_purge(self, pc, store):
        mock = MagicMock(spec=_PaperlessAPI)
        mock.tags.return_value = MOCK_TAGS
        mock.correspondents.return_value = MOCK_CORRESPONDENTS
        mock.document_types.return_value = MOCK_TYPES
        mock.documents.return_value = MOCK_DOCUMENTS

        pc.configure({"url": "http://fake:8000", "token": "token"})
        pc._api = lambda: mock
        pc.sync(store)
        count = pc.purge(store)
        assert count == 2
        assert len(store.list()) == 0
