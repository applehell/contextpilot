"""Bookmark/URL connector — fetch and index web page content."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.title = ""
        self._in_title = False
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "nav", "footer", "header"}

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self._skip_tags:
            self._skip = False
        if tag in ("p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr"):
            self.text.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if not self._skip:
            self.text.append(data)

    def get_text(self) -> str:
        raw = "".join(self.text)
        raw = re.sub(r'\n{3,}', '\n\n', raw)
        return raw.strip()


def _fetch_page(url: str, max_size: int = 1024 * 1024) -> tuple:
    """Fetch a URL and extract text + title. Returns (title, text)."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "ContextPilot/3.0 (bookmark indexer)",
        "Accept": "text/html,application/xhtml+xml,text/plain",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        ct = resp.headers.get("Content-Type", "")
        data = resp.read(max_size).decode(errors="replace")

    if "text/html" in ct or "<html" in data[:500].lower():
        parser = _TextExtractor()
        parser.feed(data)
        return parser.title.strip() or url, parser.get_text()
    else:
        return url, data.strip()


class BookmarkConnector(ConnectorPlugin):
    name = "bookmarks"
    display_name = "Bookmarks"
    description = "Fetch and index web pages as knowledge sources"
    icon = "B"

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        super().__init__(data_dir=data_dir)
        if "urls" not in self._config:
            self._config["urls"] = []

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("urls", "URLs (one per line)", type="text",
                        placeholder="https://example.com/page1\nhttps://example.com/page2"),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._get_urls())

    def _get_urls(self) -> List[str]:
        urls = self._config.get("urls", "")
        if isinstance(urls, list):
            return [u.strip() for u in urls if u.strip()]
        if isinstance(urls, str):
            return [u.strip() for u in urls.replace(",", "\n").split("\n") if u.strip()]
        return []

    def configure(self, values: Dict[str, Any]) -> None:
        super().configure(values)
        self._config["_configured"] = bool(self._get_urls())
        self._save()

    def add_url(self, url: str) -> None:
        urls = self._get_urls()
        if url not in urls:
            urls.append(url)
            self._config["urls"] = "\n".join(urls)
            self._config["_configured"] = True
            self._save()

    def remove_url(self, url: str) -> None:
        urls = self._get_urls()
        urls = [u for u in urls if u != url]
        self._config["urls"] = "\n".join(urls)
        self._save()

    def test_connection(self) -> Dict[str, Any]:
        urls = self._get_urls()
        if not urls:
            return {"ok": False, "error": "No URLs configured"}
        return {"ok": True, "url_count": len(urls)}

    def sync(self, store: MemoryStore) -> SyncResult:
        urls = self._get_urls()
        if not urls:
            r = SyncResult()
            r.errors.append("No URLs configured")
            return r

        result = SyncResult()
        result.total_remote = len(urls)
        prefix = f"{self.name}/"
        synced_keys = set()

        for url in urls:
            url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
            key = f"{prefix}{url_hash}"
            synced_keys.add(key)

            try:
                title, text = _fetch_page(url)
                if not text:
                    result.skipped += 1
                    continue
            except Exception as e:
                result.errors.append(f"{url}: {e}")
                continue

            content = f"# {title}\nSource: {url}\n\n{text}"
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
                store.set(existing)
                result.updated += 1
            except KeyError:
                mem = Memory(key=key, value=content, tags=[self.name, "web"],
                             metadata={
                                 "source": self.name, "content_hash": content_hash,
                                 "url": url, "title": title, "fetched_at": time.time(),
                             })
                store.set(mem)
                result.added += 1

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result
