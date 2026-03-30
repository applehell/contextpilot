"""Google Drive connector — sync documents, spreadsheets, and presentations via service account."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None  # type: ignore[assignment]

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

MIME_GOOGLE_DOC = "application/vnd.google-apps.document"
MIME_GOOGLE_SHEET = "application/vnd.google-apps.spreadsheet"
MIME_GOOGLE_SLIDES = "application/vnd.google-apps.presentation"
MIME_GOOGLE_FOLDER = "application/vnd.google-apps.folder"

GOOGLE_EXPORT_MAP = {
    MIME_GOOGLE_DOC: ("text/plain", "document"),
    MIME_GOOGLE_SHEET: ("text/csv", "spreadsheet"),
    MIME_GOOGLE_SLIDES: ("text/plain", "presentation"),
}

DOWNLOADABLE_MIMES = {
    "application/pdf": "pdf",
    "text/plain": "text",
    "text/csv": "csv",
    "text/markdown": "markdown",
    "text/html": "html",
    "application/json": "json",
    "application/xml": "xml",
    "text/xml": "xml",
}

FILE_TYPE_FILTERS = {
    "document": MIME_GOOGLE_DOC,
    "spreadsheet": MIME_GOOGLE_SHEET,
    "presentation": MIME_GOOGLE_SLIDES,
}

TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPES = "https://www.googleapis.com/auth/drive.readonly"


class _GoogleAuth:
    """JWT-based service account authentication for Google APIs."""

    def __init__(self, service_account_json: str) -> None:
        self._sa = json.loads(service_account_json)
        self._token: Optional[str] = None
        self._expires_at: float = 0

    def get_token(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        if pyjwt is None:
            raise RuntimeError("PyJWT is required: pip install PyJWT")

        now = int(time.time())
        payload = {
            "iss": self._sa["client_email"],
            "scope": SCOPES,
            "aud": TOKEN_URL,
            "iat": now,
            "exp": now + 3600,
        }
        signed = pyjwt.encode(payload, self._sa["private_key"], algorithm="RS256")

        data = urllib.request.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "assertion": signed,
        }).encode()
        req = urllib.request.Request(TOKEN_URL, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=15) as resp:
            token_data = json.loads(resp.read().decode())

        self._token = token_data["access_token"]
        self._expires_at = now + token_data.get("expires_in", 3600)
        return self._token


class _DriveAPI:
    """Thin wrapper around Google Drive REST API v3."""

    def __init__(self, auth: _GoogleAuth) -> None:
        self._auth = auth

    def _get(self, url: str, params: Optional[Dict[str, str]] = None) -> Any:
        token = self._auth.get_token()
        if params:
            qs = urllib.request.urlencode(params)
            url = f"{url}?{qs}"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "ContextPilot/1.0",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())

    def _get_bytes(self, url: str) -> bytes:
        token = self._auth.get_token()
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "ContextPilot/1.0",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()

    def list_files(self, folder_id: Optional[str] = None,
                   mime_filters: Optional[List[str]] = None,
                   max_files: int = 100) -> List[Dict]:
        """List files, optionally within a folder and filtered by MIME type."""
        query_parts = ["trashed = false"]
        if folder_id:
            query_parts.append(f"'{folder_id}' in parents")
        if mime_filters:
            mime_clauses = " or ".join(f"mimeType = '{m}'" for m in mime_filters)
            query_parts.append(f"({mime_clauses})")

        query = " and ".join(query_parts)
        fields = "nextPageToken, files(id, name, mimeType, modifiedTime, size, webViewLink)"

        all_files: List[Dict] = []
        page_token: Optional[str] = None

        while len(all_files) < max_files:
            params: Dict[str, str] = {
                "q": query,
                "fields": fields,
                "pageSize": str(min(100, max_files - len(all_files))),
                "orderBy": "modifiedTime desc",
            }
            if page_token:
                params["pageToken"] = page_token

            data = self._get(f"{DRIVE_API}/files", params)
            all_files.extend(data.get("files", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_files[:max_files]

    def export_file(self, file_id: str, export_mime: str) -> str:
        """Export a Google Workspace file (Docs/Sheets/Slides) to the given MIME type."""
        params = urllib.request.urlencode({"mimeType": export_mime})
        url = f"{DRIVE_API}/files/{file_id}/export?{params}"
        content = self._get_bytes(url)
        return content.decode(errors="replace")

    def download_file(self, file_id: str) -> bytes:
        """Download a non-Google file (PDF, text, etc.)."""
        url = f"{DRIVE_API}/files/{file_id}?alt=media"
        return self._get_bytes(url)


class GoogleDriveConnector(ConnectorPlugin):
    name = "gdrive"
    display_name = "Google Drive"
    description = "Sync documents, spreadsheets, and presentations from Google Drive"
    icon = "GD"
    category = "Documents"
    setup_guide = ("Create a service account at console.cloud.google.com, enable Drive API, "
                   "download JSON key file and paste its content.")
    color = "#4285f4"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("service_account_json", "Service Account JSON", type="password",
                        placeholder="Paste the entire JSON key file content",
                        required=True),
            ConfigField("folder_id", "Folder ID", type="text",
                        placeholder="Optional — restrict to a specific folder"),
            ConfigField("file_types", "File types to sync", type="text",
                        placeholder="document, spreadsheet, presentation",
                        default="document,spreadsheet,presentation"),
            ConfigField("max_files", "Max files", type="number",
                        placeholder="100", default=100),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("service_account_json"))

    def _auth(self) -> _GoogleAuth:
        return _GoogleAuth(self._config["service_account_json"])

    def _api(self) -> _DriveAPI:
        return _DriveAPI(self._auth())

    def _parse_file_types(self) -> List[str]:
        raw = self._config.get("file_types", "document,spreadsheet,presentation")
        types = [t.strip().lower() for t in raw.split(",") if t.strip()]
        return types if types else ["document", "spreadsheet", "presentation"]

    def _build_mime_filters(self) -> List[str]:
        """Build list of MIME types to query based on configured file_types."""
        types = self._parse_file_types()
        mimes: List[str] = []
        for t in types:
            if t in FILE_TYPE_FILTERS:
                mimes.append(FILE_TYPE_FILTERS[t])
            elif t == "pdf":
                mimes.append("application/pdf")
            elif t == "text":
                mimes.append("text/plain")
        return mimes if mimes else None  # type: ignore[return-value]

    def _mime_short(self, mime_type: str) -> str:
        if mime_type in GOOGLE_EXPORT_MAP:
            return GOOGLE_EXPORT_MAP[mime_type][1]
        return DOWNLOADABLE_MIMES.get(mime_type, "file")

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Service account JSON not configured"}
        if pyjwt is None:
            return {"ok": False, "error": "PyJWT not installed — pip install PyJWT"}
        try:
            api = self._api()
            files = api.list_files(
                folder_id=self._config.get("folder_id") or None,
                max_files=1,
            )
            return {
                "ok": True,
                "message": f"Connected. Found {len(files)} file(s) in test query.",
                "service_account": json.loads(
                    self._config["service_account_json"]
                ).get("client_email", "unknown"),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r
        if pyjwt is None:
            r = SyncResult()
            r.errors.append("PyJWT not installed — pip install PyJWT")
            return r

        result = SyncResult()
        api = self._api()
        prefix = f"{self.name}/"
        folder_id = self._config.get("folder_id") or None
        max_files = int(self._config.get("max_files", 100))
        mime_filters = self._build_mime_filters()
        synced_keys: set[str] = set()

        try:
            files = api.list_files(folder_id=folder_id, mime_filters=mime_filters,
                                   max_files=max_files)
        except Exception as e:
            result.errors.append(f"Failed to list files: {e}")
            self._update_sync_stats(0)
            return result

        result.total_remote = len(files)

        for f in files:
            file_id = f["id"]
            file_name = f.get("name", "Untitled")
            mime_type = f.get("mimeType", "")
            key = f"{prefix}{file_id}"
            synced_keys.add(key)

            content = self._fetch_content(api, file_id, file_name, mime_type, result)
            if content is None:
                result.skipped += 1
                continue

            mime_short = self._mime_short(mime_type)
            tags = [self.name, file_name, mime_short]
            meta_extra = {
                "file_id": file_id,
                "file_name": file_name,
                "mime_type": mime_type,
                "modified_time": f.get("modifiedTime", ""),
                "web_link": f.get("webViewLink", ""),
            }
            self._upsert(store, key, content, tags, meta_extra, result)

        # Cleanup deleted files
        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _fetch_content(self, api: _DriveAPI, file_id: str, file_name: str,
                       mime_type: str, result: SyncResult) -> Optional[str]:
        """Fetch file content: export Google Workspace files, download others."""
        try:
            if mime_type in GOOGLE_EXPORT_MAP:
                export_mime, _ = GOOGLE_EXPORT_MAP[mime_type]
                text = api.export_file(file_id, export_mime)
                return f"# {file_name}\n\n{text}" if text.strip() else None

            if mime_type in DOWNLOADABLE_MIMES:
                raw = api.download_file(file_id)
                text = raw.decode(errors="replace")
                return f"# {file_name}\n\n{text}" if text.strip() else None

        except Exception as e:
            result.errors.append(f"{file_name}: {e}")
        return None

    def _upsert(self, store: MemoryStore, key: str, content: str,
                tags: List[str], meta_extra: Dict[str, Any],
                result: SyncResult) -> None:
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
            existing.metadata.update(meta_extra)
            if ttl_sec:
                existing.metadata["ttl_seconds"] = ttl_sec
            existing.expires_at = expires_at
            existing.updated_at = time.time()
            store.set(existing, reset_ttl=False)
            result.updated += 1
        except KeyError:
            meta = {"source": self.name, "content_hash": content_hash}
            meta.update(meta_extra)
            if ttl_sec:
                meta["ttl_seconds"] = ttl_sec
            mem = Memory(key=key, value=content, tags=tags, metadata=meta,
                         expires_at=expires_at)
            store.set(mem)
            result.added += 1
