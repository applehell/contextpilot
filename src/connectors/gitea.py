"""Gitea connector — sync repo READMEs, issues, and wiki pages."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import urllib.error
import base64
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


class _GiteaAPI:
    def __init__(self, url: str, token: str) -> None:
        self.base_url = url.rstrip("/")
        self.token = token

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(f"{self.base_url}/api/v1{path}", headers={
            "Authorization": f"token {self.token}",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    def repos(self) -> List[Dict]:
        return self._get("/user/repos?limit=50")

    def readme(self, owner: str, repo: str) -> Optional[str]:
        try:
            data = self._get(f"/repos/{owner}/{repo}/raw/README.md")
            return data if isinstance(data, str) else None
        except Exception:
            try:
                data = self._get(f"/repos/{owner}/{repo}/contents/README.md")
                if isinstance(data, dict) and data.get("content"):
                    return base64.b64decode(data["content"]).decode(errors="replace")
            except Exception:
                pass
        return None

    def issues(self, owner: str, repo: str, state: str = "open") -> List[Dict]:
        try:
            return self._get(f"/repos/{owner}/{repo}/issues?state={state}&limit=50&type=issues")
        except Exception:
            return []


class GiteaConnector(ConnectorPlugin):
    name = "gitea"
    display_name = "Gitea"
    description = "Sync repo READMEs and issues from Gitea"
    icon = "G"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("url", "URL", placeholder="http://<server-ip>:3300", required=True),
            ConfigField("token", "API Token", type="password", placeholder="Settings → Applications → Generate Token", required=True),
            ConfigField("sync_items", "Sync items", type="tags", placeholder="readmes, issues (empty = all)", default="readmes, issues"),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("url") and self._config.get("token"))

    def _api(self) -> _GiteaAPI:
        return _GiteaAPI(self._config["url"], self._config["token"])

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        try:
            api = self._api()
            repos = api.repos()
            return {"ok": True, "repo_count": len(repos)}
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

        sync_items = self._config.get("sync_items", "readmes, issues")
        if isinstance(sync_items, str):
            items = [t.strip().lower() for t in sync_items.split(",") if t.strip()]
        else:
            items = [t.lower() for t in sync_items]
        if not items:
            items = ["readmes", "issues"]

        synced_keys = set()

        try:
            repos = api.repos()
        except Exception as e:
            result.errors.append(f"API error: {e}")
            return result

        for repo in repos:
            owner = repo["owner"]["login"]
            repo_name = repo["name"]
            full_name = repo.get("full_name", f"{owner}/{repo_name}")

            if "readmes" in items:
                readme = api.readme(owner, repo_name)
                if readme and readme.strip():
                    key = f"{prefix}{full_name}/README"
                    synced_keys.add(key)
                    result.total_remote += 1
                    self._upsert(store, key, f"# {full_name}\n\n{readme}",
                                 [self.name, "readme", repo_name], repo, result)

            if "issues" in items:
                issues = api.issues(owner, repo_name)
                for issue in issues:
                    key = f"{prefix}{full_name}/issue/{issue['number']}"
                    synced_keys.add(key)
                    result.total_remote += 1
                    content = f"# [{full_name}] #{issue['number']}: {issue['title']}\n\n{issue.get('body', '') or ''}"
                    labels = [l["name"].lower() for l in issue.get("labels", [])]
                    self._upsert(store, key, content,
                                 [self.name, "issue", repo_name] + labels, repo, result)

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _upsert(self, store, key, content, tags, repo, result):
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        try:
            existing = store.get(key)
            if existing.metadata.get("content_hash") == content_hash:
                result.skipped += 1
                return
            existing.value = content
            existing.tags = tags
            existing.metadata["content_hash"] = content_hash
            existing.updated_at = time.time()
            store.set(existing)
            result.updated += 1
        except KeyError:
            mem = Memory(key=key, value=content, tags=tags, metadata={
                "source": self.name, "content_hash": content_hash,
                "repo": repo.get("full_name", ""),
            })
            store.set(mem)
            result.added += 1
