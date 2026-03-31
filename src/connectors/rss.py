"""RSS / Atom feed connector — fetch and index feed items."""
from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from pathlib import Path

import requests

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|li|tr|h[1-6])>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#?\w+;", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _el_text(el: Optional[ET.Element]) -> str:
    if el is None:
        return ""
    return (el.text or "").strip()


def _parse_rss_items(root: ET.Element, max_items: int, include_content: bool) -> tuple:
    channel = root.find("channel")
    if channel is None:
        return "", []

    feed_title = _el_text(channel.find("title")) or "RSS Feed"
    items = []
    for item in channel.findall("item")[:max_items]:
        title = _el_text(item.find("title"))
        link = _el_text(item.find("link"))
        pub_date = _el_text(item.find("pubDate"))
        guid = _el_text(item.find("guid")) or link or title

        description = ""
        if include_content:
            content_encoded = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
            if content_encoded is not None and content_encoded.text:
                description = content_encoded.text.strip()
            else:
                description = _el_text(item.find("description"))
        else:
            description = _el_text(item.find("description"))

        items.append({
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "guid": guid,
            "description": description,
        })
    return feed_title, items


def _parse_atom_entries(root: ET.Element, max_items: int, include_content: bool) -> tuple:
    feed_title = _el_text(root.find(f"{_ATOM_NS}title")) or "Atom Feed"
    entries = []
    for entry in root.findall(f"{_ATOM_NS}entry")[:max_items]:
        title = _el_text(entry.find(f"{_ATOM_NS}title"))

        link_el = entry.find(f"{_ATOM_NS}link[@rel='alternate']")
        if link_el is None:
            link_el = entry.find(f"{_ATOM_NS}link")
        link = link_el.get("href", "") if link_el is not None else ""

        published = _el_text(entry.find(f"{_ATOM_NS}published"))
        if not published:
            published = _el_text(entry.find(f"{_ATOM_NS}updated"))

        entry_id = _el_text(entry.find(f"{_ATOM_NS}id")) or link or title

        description = ""
        if include_content:
            content_el = entry.find(f"{_ATOM_NS}content")
            if content_el is not None and content_el.text:
                description = content_el.text.strip()
            else:
                description = _el_text(entry.find(f"{_ATOM_NS}summary"))
        else:
            description = _el_text(entry.find(f"{_ATOM_NS}summary"))

        entries.append({
            "title": title,
            "link": link,
            "pub_date": published,
            "guid": entry_id,
            "description": description,
        })
    return feed_title, entries


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _parse_feed(xml_text: str, max_items: int, include_content: bool) -> tuple:
    root = ET.fromstring(xml_text)
    tag = _strip_ns(root.tag)
    if tag == "rss":
        return _parse_rss_items(root, max_items, include_content)
    if tag == "feed":
        return _parse_atom_entries(root, max_items, include_content)
    raise ValueError(f"Unknown feed format: <{root.tag}>")


class RSSConnector(ConnectorPlugin):
    name = "rss"
    display_name = "RSS / Atom Feeds"
    description = "Subscribe to RSS and Atom feeds as knowledge sources"
    icon = "RS"
    category = "Knowledge"
    setup_guide = "Add feed URLs (one per line). Supports RSS 2.0 and Atom feeds."
    color = "#ee802f"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("feed_urls", "Feed URLs (one per line)", type="text",
                        placeholder="https://example.com/feed.xml\nhttps://blog.example.com/rss",
                        required=True),
            ConfigField("max_items_per_feed", "Max items per feed", type="number",
                        placeholder="20", default=20),
            ConfigField("include_content", "Include full content", type="boolean",
                        default=True),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._get_feed_urls())

    def _get_feed_urls(self) -> List[str]:
        urls = self._config.get("feed_urls", "")
        if isinstance(urls, list):
            return [u.strip() for u in urls if u.strip()]
        if isinstance(urls, str):
            return [u.strip() for u in urls.replace(",", "\n").split("\n") if u.strip()]
        return []

    def _get_max_items(self) -> int:
        val = self._config.get("max_items_per_feed", 20)
        try:
            return max(1, int(val))
        except (ValueError, TypeError):
            return 20

    def _get_include_content(self) -> bool:
        val = self._config.get("include_content", True)
        if isinstance(val, str):
            return val.lower() not in ("false", "0", "no", "")
        return bool(val)

    def configure(self, values: Dict[str, Any]) -> None:
        super().configure(values)
        self._config["_configured"] = bool(self._get_feed_urls())
        self._save()

    def test_connection(self) -> Dict[str, Any]:
        urls = self._get_feed_urls()
        if not urls:
            return {"ok": False, "error": "No feed URLs configured"}
        try:
            resp = requests.get(urls[0], timeout=15, headers={
                "User-Agent": "ContextPilot/3.0 (feed reader)",
                "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            })
            resp.raise_for_status()
            feed_title, items = _parse_feed(resp.text, 1, False)
            return {"ok": True, "feed_title": feed_title, "feed_count": len(urls)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        urls = self._get_feed_urls()
        if not urls:
            r = SyncResult()
            r.errors.append("No feed URLs configured")
            return r

        max_items = self._get_max_items()
        include_content = self._get_include_content()
        result = SyncResult()
        prefix = f"{self.name}/"
        synced_keys = set()
        expires_at = self._compute_expires_at()

        for feed_url in urls:
            try:
                resp = requests.get(feed_url, timeout=15, headers={
                    "User-Agent": "ContextPilot/3.0 (feed reader)",
                    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
                })
                resp.raise_for_status()
                feed_title, items = _parse_feed(resp.text, max_items, include_content)
            except Exception as e:
                result.errors.append(f"{feed_url}: {e}")
                continue

            result.total_remote += len(items)

            for item in items:
                guid_hash = hashlib.md5(item["guid"].encode()).hexdigest()[:12]
                safe_title = re.sub(r"[^a-zA-Z0-9_-]", "_", feed_title)[:40]
                key = f"{prefix}{safe_title}/{guid_hash}"
                synced_keys.add(key)

                title = item["title"] or "Untitled"
                link = item["link"]
                pub_date = item["pub_date"]
                description = _strip_html(item["description"]) if item["description"] else ""

                parts = [f"# {title}"]
                if link:
                    parts.append(f"Source: {link}")
                if pub_date:
                    parts.append(f"Date: {pub_date}")
                parts.append("")
                if description:
                    parts.append(description)

                content = "\n".join(parts)
                if len(content) > 100000:
                    content = content[:100000] + "\n\n[truncated]"
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                try:
                    existing = store.get(key)
                    if existing.metadata.get("content_hash") == content_hash:
                        result.skipped += 1
                        continue
                    existing.value = content
                    existing.metadata["content_hash"] = content_hash
                    existing.metadata["title"] = title
                    existing.metadata["fetched_at"] = time.time()
                    existing.updated_at = time.time()
                    if expires_at:
                        existing.expires_at = expires_at
                    store.set(existing)
                    result.updated += 1
                except KeyError:
                    mem = Memory(
                        key=key, value=content,
                        tags=["rss", feed_title],
                        metadata={
                            "source": self.name,
                            "content_hash": content_hash,
                            "feed_url": feed_url,
                            "feed_title": feed_title,
                            "title": title,
                            "link": link,
                            "pub_date": pub_date,
                            "fetched_at": time.time(),
                        },
                    )
                    if expires_at:
                        mem.expires_at = expires_at
                    store.set(mem)
                    result.added += 1

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys), result)
        return result
