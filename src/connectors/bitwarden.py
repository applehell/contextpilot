"""Bitwarden connector — sync secure notes and folder structure.

SECURITY: This connector ONLY syncs Secure Notes (type=2).
It NEVER syncs Logins (type=1), Cards (type=3), or Identity (type=4).
No passwords, usernames, TOTP secrets, or login credentials are ever stored.
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, List, Optional

import requests

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

SECURE_NOTE_TYPE = 2
BLOCKED_TYPES = {1, 3, 4}  # Login, Card, Identity — NEVER sync


class _BitwardenAPI:
    def __init__(self, server_url: str, client_id: str, client_secret: str) -> None:
        self.server_url = server_url.rstrip("/")
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token: Optional[str] = None

    def authenticate(self) -> None:
        resp = requests.post(
            f"{self.server_url}/identity/connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "api",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )
        resp.raise_for_status()
        self.access_token = resp.json()["access_token"]

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }

    def sync(self) -> Dict[str, Any]:
        resp = requests.get(
            f"{self.server_url}/api/sync",
            headers=self._headers(),
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def folders(self) -> List[Dict[str, Any]]:
        data = self.sync()
        return data.get("folders", [])

    def secure_notes(self, folder_filter: Optional[List[str]] = None) -> tuple[List[Dict], Dict[str, str]]:
        data = self.sync()

        folder_map: Dict[str, str] = {}
        for f in data.get("folders", []):
            folder_map[f["id"]] = f.get("name", "Unknown")

        allowed_folder_ids: Optional[set] = None
        if folder_filter:
            filter_lower = {n.lower().strip() for n in folder_filter}
            allowed_folder_ids = set()
            for fid, fname in folder_map.items():
                if fname.lower() in filter_lower:
                    allowed_folder_ids.add(fid)

        notes = []
        for item in data.get("ciphers", []):
            if item.get("type") != SECURE_NOTE_TYPE:
                continue
            if item.get("type") in BLOCKED_TYPES:
                continue
            fid = item.get("folderId")
            if allowed_folder_ids is not None:
                if fid not in allowed_folder_ids:
                    continue
            notes.append(item)

        return notes, folder_map


class BitwardenConnector(ConnectorPlugin):
    name = "bitwarden"
    display_name = "Bitwarden"
    description = "Sync secure notes and folder structure from Bitwarden"
    icon = "BW"
    category = "Knowledge"
    setup_guide = (
        "Use the Bitwarden CLI (bw) or API. Provide your API client_id and "
        "client_secret from vault settings, or a session key from 'bw unlock'."
    )
    color = "#175ddc"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("server_url", "Server URL", type="text",
                        placeholder="https://vault.bitwarden.com",
                        default="https://vault.bitwarden.com"),
            ConfigField("client_id", "API Client ID", type="text",
                        placeholder="user.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
                        required=True),
            ConfigField("client_secret", "API Client Secret", type="password",
                        placeholder="Your API client secret",
                        required=True),
            ConfigField("folder_filter", "Folder filter", type="text",
                        placeholder="Optional: Notes, Wiki, Projects (comma-separated)"),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("client_id") and self._config.get("client_secret"))

    def _api(self) -> _BitwardenAPI:
        return _BitwardenAPI(
            server_url=self._config.get("server_url", "https://vault.bitwarden.com"),
            client_id=self._config.get("client_id", ""),
            client_secret=self._config.get("client_secret", ""),
        )

    def _parse_folder_filter(self) -> Optional[List[str]]:
        raw = self._config.get("folder_filter", "")
        if not raw or not raw.strip():
            return None
        return [f.strip() for f in raw.split(",") if f.strip()]

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Client ID and secret are required"}
        try:
            api = self._api()
            api.authenticate()
            folders = api.folders()
            folder_names = [f.get("name", "Unknown") for f in folders]
            return {
                "ok": True,
                "folders": folder_names,
                "folder_count": len(folder_names),
            }
        except requests.HTTPError as e:
            return {"ok": False, "error": f"Authentication failed: {e.response.status_code}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r

        result = SyncResult()
        prefix = f"{self.name}/"
        synced_keys: set[str] = set()
        folder_filter = self._parse_folder_filter()

        try:
            api = self._api()
            api.authenticate()
            notes, folder_map = api.secure_notes(folder_filter)
        except Exception as e:
            result.errors.append(f"Sync failed: {e}")
            return result

        for item in notes:
            if item.get("type") != SECURE_NOTE_TYPE:
                continue
            if item.get("type") in BLOCKED_TYPES:
                continue

            name = item.get("name", "Untitled")
            folder_id = item.get("folderId")
            folder_name = folder_map.get(folder_id, "No Folder") if folder_id else "No Folder"
            note_body = item.get("notes") or ""
            revision_date = item.get("revisionDate", "")

            safe_folder = folder_name.replace("/", "-")
            safe_name = name.replace("/", "-")
            key = f"{prefix}{safe_folder}/{safe_name}"
            synced_keys.add(key)
            result.total_remote += 1

            lines = [f"# {name}"]
            lines.append(f"Folder: {folder_name}")
            if revision_date:
                lines.append(f"Revision: {revision_date}")
            lines.append("")
            lines.append(note_body)
            content = "\n".join(lines)

            tags = [self.name, folder_name]
            self._upsert(store, key, content, tags, folder_name, result)

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _upsert(self, store, key, content, tags, folder_name, result):
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
            meta = {"source": self.name, "content_hash": content_hash, "folder": folder_name}
            if ttl_sec:
                meta["ttl_seconds"] = ttl_sec
            mem = Memory(key=key, value=content, tags=tags, metadata=meta,
                         expires_at=expires_at)
            store.set(mem)
            result.added += 1
