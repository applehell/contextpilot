"""Tests for M12: RSS parser uses defusedxml when available."""
from __future__ import annotations

import pytest

from src.connectors.rss import _parse_feed, SafeET


def test_defusedxml_is_available() -> None:
    assert SafeET is not None, "defusedxml should be installed"


def test_rss_parse_still_works() -> None:
    xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>Article 1</title>
          <link>https://example.com/1</link>
          <description>First article</description>
          <guid>1</guid>
        </item>
      </channel>
    </rss>"""
    title, items = _parse_feed(xml, 10, True)
    assert title == "Test Feed"
    assert len(items) == 1
    assert items[0]["title"] == "Article 1"


def test_atom_parse_still_works() -> None:
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Atom Feed</title>
      <entry>
        <title>Entry 1</title>
        <link href="https://example.com/1" rel="alternate"/>
        <id>urn:entry:1</id>
        <summary>Summary text</summary>
      </entry>
    </feed>"""
    title, items = _parse_feed(xml, 10, True)
    assert title == "Atom Feed"
    assert len(items) == 1
    assert items[0]["title"] == "Entry 1"
