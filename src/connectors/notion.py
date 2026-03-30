"""Notion connector — sync pages and databases via the Notion API."""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

import requests

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

NOTION_API = "https://api.notion.com"
NOTION_VERSION = "2022-06-28"


class _NotionAPI:
    def __init__(self, token: str) -> None:
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        resp = requests.get(f"{NOTION_API}{path}", headers=self.headers,
                            params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: Optional[Dict] = None) -> Dict:
        resp = requests.post(f"{NOTION_API}{path}", headers=self.headers,
                             json=body or {}, timeout=20)
        resp.raise_for_status()
        return resp.json()

    def me(self) -> Dict:
        return self._get("/v1/users/me")

    def search(self, filter_type: Optional[str] = None,
               page_size: int = 100, start_cursor: Optional[str] = None) -> Dict:
        body: Dict[str, Any] = {"page_size": min(page_size, 100)}
        if filter_type:
            body["filter"] = {"value": filter_type, "property": "object"}
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._post("/v1/search", body)

    def get_blocks(self, block_id: str, start_cursor: Optional[str] = None) -> Dict:
        params = {}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._get(f"/v1/blocks/{block_id}/children", params=params)

    def query_database(self, database_id: str,
                       start_cursor: Optional[str] = None) -> Dict:
        body: Dict[str, Any] = {"page_size": 100}
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._post(f"/v1/databases/{database_id}/query", body)


def _rich_text_to_str(rich_texts: List[Dict]) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def _blocks_to_markdown(blocks: List[Dict]) -> str:
    lines: List[str] = []
    numbered_counter = 0

    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})

        if btype == "paragraph":
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(text)
            numbered_counter = 0
        elif btype == "heading_1":
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(f"# {text}")
            numbered_counter = 0
        elif btype == "heading_2":
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(f"## {text}")
            numbered_counter = 0
        elif btype == "heading_3":
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(f"### {text}")
            numbered_counter = 0
        elif btype == "bulleted_list_item":
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(f"- {text}")
            numbered_counter = 0
        elif btype == "numbered_list_item":
            numbered_counter += 1
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(f"{numbered_counter}. {text}")
        elif btype == "code":
            text = _rich_text_to_str(data.get("rich_text", []))
            lang = data.get("language", "")
            lines.append(f"```{lang}")
            lines.append(text)
            lines.append("```")
            numbered_counter = 0
        elif btype == "quote":
            text = _rich_text_to_str(data.get("rich_text", []))
            for line in text.split("\n"):
                lines.append(f"> {line}")
            numbered_counter = 0
        elif btype == "to_do":
            text = _rich_text_to_str(data.get("rich_text", []))
            checked = data.get("checked", False)
            marker = "[x]" if checked else "[ ]"
            lines.append(f"- {marker} {text}")
            numbered_counter = 0
        elif btype == "toggle":
            text = _rich_text_to_str(data.get("rich_text", []))
            lines.append(f"<details><summary>{text}</summary></details>")
            numbered_counter = 0
        elif btype == "callout":
            text = _rich_text_to_str(data.get("rich_text", []))
            icon = data.get("icon", {})
            emoji = icon.get("emoji", "") if icon else ""
            prefix = f"{emoji} " if emoji else ""
            lines.append(f"> {prefix}{text}")
            numbered_counter = 0
        elif btype == "divider":
            lines.append("---")
            numbered_counter = 0
        elif btype == "table":
            pass
        else:
            numbered_counter = 0

        if btype not in ("bulleted_list_item", "numbered_list_item",
                         "to_do", "code", "table"):
            lines.append("")

    return "\n".join(lines).strip()


def _get_page_title(page: Dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return _rich_text_to_str(prop.get("title", []))
    return page.get("id", "Untitled")[:8]


def _get_database_title(db: Dict) -> str:
    title_parts = db.get("title", [])
    if title_parts:
        return _rich_text_to_str(title_parts)
    return db.get("id", "Untitled")[:8]


def _format_property_value(prop: Dict) -> str:
    ptype = prop.get("type", "")
    if ptype == "title":
        return _rich_text_to_str(prop.get("title", []))
    elif ptype == "rich_text":
        return _rich_text_to_str(prop.get("rich_text", []))
    elif ptype == "number":
        val = prop.get("number")
        return str(val) if val is not None else ""
    elif ptype == "select":
        sel = prop.get("select")
        return sel.get("name", "") if sel else ""
    elif ptype == "multi_select":
        return ", ".join(s.get("name", "") for s in prop.get("multi_select", []))
    elif ptype == "date":
        date = prop.get("date")
        if not date:
            return ""
        start = date.get("start", "")
        end = date.get("end", "")
        return f"{start} - {end}" if end else start
    elif ptype == "checkbox":
        return "Yes" if prop.get("checkbox") else "No"
    elif ptype == "url":
        return prop.get("url", "") or ""
    elif ptype == "email":
        return prop.get("email", "") or ""
    elif ptype == "phone_number":
        return prop.get("phone_number", "") or ""
    elif ptype == "status":
        st = prop.get("status")
        return st.get("name", "") if st else ""
    elif ptype == "people":
        return ", ".join(p.get("name", "") for p in prop.get("people", []))
    elif ptype == "relation":
        return f"({len(prop.get('relation', []))} relations)"
    elif ptype == "formula":
        formula = prop.get("formula", {})
        ftype = formula.get("type", "")
        return str(formula.get(ftype, ""))
    elif ptype == "rollup":
        rollup = prop.get("rollup", {})
        rtype = rollup.get("type", "")
        return str(rollup.get(rtype, ""))
    return ""


class NotionConnector(ConnectorPlugin):
    name = "notion"
    display_name = "Notion"
    description = "Sync pages and databases from Notion workspaces"
    icon = "N"
    category = "Knowledge"
    setup_guide = "Create an internal integration at notion.so/my-integrations and share pages/databases with it."
    color = "#000"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("token", "Integration Token", type="password",
                        placeholder="secret_...", required=True),
            ConfigField("database_ids", "Database IDs to sync", type="text",
                        placeholder="Optional — comma-separated database IDs"),
            ConfigField("sync_pages", "Sync pages", type="boolean", default=True),
            ConfigField("sync_databases", "Sync databases", type="boolean",
                        default=True),
            ConfigField("page_limit", "Page limit", type="number",
                        placeholder="100", default=100),
        ]

    def _api(self) -> _NotionAPI:
        return _NotionAPI(self._config.get("token", ""))

    def test_connection(self) -> Dict[str, Any]:
        token = self._config.get("token", "")
        if not token:
            return {"ok": False, "error": "No integration token configured"}
        try:
            api = self._api()
            user = api.me()
            name = user.get("name", "") or user.get("bot", {}).get("owner", {}).get("type", "bot")
            return {"ok": True, "user": name, "type": user.get("type", "bot")}
        except requests.HTTPError as e:
            return {"ok": False, "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        token = self._config.get("token", "")
        if not token:
            r = SyncResult()
            r.errors.append("No integration token configured")
            return r

        result = SyncResult()
        api = self._api()
        prefix = f"{self.name}/"
        synced_keys: set[str] = set()
        sync_pages = self._config.get("sync_pages", True)
        sync_databases = self._config.get("sync_databases", True)
        page_limit = int(self._config.get("page_limit", 100))
        explicit_db_ids = self._parse_database_ids()

        # Sync explicitly listed databases
        for db_id in explicit_db_ids:
            try:
                self._sync_database(api, db_id, store, prefix, synced_keys, result)
            except Exception as e:
                result.errors.append(f"Database {db_id[:8]}: {e}")

        # Search for pages and databases
        fetched = 0
        start_cursor = None
        while fetched < page_limit:
            try:
                batch_size = min(100, page_limit - fetched)
                data = api.search(page_size=batch_size, start_cursor=start_cursor)
            except Exception as e:
                result.errors.append(f"Search failed: {e}")
                break

            results_list = data.get("results", [])
            if not results_list:
                break

            for item in results_list:
                obj_type = item.get("object")
                item_id = item.get("id", "")

                if obj_type == "page" and sync_pages:
                    try:
                        self._sync_page(api, item, store, prefix, synced_keys, result)
                    except Exception as e:
                        result.errors.append(f"Page {item_id[:8]}: {e}")

                elif obj_type == "database" and sync_databases:
                    if item_id not in explicit_db_ids:
                        try:
                            self._sync_database(api, item_id, store, prefix,
                                                synced_keys, result, db_meta=item)
                        except Exception as e:
                            result.errors.append(f"Database {item_id[:8]}: {e}")

            fetched += len(results_list)
            if not data.get("has_more") or not data.get("next_cursor"):
                break
            start_cursor = data["next_cursor"]

        # Cleanup removed items
        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _parse_database_ids(self) -> List[str]:
        raw = self._config.get("database_ids", "")
        if not raw:
            return []
        return [db_id.strip() for db_id in raw.split(",") if db_id.strip()]

    def _sync_page(self, api: _NotionAPI, page: Dict, store: MemoryStore,
                   prefix: str, synced_keys: set, result: SyncResult) -> None:
        page_id = page["id"]
        title = _get_page_title(page)
        key = f"{prefix}{page_id}"
        synced_keys.add(key)
        result.total_remote += 1

        # Fetch all blocks with pagination
        all_blocks: List[Dict] = []
        cursor: Optional[str] = None
        while True:
            block_data = api.get_blocks(page_id, start_cursor=cursor)
            all_blocks.extend(block_data.get("results", []))
            if not block_data.get("has_more") or not block_data.get("next_cursor"):
                break
            cursor = block_data["next_cursor"]

        body = _blocks_to_markdown(all_blocks)
        last_edited = page.get("last_edited_time", "")

        lines = [f"# {title}"]
        if last_edited:
            lines.append(f"**Last edited:** {last_edited[:10]}")
        url = page.get("url", "")
        if url:
            lines.append(f"**URL:** {url}")
        if body:
            lines.append(f"\n{body}")

        content = "\n".join(lines)
        tags = [self.name, title]
        self._upsert(store, key, content, tags, title, result)

    def _sync_database(self, api: _NotionAPI, db_id: str, store: MemoryStore,
                       prefix: str, synced_keys: set, result: SyncResult,
                       db_meta: Optional[Dict] = None) -> None:
        key = f"{prefix}db/{db_id}"
        synced_keys.add(key)
        result.total_remote += 1

        # Get database title
        if db_meta:
            db_title = _get_database_title(db_meta)
        else:
            db_title = db_id[:8]

        # Query all rows with pagination
        all_rows: List[Dict] = []
        cursor: Optional[str] = None
        while True:
            data = api.query_database(db_id, start_cursor=cursor)
            all_rows.extend(data.get("results", []))
            if not data.get("has_more") or not data.get("next_cursor"):
                break
            cursor = data["next_cursor"]

        lines = [f"# Database: {db_title}", f"**Rows:** {len(all_rows)}", ""]

        for row in all_rows:
            props = row.get("properties", {})
            row_parts: List[str] = []
            for prop_name, prop_val in props.items():
                formatted = _format_property_value(prop_val)
                if formatted:
                    row_parts.append(f"**{prop_name}:** {formatted}")
            if row_parts:
                lines.append("- " + " | ".join(row_parts))

        content = "\n".join(lines)
        tags = [self.name, db_title]
        self._upsert(store, key, content, tags, db_title, result)

    def _upsert(self, store: MemoryStore, key: str, content: str,
                tags: List[str], title: str, result: SyncResult) -> None:
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        expires_at = self._compute_expires_at()
        ttl_sec = self._ttl_seconds()
        try:
            existing = store.get(key)
            if existing.metadata.get("content_hash") == content_hash:
                result.skipped += 1
                return
            existing.value = content
            existing.tags = tags
            existing.metadata["content_hash"] = content_hash
            if ttl_sec:
                existing.metadata["ttl_seconds"] = ttl_sec
            existing.expires_at = expires_at
            existing.updated_at = time.time()
            store.set(existing, reset_ttl=False)
            result.updated += 1
        except KeyError:
            meta = {"source": self.name, "content_hash": content_hash, "title": title}
            if ttl_sec:
                meta["ttl_seconds"] = ttl_sec
            mem = Memory(key=key, value=content, tags=tags, metadata=meta,
                         expires_at=expires_at)
            store.set(mem)
            result.added += 1
