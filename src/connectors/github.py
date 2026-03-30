"""GitHub connector — track public repos, releases, READMEs, and activity."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


ALL_SYNC_ITEMS = ["readmes", "releases", "repos", "issues"]


class _GitHubAPI:
    BASE = "https://api.github.com"

    def __init__(self, token: str = "") -> None:
        self.token = token

    def _get(self, path: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ContextPilot/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"{self.BASE}{path}", headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())

    def _get_raw(self, url: str) -> str:
        headers = {"User-Agent": "ContextPilot/1.0"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read().decode(errors="replace")

    def repo(self, owner: str, name: str) -> Dict:
        return self._get(f"/repos/{owner}/{name}")

    def readme(self, owner: str, name: str) -> Optional[str]:
        try:
            data = self._get(f"/repos/{owner}/{name}/readme")
            if data.get("download_url"):
                return self._get_raw(data["download_url"])
            if data.get("content"):
                import base64
                return base64.b64decode(data["content"]).decode(errors="replace")
        except Exception:
            pass
        return None

    def releases(self, owner: str, name: str, limit: int = 10) -> List[Dict]:
        try:
            return self._get(f"/repos/{owner}/{name}/releases?per_page={limit}")
        except Exception:
            return []

    def issues(self, owner: str, name: str, state: str = "open", limit: int = 30) -> List[Dict]:
        try:
            return self._get(f"/repos/{owner}/{name}/issues?state={state}&per_page={limit}&sort=updated")
        except Exception:
            return []

    def rate_limit(self) -> Dict:
        try:
            return self._get("/rate_limit")
        except Exception:
            return {}


class GitHubConnector(ConnectorPlugin):
    name = "github"
    display_name = "GitHub"
    description = "Track public repos — releases, READMEs, issues, and metadata"
    icon = "GH"
    category = "Development"
    setup_guide = "Create a Personal Access Token at GitHub > Settings > Developer Settings > Tokens (optional for public repos)."
    color = "#333"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("token", "Personal Access Token", type="password",
                        placeholder="Optional — increases rate limit from 60 to 5000 req/h"),
            ConfigField("repos", "Repositories to track", type="text",
                        placeholder="owner/repo, owner/repo2 (comma-separated)",
                        required=True),
            ConfigField("sync_items", "Sync items", type="tags",
                        placeholder="readmes, releases, repos, issues (empty = all)",
                        default=", ".join(ALL_SYNC_ITEMS)),
            ConfigField("release_limit", "Releases per repo", type="number",
                        placeholder="10", default=10),
            ConfigField("issue_limit", "Issues per repo", type="number",
                        placeholder="20", default=20),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("repos"))

    def _api(self) -> _GitHubAPI:
        return _GitHubAPI(self._config.get("token", ""))

    def _parse_repos(self) -> List[tuple[str, str]]:
        raw = self._config.get("repos", "")
        result = []
        for entry in raw.split(","):
            entry = entry.strip().strip("/")
            if "/" in entry:
                parts = entry.split("/")
                owner = parts[-2]
                name = parts[-1]
                result.append((owner, name))
        return result

    def _parse_sync_items(self) -> List[str]:
        raw = self._config.get("sync_items", "")
        if isinstance(raw, str):
            items = [t.strip().lower() for t in raw.split(",") if t.strip()]
        else:
            items = [t.lower() for t in raw]
        return items if items else list(ALL_SYNC_ITEMS)

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "No repositories configured"}
        try:
            api = self._api()
            repos = self._parse_repos()
            accessible = []
            errors = []
            for owner, name in repos:
                try:
                    r = api.repo(owner, name)
                    accessible.append(r.get("full_name", f"{owner}/{name}"))
                except Exception as e:
                    errors.append(f"{owner}/{name}: {e}")

            rl = api.rate_limit()
            remaining = rl.get("rate", {}).get("remaining", "?")

            result = {"ok": len(accessible) > 0, "repos": accessible, "rate_remaining": remaining}
            if errors:
                result["errors"] = errors
            return result
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
        items = self._parse_sync_items()
        repos = self._parse_repos()
        release_limit = int(self._config.get("release_limit", 10))
        issue_limit = int(self._config.get("issue_limit", 20))
        synced_keys: set[str] = set()

        for owner, name in repos:
            full_name = f"{owner}/{name}"

            try:
                repo_data = api.repo(owner, name)
            except Exception as e:
                result.errors.append(f"{full_name}: {e}")
                continue

            # --- Repo metadata ---
            if "repos" in items:
                key = f"{prefix}{full_name}/meta"
                synced_keys.add(key)
                result.total_remote += 1

                lines = [f"# {full_name}"]
                if repo_data.get("description"):
                    lines.append(f"\n{repo_data['description']}")
                if repo_data.get("homepage"):
                    lines.append(f"**Homepage:** {repo_data['homepage']}")
                lines.append(f"**Language:** {repo_data.get('language') or 'n/a'}")
                lines.append(f"**Stars:** {repo_data.get('stargazers_count', 0):,} | "
                             f"**Forks:** {repo_data.get('forks_count', 0):,} | "
                             f"**Open Issues:** {repo_data.get('open_issues_count', 0):,}")
                lines.append(f"**Default branch:** {repo_data.get('default_branch', 'main')}")
                lines.append(f"**Created:** {(repo_data.get('created_at') or '')[:10]} | "
                             f"**Updated:** {(repo_data.get('updated_at') or '')[:10]} | "
                             f"**Pushed:** {(repo_data.get('pushed_at') or '')[:10]}")
                topics = repo_data.get("topics") or []
                if topics:
                    lines.append(f"**Topics:** {', '.join(topics)}")
                license_info = repo_data.get("license")
                if license_info and license_info.get("spdx_id"):
                    lines.append(f"**License:** {license_info['spdx_id']}")
                lines.append(f"**URL:** {repo_data.get('html_url', '')}")

                content = "\n".join(lines)
                tags = [self.name, "repo", name] + topics
                self._upsert(store, key, content, tags, full_name, result)

            # --- README ---
            if "readmes" in items:
                readme = api.readme(owner, name)
                if readme and readme.strip():
                    key = f"{prefix}{full_name}/README"
                    synced_keys.add(key)
                    result.total_remote += 1
                    self._upsert(store, key, f"# {full_name}\n\n{readme}",
                                 [self.name, "readme", name], full_name, result)

            # --- Releases ---
            if "releases" in items:
                releases = api.releases(owner, name, limit=release_limit)
                for rel in releases:
                    tag = rel.get("tag_name", "unknown")
                    key = f"{prefix}{full_name}/release/{tag}"
                    synced_keys.add(key)
                    result.total_remote += 1

                    lines = [f"# [{full_name}] Release {tag}"]
                    rel_name = rel.get("name") or tag
                    if rel_name != tag:
                        lines[0] += f": {rel_name}"
                    if rel.get("prerelease"):
                        lines.append("**Pre-release**")
                    if rel.get("draft"):
                        lines.append("**Draft**")
                    published = rel.get("published_at") or rel.get("created_at", "")
                    lines.append(f"**Published:** {published[:10]}")
                    author = rel.get("author", {}).get("login", "")
                    if author:
                        lines.append(f"**Author:** {author}")
                    if rel.get("body"):
                        lines.append(f"\n{rel['body']}")
                    assets = rel.get("assets", [])
                    if assets:
                        lines.append("\n**Assets:**")
                        for a in assets[:15]:
                            size_mb = a.get("size", 0) / 1048576
                            dl = a.get("download_count", 0)
                            lines.append(f"- [{a['name']}]({a.get('browser_download_url', '')}) "
                                         f"({size_mb:.1f} MB, {dl:,} downloads)")
                    lines.append(f"\n**URL:** {rel.get('html_url', '')}")

                    content = "\n".join(lines)
                    self._upsert(store, key, content,
                                 [self.name, "release", name, tag], full_name, result)

            # --- Issues ---
            if "issues" in items:
                all_issues = api.issues(owner, name, limit=issue_limit)
                # GitHub returns PRs in the issues endpoint — filter them out
                issues_only = [i for i in all_issues if "pull_request" not in i]
                for issue in issues_only:
                    key = f"{prefix}{full_name}/issue/{issue['number']}"
                    synced_keys.add(key)
                    result.total_remote += 1

                    lines = [f"# [{full_name}] #{issue['number']}: {issue['title']}"]
                    lines.append(f"**State:** {issue.get('state', 'open')} | "
                                 f"**Created:** {(issue.get('created_at') or '')[:10]} | "
                                 f"**Updated:** {(issue.get('updated_at') or '')[:10]}")
                    author = issue.get("user", {}).get("login", "")
                    if author:
                        lines.append(f"**Author:** {author}")
                    labels = [l["name"] for l in issue.get("labels", [])]
                    if labels:
                        lines.append(f"**Labels:** {', '.join(labels)}")
                    if issue.get("body"):
                        lines.append(f"\n{issue['body']}")
                    lines.append(f"\n**URL:** {issue.get('html_url', '')}")

                    content = "\n".join(lines)
                    tag_labels = [l.lower().replace(" ", "-") for l in labels]
                    self._upsert(store, key, content,
                                 [self.name, "issue", name] + tag_labels, full_name, result)

        # --- Cleanup removed items ---
        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _upsert(self, store, key, content, tags, full_name, result):
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
            meta = {"source": self.name, "content_hash": content_hash, "full_name": full_name}
            if ttl_sec:
                meta["ttl_seconds"] = ttl_sec
            mem = Memory(key=key, value=content, tags=tags, metadata=meta,
                         expires_at=expires_at)
            store.set(mem)
            result.added += 1
