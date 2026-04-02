"""Tests for the Notion connector — API mocking, markdown conversion, property formatting."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.connectors.notion import (
    NotionConnector,
    _NotionAPI,
    _rich_text_to_str,
    _blocks_to_markdown,
    _get_page_title,
    _get_database_title,
    _format_property_value,
)
from src.storage.db import Database
from src.storage.memory import MemoryStore


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


@pytest.fixture
def connector(tmp_path):
    c = NotionConnector(data_dir=tmp_path)
    c.configure({"token": "secret_test"})
    return c


class TestRichTextToStr:
    def test_empty(self):
        assert _rich_text_to_str([]) == ""

    def test_single(self):
        assert _rich_text_to_str([{"plain_text": "hello"}]) == "hello"

    def test_multiple(self):
        parts = [{"plain_text": "hello "}, {"plain_text": "world"}]
        assert _rich_text_to_str(parts) == "hello world"


class TestBlocksToMarkdown:
    def test_paragraph(self):
        blocks = [{"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Hello"}]}}]
        assert "Hello" in _blocks_to_markdown(blocks)

    def test_heading1(self):
        blocks = [{"type": "heading_1", "heading_1": {"rich_text": [{"plain_text": "Title"}]}}]
        assert "# Title" in _blocks_to_markdown(blocks)

    def test_heading2(self):
        blocks = [{"type": "heading_2", "heading_2": {"rich_text": [{"plain_text": "Sub"}]}}]
        assert "## Sub" in _blocks_to_markdown(blocks)

    def test_heading3(self):
        blocks = [{"type": "heading_3", "heading_3": {"rich_text": [{"plain_text": "H3"}]}}]
        assert "### H3" in _blocks_to_markdown(blocks)

    def test_bulleted_list(self):
        blocks = [{"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": [{"plain_text": "item"}]}}]
        assert "- item" in _blocks_to_markdown(blocks)

    def test_numbered_list(self):
        blocks = [
            {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "first"}]}},
            {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "second"}]}},
        ]
        md = _blocks_to_markdown(blocks)
        assert "1. first" in md
        assert "2. second" in md

    def test_code_block(self):
        blocks = [{"type": "code", "code": {"rich_text": [{"plain_text": "print('hi')"}], "language": "python"}}]
        md = _blocks_to_markdown(blocks)
        assert "```python" in md
        assert "print('hi')" in md

    def test_quote(self):
        blocks = [{"type": "quote", "quote": {"rich_text": [{"plain_text": "wise words"}]}}]
        assert "> wise words" in _blocks_to_markdown(blocks)

    def test_todo(self):
        blocks = [
            {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "done"}], "checked": True}},
            {"type": "to_do", "to_do": {"rich_text": [{"plain_text": "todo"}], "checked": False}},
        ]
        md = _blocks_to_markdown(blocks)
        assert "[x] done" in md
        assert "[ ] todo" in md

    def test_toggle(self):
        blocks = [{"type": "toggle", "toggle": {"rich_text": [{"plain_text": "toggle"}]}}]
        assert "<details>" in _blocks_to_markdown(blocks)

    def test_callout(self):
        blocks = [{"type": "callout", "callout": {
            "rich_text": [{"plain_text": "note"}],
            "icon": {"emoji": "💡"},
        }}]
        md = _blocks_to_markdown(blocks)
        assert "note" in md

    def test_divider(self):
        blocks = [{"type": "divider", "divider": {}}]
        assert "---" in _blocks_to_markdown(blocks)

    def test_unknown_type(self):
        blocks = [{"type": "unknown_block", "unknown_block": {}}]
        result = _blocks_to_markdown(blocks)
        assert result == ""

    def test_numbered_reset_after_paragraph(self):
        blocks = [
            {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "one"}]}},
            {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "break"}]}},
            {"type": "numbered_list_item", "numbered_list_item": {"rich_text": [{"plain_text": "new one"}]}},
        ]
        md = _blocks_to_markdown(blocks)
        assert md.count("1.") == 2


class TestGetPageTitle:
    def test_with_title(self):
        page = {"properties": {"Name": {"type": "title", "title": [{"plain_text": "My Page"}]}}}
        assert _get_page_title(page) == "My Page"

    def test_no_title(self):
        page = {"id": "abc12345", "properties": {}}
        assert _get_page_title(page) == "abc12345"


class TestGetDatabaseTitle:
    def test_with_title(self):
        db = {"title": [{"plain_text": "My DB"}]}
        assert _get_database_title(db) == "My DB"

    def test_no_title(self):
        db = {"id": "xyz98765", "title": []}
        assert _get_database_title(db) == "xyz98765"


class TestFormatPropertyValue:
    def test_title(self):
        assert _format_property_value({"type": "title", "title": [{"plain_text": "T"}]}) == "T"

    def test_rich_text(self):
        assert _format_property_value({"type": "rich_text", "rich_text": [{"plain_text": "text"}]}) == "text"

    def test_number(self):
        assert _format_property_value({"type": "number", "number": 42}) == "42"
        assert _format_property_value({"type": "number", "number": None}) == ""

    def test_select(self):
        assert _format_property_value({"type": "select", "select": {"name": "Option A"}}) == "Option A"
        assert _format_property_value({"type": "select", "select": None}) == ""

    def test_multi_select(self):
        val = _format_property_value({"type": "multi_select", "multi_select": [
            {"name": "A"}, {"name": "B"},
        ]})
        assert val == "A, B"

    def test_date(self):
        assert _format_property_value({"type": "date", "date": {"start": "2025-01-01", "end": "2025-01-31"}}) == "2025-01-01 - 2025-01-31"
        assert _format_property_value({"type": "date", "date": {"start": "2025-01-01"}}) == "2025-01-01"
        assert _format_property_value({"type": "date", "date": None}) == ""

    def test_checkbox(self):
        assert _format_property_value({"type": "checkbox", "checkbox": True}) == "Yes"
        assert _format_property_value({"type": "checkbox", "checkbox": False}) == "No"

    def test_url(self):
        assert _format_property_value({"type": "url", "url": "http://x.com"}) == "http://x.com"

    def test_email(self):
        assert _format_property_value({"type": "email", "email": "a@b.com"}) == "a@b.com"

    def test_phone(self):
        assert _format_property_value({"type": "phone_number", "phone_number": "123"}) == "123"

    def test_status(self):
        assert _format_property_value({"type": "status", "status": {"name": "Done"}}) == "Done"
        assert _format_property_value({"type": "status", "status": None}) == ""

    def test_people(self):
        val = _format_property_value({"type": "people", "people": [{"name": "Alice"}, {"name": "Bob"}]})
        assert val == "Alice, Bob"

    def test_relation(self):
        val = _format_property_value({"type": "relation", "relation": [{"id": "a"}, {"id": "b"}]})
        assert "2 relations" in val

    def test_formula(self):
        val = _format_property_value({"type": "formula", "formula": {"type": "string", "string": "result"}})
        assert val == "result"

    def test_rollup(self):
        val = _format_property_value({"type": "rollup", "rollup": {"type": "number", "number": 99}})
        assert val == "99"

    def test_unknown(self):
        assert _format_property_value({"type": "unknown"}) == ""


MOCK_SEARCH = {
    "results": [
        {
            "object": "page",
            "id": "page-id-1",
            "last_edited_time": "2025-01-01T00:00:00.000Z",
            "url": "https://notion.so/page-id-1",
            "properties": {"Name": {"type": "title", "title": [{"plain_text": "Test Page"}]}},
        },
        {
            "object": "database",
            "id": "db-id-1",
            "title": [{"plain_text": "Tasks DB"}],
        },
    ],
    "has_more": False,
}

MOCK_BLOCKS = {
    "results": [
        {"type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "Page content here"}]}},
    ],
    "has_more": False,
}

MOCK_DB_QUERY = {
    "results": [
        {
            "properties": {
                "Name": {"type": "title", "title": [{"plain_text": "Task 1"}]},
                "Status": {"type": "status", "status": {"name": "In Progress"}},
            },
        },
    ],
    "has_more": False,
}


class TestNotionConnector:
    def test_not_configured(self, tmp_path):
        c = NotionConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured(self, connector):
        assert connector.configured

    @patch("src.connectors.notion.requests.get")
    def test_test_connection_ok(self, mock_get, connector):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"name": "Bot", "type": "bot"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        result = connector.test_connection()
        assert result["ok"] is True

    def test_test_connection_no_token(self, tmp_path):
        c = NotionConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    @patch("src.connectors.notion.requests.get")
    def test_test_connection_error(self, mock_get, connector):
        mock_get.side_effect = ConnectionError("fail")
        result = connector.test_connection()
        assert result["ok"] is False

    @patch("src.connectors.notion.requests.post")
    @patch("src.connectors.notion.requests.get")
    def test_sync(self, mock_get, mock_post, connector, store):
        def get_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json.return_value = MOCK_BLOCKS
            return resp
        mock_get.side_effect = get_side_effect

        def post_side_effect(url, **kwargs):
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            if "search" in url:
                resp.json.return_value = MOCK_SEARCH
            elif "query" in url:
                resp.json.return_value = MOCK_DB_QUERY
            else:
                resp.json.return_value = {"results": []}
            return resp
        mock_post.side_effect = post_side_effect

        result = connector.sync(store)
        assert result.added >= 2  # 1 page + 1 database
        assert result.errors == []

    def test_sync_no_token(self, tmp_path, store):
        c = NotionConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["No integration token configured"]

    def test_parse_database_ids(self, connector):
        assert connector._parse_database_ids() == []
        connector._config["database_ids"] = "db1, db2"
        assert connector._parse_database_ids() == ["db1", "db2"]
