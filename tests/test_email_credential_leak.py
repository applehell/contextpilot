"""Tests for M14: email IMAP does not leak credentials in error messages."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from src.connectors.email_imap import EmailConnector
from src.storage.db import Database
from src.storage.memory import MemoryStore


def test_connection_error_hides_credentials(tmp_path: Path) -> None:
    conn = EmailConnector(data_dir=tmp_path)
    password = "SuperSecretPassword123!"
    conn._config = {
        "_configured": True,
        "_enabled": True,
        "accounts": [
            {
                "name": "test",
                "host": "mail.example.com",
                "port": 993,
                "user": "user@example.com",
                "password": password,
                "ssl": True,
                "folders": ["INBOX"],
            }
        ],
        "max_emails": 10,
        "since_days": 7,
        "max_body_length": 500,
    }

    db_path = tmp_path / "test.db"
    db = Database(db_path)
    store = MemoryStore(db)

    with patch("src.connectors.email_imap._connect", side_effect=Exception(f"LOGIN failed for user@example.com with password {password}")):
        result = conn.sync(store)

    assert len(result.errors) == 1
    assert password not in result.errors[0]
    assert "connection failed" in result.errors[0]
    assert "test" in result.errors[0]

    db.close()
