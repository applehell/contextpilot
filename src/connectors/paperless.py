"""Paperless-ngx connector plugin."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


class _PaperlessAPI:
    """Low-level Paperless-ngx REST API client."""

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

    def _paginate(self, path: str, params: Optional[Dict[str, str]] = None) -> List[Dict]:
        items = []
        page = 1
        while True:
            p = dict(params or {})
            p["page"] = str(page)
            p.setdefault("page_size", "100")
            data = self._get(path, p)
            items.extend(data.get("results", []))
            if not data.get("next"):
                break
            page += 1
        return items

    def test(self) -> Dict:
        docs = self._get("/api/documents/", {"page": "1", "page_size": "1"})
        tags = self._get("/api/tags/", {"page_size": "1"})
        return {"ok": True, "document_count": docs.get("count", 0), "tag_count": tags.get("count", 0)}

    def tags(self) -> Dict[int, str]:
        return {t["id"]: t["name"] for t in self._paginate("/api/tags/")}

    def correspondents(self) -> Dict[int, str]:
        return {c["id"]: c["name"] for c in self._paginate("/api/correspondents/")}

    def document_types(self) -> Dict[int, str]:
        return {t["id"]: t["name"] for t in self._paginate("/api/document_types/")}

    def documents(self, tag_ids: Optional[List[int]] = None) -> List[Dict]:
        params = {}
        if tag_ids:
            params["tags__id__in"] = ",".join(str(t) for t in tag_ids)
        return self._paginate("/api/documents/", params)


class PaperlessConnector(ConnectorPlugin):
    name = "paperless"
    display_name = "Paperless-ngx"
    description = "Sync OCR'd documents from Paperless-ngx"
    icon = "P"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("url", "URL", placeholder="http://192.168.1.x:8000", required=True),
            ConfigField("token", "API Token", type="password", placeholder="Token from Paperless admin", required=True),
            ConfigField("sync_tags", "Sync tags (comma-separated)", type="tags", placeholder="e.g. finance, contracts"),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("url") and self._config.get("token"))

    def _api(self) -> _PaperlessAPI:
        return _PaperlessAPI(self._config["url"], self._config["token"])

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        try:
            return self._api().test()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r

        result = SyncResult()
        api = self._api()
        prefix = f"{self.name}/"

        try:
            tag_map = api.tags()
            corr_map = api.correspondents()
            type_map = api.document_types()

            filter_tag_ids = None
            sync_tags = self._config.get("sync_tags", "")
            if isinstance(sync_tags, str) and sync_tags.strip():
                tag_list = [t.strip() for t in sync_tags.split(",") if t.strip()]
            elif isinstance(sync_tags, list):
                tag_list = sync_tags
            else:
                tag_list = []

            if tag_list:
                name_to_id = {v.lower(): k for k, v in tag_map.items()}
                filter_tag_ids = [name_to_id[t.lower()] for t in tag_list if t.lower() in name_to_id]
                if not filter_tag_ids:
                    result.errors.append(f"None of the sync tags found: {tag_list}")
                    return result

            docs = api.documents(tag_ids=filter_tag_ids)
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

            title = doc.get("title", f"Document {doc_id}")
            corr_name = corr_map.get(doc.get("correspondent")) or ""
            type_name = type_map.get(doc.get("document_type")) or ""
            created = doc.get("created_date", "")
            original = doc.get("original_file_name", "")

            header = [f"# {title}"]
            if corr_name: header.append(f"Correspondent: {corr_name}")
            if type_name: header.append(f"Type: {type_name}")
            if created: header.append(f"Date: {created}")
            if original: header.append(f"File: {original}")
            header.append("")

            full_content = "\n".join(header) + content
            content_hash = hashlib.sha256(full_content.encode()).hexdigest()[:16]

            doc_tags = [self.name]
            for tid in doc.get("tags", []):
                if tid in tag_map:
                    doc_tags.append(tag_map[tid].lower())
            if corr_name: doc_tags.append(corr_name.lower())
            if type_name: doc_tags.append(type_name.lower())

            try:
                existing = store.get(key)
                if existing.metadata.get("content_hash") == content_hash:
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
                        "source": self.name,
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

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result
