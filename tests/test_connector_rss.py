"""Tests for the RSS/Atom feed connector — parsing and configuration."""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from src.connectors.rss import (
    RSSConnector,
    _strip_html,
    _el_text,
    _parse_rss_items,
    _parse_atom_entries,
    _parse_feed,
    _strip_ns,
)
from src.storage.db import Database
from src.storage.memory import MemoryStore
import xml.etree.ElementTree as ET


@pytest.fixture
def store():
    db = Database(None)
    return MemoryStore(db)


RSS_XML = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Test Blog</title>
    <item>
      <title>First Post</title>
      <link>http://example.com/1</link>
      <pubDate>Mon, 01 Jan 2025 12:00:00 GMT</pubDate>
      <guid>http://example.com/1</guid>
      <description>First post content &amp; details</description>
    </item>
    <item>
      <title>Second Post</title>
      <link>http://example.com/2</link>
      <description>&lt;p&gt;HTML content&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""

ATOM_XML = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom Blog</title>
  <entry>
    <title>Entry One</title>
    <link rel="alternate" href="http://example.com/a" />
    <id>tag:example.com,2025:1</id>
    <published>2025-01-01T12:00:00Z</published>
    <summary>Summary of entry one</summary>
    <content type="html">Full content of entry one</content>
  </entry>
  <entry>
    <title>Entry Two</title>
    <link href="http://example.com/b" />
    <id>tag:example.com,2025:2</id>
    <updated>2025-01-02T12:00:00Z</updated>
    <summary>Summary only</summary>
  </entry>
</feed>
"""


class TestStripHtml:
    def test_basic(self):
        assert _strip_html("<p>Hello</p>") == "Hello"

    def test_br(self):
        assert "Line1\nLine2" == _strip_html("Line1<br/>Line2")

    def test_entities(self):
        assert "&" in _strip_html("&amp;")
        assert "<" in _strip_html("&lt;")
        assert ">" in _strip_html("&gt;")
        assert '"' in _strip_html("&quot;")

    def test_empty(self):
        assert _strip_html("") == ""

    def test_nested(self):
        result = _strip_html("<div><p>text</p></div>")
        assert "text" in result


class TestElText:
    def test_none(self):
        assert _el_text(None) == ""

    def test_empty(self):
        el = ET.Element("x")
        assert _el_text(el) == ""

    def test_with_text(self):
        el = ET.Element("x")
        el.text = " hello "
        assert _el_text(el) == "hello"


class TestStripNs:
    def test_with_ns(self):
        assert _strip_ns("{http://example.com}title") == "title"

    def test_without_ns(self):
        assert _strip_ns("title") == "title"


class TestParseRssItems:
    def test_parse(self):
        root = ET.fromstring(RSS_XML)
        title, items = _parse_rss_items(root, 10, True)
        assert title == "Test Blog"
        assert len(items) == 2
        assert items[0]["title"] == "First Post"
        assert items[0]["link"] == "http://example.com/1"

    def test_max_items(self):
        root = ET.fromstring(RSS_XML)
        _, items = _parse_rss_items(root, 1, True)
        assert len(items) == 1

    def test_no_channel(self):
        root = ET.fromstring("<rss></rss>")
        title, items = _parse_rss_items(root, 10, True)
        assert title == ""
        assert items == []


class TestParseAtomEntries:
    def test_parse(self):
        root = ET.fromstring(ATOM_XML)
        title, entries = _parse_atom_entries(root, 10, True)
        assert title == "Atom Blog"
        assert len(entries) == 2
        assert entries[0]["title"] == "Entry One"
        assert "example.com/a" in entries[0]["link"]

    def test_content_included(self):
        root = ET.fromstring(ATOM_XML)
        _, entries = _parse_atom_entries(root, 10, True)
        assert entries[0]["description"] == "Full content of entry one"

    def test_content_not_included(self):
        root = ET.fromstring(ATOM_XML)
        _, entries = _parse_atom_entries(root, 10, False)
        assert entries[0]["description"] == "Summary of entry one"

    def test_updated_fallback(self):
        root = ET.fromstring(ATOM_XML)
        _, entries = _parse_atom_entries(root, 10, True)
        assert entries[1]["pub_date"] == "2025-01-02T12:00:00Z"


class TestParseFeed:
    def test_rss(self):
        title, items = _parse_feed(RSS_XML, 10, True)
        assert title == "Test Blog"
        assert len(items) == 2

    def test_atom(self):
        title, entries = _parse_feed(ATOM_XML, 10, True)
        assert title == "Atom Blog"
        assert len(entries) == 2

    def test_unknown_format(self):
        with pytest.raises(ValueError, match="Unknown feed format"):
            _parse_feed("<html></html>", 10, True)


class TestRSSConnector:
    def test_not_configured(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        assert not c.configured

    def test_configured_with_urls(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        c.configure({"feed_urls": "http://example.com/feed.xml"})
        assert c.configured

    def test_config_schema(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        schema = c.config_schema()
        assert len(schema) >= 1
        assert schema[0].name == "feed_urls"

    def test_get_feed_urls_string(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        c._config["feed_urls"] = "http://a.com\nhttp://b.com"
        assert c._get_feed_urls() == ["http://a.com", "http://b.com"]

    def test_get_feed_urls_list(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        c._config["feed_urls"] = ["http://a.com", "http://b.com"]
        assert c._get_feed_urls() == ["http://a.com", "http://b.com"]

    def test_get_max_items(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        assert c._get_max_items() == 20
        c._config["max_items_per_feed"] = "5"
        assert c._get_max_items() == 5
        c._config["max_items_per_feed"] = "invalid"
        assert c._get_max_items() == 20

    def test_get_include_content(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        assert c._get_include_content() is True
        c._config["include_content"] = "false"
        assert c._get_include_content() is False
        c._config["include_content"] = False
        assert c._get_include_content() is False

    def test_test_connection_no_urls(self, tmp_path):
        c = RSSConnector(data_dir=tmp_path)
        result = c.test_connection()
        assert result["ok"] is False

    @patch("src.connectors.rss.requests.get")
    def test_test_connection_ok(self, mock_get, tmp_path):
        mock_resp = MagicMock()
        mock_resp.text = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        c = RSSConnector(data_dir=tmp_path)
        c.configure({"feed_urls": "http://example.com/feed.xml"})
        result = c.test_connection()
        assert result["ok"] is True
        assert result["feed_title"] == "Test Blog"

    @patch("src.connectors.rss.requests.get")
    def test_test_connection_error(self, mock_get, tmp_path):
        mock_get.side_effect = ConnectionError("fail")
        c = RSSConnector(data_dir=tmp_path)
        c.configure({"feed_urls": "http://example.com/feed.xml"})
        result = c.test_connection()
        assert result["ok"] is False

    def test_sync_no_urls(self, tmp_path, store):
        c = RSSConnector(data_dir=tmp_path)
        result = c.sync(store)
        assert result.errors == ["No feed URLs configured"]

    @patch("src.connectors.rss.requests.get")
    def test_sync(self, mock_get, tmp_path, store):
        mock_resp = MagicMock()
        mock_resp.text = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        c = RSSConnector(data_dir=tmp_path)
        c.configure({"feed_urls": "http://example.com/feed.xml"})
        result = c.sync(store)
        assert result.added == 2
        assert result.errors == []

    @patch("src.connectors.rss.requests.get")
    def test_sync_updates(self, mock_get, tmp_path, store):
        mock_resp = MagicMock()
        mock_resp.text = RSS_XML
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        c = RSSConnector(data_dir=tmp_path)
        c.configure({"feed_urls": "http://example.com/feed.xml"})
        c.sync(store)

        updated_xml = RSS_XML.replace("First post content", "UPDATED content")
        mock_resp2 = MagicMock()
        mock_resp2.text = updated_xml
        mock_resp2.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp2
        result = c.sync(store)
        assert result.updated >= 1

    @patch("src.connectors.rss.requests.get")
    def test_sync_error(self, mock_get, tmp_path, store):
        mock_get.side_effect = ConnectionError("fail")
        c = RSSConnector(data_dir=tmp_path)
        c.configure({"feed_urls": "http://example.com/feed.xml"})
        result = c.sync(store)
        assert len(result.errors) >= 1
