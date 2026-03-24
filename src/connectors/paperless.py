"""Paperless-ngx connector — sync documents into the memory store."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore

import os

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
PAPERLESS_CONFIG = _DATA_DIR / "paperless.json"


@dataclass
class PaperlessConfig:
    url: str = ""
    token: str = ""
    enabled: bool = True
    sync_tags: List[str] = field(default_factory=list)
    last_sync: Optional[float] = None
    synced_docs: int = 0


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    total_remote: int = 0
    errors: List[str] = field(default_factory=list)


class PaperlessClient:

    def __init__(self, url: str, token: str) -> None:
        self.base_url = url.rstrip("/")
        self.token = token

    def _get(self, path: str, params: Optional[Dict[str, str]] = None) -> Dict:
        url = f"{self.base_url}{path}"
        if params:
            qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
            url += f"?{qs}"

        req = urllib.request.Request(url, headers={
            "Authorization": f"Token {self.token}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def test_connection(self) -> Dict:
        """Test connection and return basic stats."""
        docs = self._get("/api/documents/", {"page": "1", "page_size": "1"})
        tags = self._get("/api/tags/", {"page_size": "1"})
        return {
            "ok": True,
            "document_count": docs.get("count", 0),
            "tag_count": tags.get("count", 0),
        }

    def list_tags(self) -> Dict[int, str]:
        """Fetch all tags as {id: name} mapping."""
        tags = {}
        page = 1
        while True:
            data = self._get("/api/tags/", {"page": str(page), "page_size": "100"})
            for t in data.get("results", []):
                tags[t["id"]] = t["name"]
            if not data.get("next"):
                break
            page += 1
        return tags

    def list_correspondents(self) -> Dict[int, str]:
        corrs = {}
        page = 1
        while True:
            data = self._get("/api/correspondents/", {"page": str(page), "page_size": "100"})
            for c in data.get("results", []):
                corrs[c["id"]] = c["name"]
            if not data.get("next"):
                break
            page += 1
        return corrs

    def list_document_types(self) -> Dict[int, str]:
        types = {}
        page = 1
        while True:
            data = self._get("/api/document_types/", {"page": str(page), "page_size": "100"})
            for t in data.get("results", []):
                types[t["id"]] = t["name"]
            if not data.get("next"):
                break
            page += 1
        return types

    def list_documents(self, tag_ids: Optional[List[int]] = None) -> List[Dict]:
        """Fetch all documents, optionally filtered by tag IDs."""
        docs = []
        page = 1
        while True:
            params = {"page": str(page), "page_size": "100"}
            if tag_ids:
                params["tags__id__in"] = ",".join(str(t) for t in tag_ids)
            data = self._get("/api/documents/", params)
            docs.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        return docs


class PaperlessConnector:

    def __init__(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._config = self._load()

    def _load(self) -> Dict[str, Any]:
        if PAPERLESS_CONFIG.exists():
            return json.loads(PAPERLESS_CONFIG.read_text())
        return {"url": "", "token": "", "enabled": True, "sync_tags": [],
                "last_sync": None, "synced_docs": 0}

    def _save(self) -> None:
        PAPERLESS_CONFIG.write_text(json.dumps(self._config, indent=2))

    @property
    def configured(self) -> bool:
        return bool(self._config.get("url") and self._config.get("token"))

    def get_config(self) -> PaperlessConfig:
        return PaperlessConfig(
            url=self._config.get("url", ""),
            token=self._config.get("token", ""),
            enabled=self._config.get("enabled", True),
            sync_tags=self._config.get("sync_tags", []),
            last_sync=self._config.get("last_sync"),
            synced_docs=self._config.get("synced_docs", 0),
        )

    def configure(self, url: str, token: str, sync_tags: Optional[List[str]] = None) -> None:
        self._config["url"] = url.rstrip("/")
        self._config["token"] = token
        if sync_tags is not None:
            self._config["sync_tags"] = sync_tags
        self._save()

    def update(self, **kwargs) -> None:
        for key in ("url", "token", "sync_tags", "enabled"):
            if key in kwargs and kwargs[key] is not None:
                self._config[key] = kwargs[key]
        self._save()

    def remove(self) -> None:
        if PAPERLESS_CONFIG.exists():
            PAPERLESS_CONFIG.unlink()
        self._config = {"url": "", "token": "", "enabled": True, "sync_tags": [],
                        "last_sync": None, "synced_docs": 0}

    def test(self) -> Dict:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        client = PaperlessClient(self._config["url"], self._config["token"])
        try:
            return client.test_connection()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            result = SyncResult()
            result.errors.append("Not configured")
            return result

        result = SyncResult()
        client = PaperlessClient(self._config["url"], self._config["token"])
        prefix = "paperless/"

        try:
            # Resolve tag names → IDs for filtering
            tag_map = client.list_tags()
            corr_map = client.list_correspondents()
            type_map = client.list_document_types()

            filter_tag_ids = None
            sync_tags = self._config.get("sync_tags", [])
            if sync_tags:
                name_to_id = {v.lower(): k for k, v in tag_map.items()}
                filter_tag_ids = [name_to_id[t.lower()] for t in sync_tags if t.lower() in name_to_id]
                if not filter_tag_ids:
                    result.errors.append(f"None of the sync tags found: {sync_tags}")
                    return result

            docs = client.list_documents(tag_ids=filter_tag_ids)
            result.total_remote = len(docs)

        except Exception as e:
            result.errors.append(f"API error: {e}")
            return result

        synced_keys = set()

        for doc in docs:
            doc_id = doc["id"]
            key = f"{prefix}{doc_id}"
            synced_keys.add(key)

            content = doc.get("content", "")
            if not content or not content.strip():
                result.skipped += 1
                continue

            # Build rich content with metadata header
            title = doc.get("title", f"Document {doc_id}")
            corr_name = corr_map.get(doc.get("correspondent")) or ""
            type_name = type_map.get(doc.get("document_type")) or ""
            created = doc.get("created_date", "")
            original = doc.get("original_file_name", "")

            header_parts = [f"# {title}"]
            if corr_name:
                header_parts.append(f"Correspondent: {corr_name}")
            if type_name:
                header_parts.append(f"Type: {type_name}")
            if created:
                header_parts.append(f"Date: {created}")
            if original:
                header_parts.append(f"File: {original}")
            header_parts.append("")

            full_content = "\n".join(header_parts) + content
            content_hash = hashlib.sha256(full_content.encode()).hexdigest()[:16]

            doc_tags = ["paperless"]
            for tid in doc.get("tags", []):
                if tid in tag_map:
                    doc_tags.append(tag_map[tid].lower())
            if corr_name:
                doc_tags.append(corr_name.lower())
            if type_name:
                doc_tags.append(type_name.lower())

            try:
                existing = store.get(key)
                old_hash = existing.metadata.get("content_hash", "")
                if old_hash == content_hash:
                    result.skipped += 1
                    continue
                existing.value = full_content
                existing.tags = doc_tags
                existing.metadata["content_hash"] = content_hash
                existing.metadata["title"] = title
                existing.metadata["paperless_id"] = doc_id
                existing.metadata["correspondent"] = corr_name
                existing.metadata["document_type"] = type_name
                existing.metadata["created_date"] = created
                existing.metadata["original_file"] = original
                existing.updated_at = time.time()
                store.set(existing)
                result.updated += 1
            except KeyError:
                mem = Memory(
                    key=key,
                    value=full_content,
                    tags=doc_tags,
                    metadata={
                        "source": "paperless",
                        "content_hash": content_hash,
                        "paperless_id": doc_id,
                        "title": title,
                        "correspondent": corr_name,
                        "document_type": type_name,
                        "created_date": created,
                        "original_file": original,
                        "paperless_url": f"{self._config['url']}/documents/{doc_id}",
                    },
                )
                store.set(mem)
                result.added += 1

        # Remove memories for documents no longer in Paperless
        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._config["last_sync"] = time.time()
        self._config["synced_docs"] = len(synced_keys)
        self._save()

        return result

    def purge(self, store: MemoryStore) -> int:
        prefix = "paperless/"
        count = 0
        for m in store.list():
            if m.key.startswith(prefix):
                store.delete(m.key)
                count += 1
        return count
