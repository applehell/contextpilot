"""Tests for the Paperless-ngx connector."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.connectors.paperless import PaperlessConnector, PaperlessClient, PAPERLESS_CONFIG
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def pc(tmp_path, monkeypatch):
    config = tmp_path / "paperless.json"
    monkeypatch.setattr("src.connectors.paperless.PAPERLESS_CONFIG", config)
    monkeypatch.setattr("src.connectors.paperless._DATA_DIR", tmp_path)
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
        pc.configure("http://localhost:8000", "mytoken")
        assert pc.configured is True
        cfg = pc.get_config()
        assert cfg.url == "http://localhost:8000"
        assert cfg.token == "mytoken"

    def test_configure_with_tags(self, pc):
        pc.configure("http://localhost:8000", "mytoken", sync_tags=["finance"])
        cfg = pc.get_config()
        assert cfg.sync_tags == ["finance"]

    def test_configure_strips_trailing_slash(self, pc):
        pc.configure("http://localhost:8000/", "token")
        assert pc.get_config().url == "http://localhost:8000"

    def test_update(self, pc):
        pc.configure("http://localhost:8000", "token")
        pc.update(sync_tags=["new-tag"])
        assert pc.get_config().sync_tags == ["new-tag"]

    def test_remove(self, pc):
        pc.configure("http://localhost:8000", "token")
        pc.remove()
        assert pc.configured is False


class TestTest:
    def test_not_configured(self, pc):
        result = pc.test()
        assert result["ok"] is False
        assert "Not configured" in result["error"]


class TestSync:
    def _mock_client(self, pc):
        pc.configure("http://fake:8000", "faketoken")
        mock = MagicMock(spec=PaperlessClient)
        mock.list_tags.return_value = MOCK_TAGS
        mock.list_correspondents.return_value = MOCK_CORRESPONDENTS
        mock.list_document_types.return_value = MOCK_TYPES
        mock.list_documents.return_value = MOCK_DOCUMENTS
        return mock

    def test_sync_not_configured(self, pc, store):
        result = pc.sync(store)
        assert result.errors[0] == "Not configured"

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_adds_documents(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        result = pc.sync(store)
        assert result.added == 2  # 2 with content, 1 empty skipped
        assert result.skipped == 1
        assert result.total_remote == 3

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_creates_correct_keys(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)
        keys = [m.key for m in store.list()]
        assert "paperless/1" in keys
        assert "paperless/2" in keys

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_content_includes_header(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)
        m = store.get("paperless/1")
        assert "# Invoice 2025" in m.value
        assert "Correspondent: Stadtwerke" in m.value
        assert "Type: Invoice" in m.value
        assert "Total: 150.00 EUR" in m.value

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_tags(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)
        m = store.get("paperless/1")
        assert "paperless" in m.tags
        assert "finance" in m.tags
        assert "important" in m.tags
        assert "stadtwerke" in m.tags
        assert "invoice" in m.tags

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_metadata(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)
        m = store.get("paperless/1")
        assert m.metadata["source"] == "paperless"
        assert m.metadata["paperless_id"] == 1
        assert m.metadata["correspondent"] == "Stadtwerke"
        assert "content_hash" in m.metadata

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_idempotent(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)
        result = pc.sync(store)
        assert result.added == 0
        assert result.skipped == 3  # 2 unchanged + 1 empty

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_detects_changes(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)

        # Change doc content
        updated_docs = [d.copy() for d in MOCK_DOCUMENTS]
        updated_docs[0]["content"] = "New total: 200.00 EUR"
        mock.list_documents.return_value = updated_docs

        result = pc.sync(store)
        assert result.updated == 1

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_removes_deleted_docs(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)

        # Remove a document from Paperless
        mock.list_documents.return_value = [MOCK_DOCUMENTS[0]]
        result = pc.sync(store)
        assert result.removed == 1

    @patch("src.connectors.paperless.PaperlessClient")
    def test_sync_updates_config(self, MockClient, pc, store):
        mock = self._mock_client(pc)
        MockClient.return_value = mock

        pc.sync(store)
        cfg = pc.get_config()
        assert cfg.last_sync is not None
        assert cfg.synced_docs == 3  # includes empty doc key


class TestPurge:
    @patch("src.connectors.paperless.PaperlessClient")
    def test_purge(self, MockClient, pc, store):
        mock = MagicMock(spec=PaperlessClient)
        mock.list_tags.return_value = MOCK_TAGS
        mock.list_correspondents.return_value = MOCK_CORRESPONDENTS
        mock.list_document_types.return_value = MOCK_TYPES
        mock.list_documents.return_value = MOCK_DOCUMENTS
        MockClient.return_value = mock

        pc.configure("http://fake:8000", "token")
        pc.sync(store)
        count = pc.purge(store)
        assert count == 2
        assert len(store.list()) == 0
