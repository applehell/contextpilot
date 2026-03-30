"""Gitea connector — sync repos, issues, packages, releases, and wiki pages."""
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


ALL_SYNC_ITEMS = ["readmes", "issues", "packages", "releases", "wikis", "repos"]


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

    def _get_raw(self, path: str) -> str:
        req = urllib.request.Request(f"{self.base_url}/api/v1{path}", headers={
            "Authorization": f"token {self.token}",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode(errors="replace")

    def repos(self) -> List[Dict]:
        return self._get("/user/repos?limit=50")

    def readme(self, owner: str, repo: str) -> Optional[str]:
        try:
            return self._get_raw(f"/repos/{owner}/{repo}/raw/README.md")
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

    def releases(self, owner: str, repo: str) -> List[Dict]:
        try:
            return self._get(f"/repos/{owner}/{repo}/releases?limit=50")
        except Exception:
            return []

    def wiki_pages(self, owner: str, repo: str) -> List[Dict]:
        try:
            return self._get(f"/repos/{owner}/{repo}/wiki/pages?limit=50")
        except Exception:
            return []

    def wiki_page(self, owner: str, repo: str, slug: str) -> Optional[Dict]:
        try:
            return self._get(f"/repos/{owner}/{repo}/wiki/page/{slug}")
        except Exception:
            return None

    def packages(self, owner: str) -> List[Dict]:
        try:
            return self._get(f"/packages/{owner}?limit=50")
        except Exception:
            return []

    def package_files(self, owner: str, pkg_type: str, name: str, version: str) -> List[Dict]:
        try:
            return self._get(f"/packages/{owner}/{pkg_type}/{name}/{version}/files")
        except Exception:
            return []


class GiteaConnector(ConnectorPlugin):
    name = "gitea"
    display_name = "Gitea"
    description = "Sync repos, issues, packages, releases, and wikis from Gitea"
    icon = "G"
    category = "Development"
    setup_guide = "Create an API token at User Settings > Applications in your Gitea instance."
    color = "#609926"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("url", "URL", placeholder="http://<server-ip>:3300", required=True),
            ConfigField("token", "API Token", type="password", placeholder="Settings > Applications > Generate Token", required=True),
            ConfigField("sync_items", "Sync items", type="tags",
                        placeholder="readmes, issues, packages, releases, wikis, repos (empty = all)",
                        default=", ".join(ALL_SYNC_ITEMS)),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._config.get("url") and self._config.get("token"))

    def _api(self) -> _GiteaAPI:
        return _GiteaAPI(self._config["url"], self._config["token"])

    def _parse_sync_items(self) -> List[str]:
        raw = self._config.get("sync_items", "")
        if isinstance(raw, str):
            items = [t.strip().lower() for t in raw.split(",") if t.strip()]
        else:
            items = [t.lower() for t in raw]
        return items if items else list(ALL_SYNC_ITEMS)

    def test_connection(self) -> Dict[str, Any]:
        if not self.configured:
            return {"ok": False, "error": "Not configured"}
        try:
            api = self._api()
            repos = api.repos()
            owner = self._config.get("url", "").rstrip("/").split("/")[-1] or "unknown"
            pkgs = []
            if repos:
                owner_login = repos[0]["owner"]["login"]
                pkgs = api.packages(owner_login)
            return {"ok": True, "repo_count": len(repos), "package_count": len(pkgs)}
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
        synced_keys: set[str] = set()

        try:
            repos = api.repos()
        except Exception as e:
            result.errors.append(f"API error: {e}")
            return result

        owner_login = repos[0]["owner"]["login"] if repos else None

        for repo in repos:
            owner = repo["owner"]["login"]
            repo_name = repo["name"]
            full_name = repo.get("full_name", f"{owner}/{repo_name}")

            # --- Repo metadata ---
            if "repos" in items:
                key = f"{prefix}{full_name}/meta"
                synced_keys.add(key)
                result.total_remote += 1
                lines = [f"# {full_name}"]
                if repo.get("description"):
                    lines.append(f"\n{repo['description']}")
                lines.append(f"\n**Language:** {repo.get('language') or 'n/a'}")
                lines.append(f"**Stars:** {repo.get('stars_count', 0)} | **Forks:** {repo.get('forks_count', 0)} | **Size:** {repo.get('size', 0)} KB")
                lines.append(f"**Default branch:** {repo.get('default_branch', 'main')}")
                lines.append(f"**Created:** {repo.get('created_at', '')[:10]} | **Updated:** {repo.get('updated_at', '')[:10]}")
                if repo.get("topics"):
                    lines.append(f"**Topics:** {', '.join(repo['topics'])}")
                lines.append(f"**Clone:** `{repo.get('clone_url', '')}`")
                if repo.get("has_wiki"):
                    lines.append("**Wiki:** enabled")
                if repo.get("has_packages"):
                    lines.append("**Packages:** enabled")
                content = "\n".join(lines)
                tags = [self.name, "repo", repo_name] + (repo.get("topics") or [])
                self._upsert(store, key, content, tags, {"full_name": full_name}, result)

            # --- READMEs ---
            if "readmes" in items:
                readme = api.readme(owner, repo_name)
                if readme and readme.strip():
                    key = f"{prefix}{full_name}/README"
                    synced_keys.add(key)
                    result.total_remote += 1
                    self._upsert(store, key, f"# {full_name}\n\n{readme}",
                                 [self.name, "readme", repo_name], {"full_name": full_name}, result)

            # --- Issues ---
            if "issues" in items:
                issues = api.issues(owner, repo_name)
                for issue in issues:
                    key = f"{prefix}{full_name}/issue/{issue['number']}"
                    synced_keys.add(key)
                    result.total_remote += 1
                    content = f"# [{full_name}] #{issue['number']}: {issue['title']}\n\n{issue.get('body', '') or ''}"
                    labels = [l["name"].lower() for l in issue.get("labels", [])]
                    self._upsert(store, key, content,
                                 [self.name, "issue", repo_name] + labels, {"full_name": full_name}, result)

            # --- Releases ---
            if "releases" in items:
                releases = api.releases(owner, repo_name)
                for rel in releases:
                    tag = rel.get("tag_name", "unknown")
                    key = f"{prefix}{full_name}/release/{tag}"
                    synced_keys.add(key)
                    result.total_remote += 1
                    lines = [f"# [{full_name}] Release {tag}: {rel.get('name', tag)}"]
                    if rel.get("prerelease"):
                        lines.append("**Pre-release**")
                    lines.append(f"**Published:** {(rel.get('published_at') or rel.get('created_at', ''))[:10]}")
                    if rel.get("body"):
                        lines.append(f"\n{rel['body']}")
                    assets = rel.get("assets", [])
                    if assets:
                        lines.append("\n**Assets:**")
                        for a in assets:
                            size_mb = (a.get("size", 0) / 1048576)
                            lines.append(f"- {a['name']} ({size_mb:.1f} MB, {a.get('download_count', 0)} downloads)")
                    content = "\n".join(lines)
                    self._upsert(store, key, content,
                                 [self.name, "release", repo_name, tag], {"full_name": full_name}, result)

            # --- Wiki ---
            if "wikis" in items:
                pages = api.wiki_pages(owner, repo_name)
                for page_info in pages:
                    slug = page_info.get("sub_url") or page_info.get("title", "").replace(" ", "-")
                    if not slug:
                        continue
                    page = api.wiki_page(owner, repo_name, slug)
                    if not page:
                        continue
                    key = f"{prefix}{full_name}/wiki/{slug}"
                    synced_keys.add(key)
                    result.total_remote += 1
                    title = page.get("title", slug)
                    content_text = page.get("content_base64", "")
                    if content_text:
                        try:
                            content_text = base64.b64decode(content_text).decode(errors="replace")
                        except Exception:
                            content_text = ""
                    if not content_text:
                        content_text = page.get("content", "")
                    content = f"# [{full_name}] Wiki: {title}\n\n{content_text}"
                    self._upsert(store, key, content,
                                 [self.name, "wiki", repo_name], {"full_name": full_name}, result)

        # --- Packages / Containers ---
        if "packages" in items and owner_login:
            try:
                packages = api.packages(owner_login)
            except Exception as e:
                result.errors.append(f"Packages API error: {e}")
                packages = []

            # Group versions by package name+type
            pkg_groups: dict[str, list[Dict]] = {}
            for pkg in packages:
                group_key = f"{pkg.get('type', 'unknown')}/{pkg['name']}"
                pkg_groups.setdefault(group_key, []).append(pkg)

            for group_key, versions in pkg_groups.items():
                pkg_type, pkg_name = group_key.split("/", 1)
                key = f"{prefix}{owner_login}/package/{pkg_type}/{pkg_name}"
                synced_keys.add(key)
                result.total_remote += 1

                # Filter out sha256 digest versions for display
                display_versions = []
                digest_versions = []
                for v in versions:
                    ver = v.get("version", "?")
                    if ver.startswith("sha256:"):
                        digest_versions.append(ver[:19] + "...")
                    else:
                        display_versions.append(ver)

                lines = [f"# Package: {pkg_name} ({pkg_type})"]
                lines.append(f"**Owner:** {owner_login}")
                lines.append(f"**Type:** {pkg_type}")
                lines.append(f"**Tags:** {', '.join(display_versions) or 'none'}")
                if digest_versions:
                    lines.append(f"**Digests:** {len(digest_versions)} manifest(s)")
                lines.append(f"**Total versions:** {len(versions)}")

                latest = max(versions, key=lambda v: v.get("created_at", ""))
                lines.append(f"**Latest push:** {latest.get('created_at', '')[:19].replace('T', ' ')}")

                if pkg_type == "container":
                    registry_url = self._config.get("url", "").rstrip("/")
                    lines.append(f"\n**Pull:**\n```\ndocker pull {registry_url.replace('http://', '').replace('https://', '')}/{owner_login}/{pkg_name}:latest\n```")

                html_url = latest.get("html_url", "")
                if html_url:
                    lines.append(f"**URL:** {html_url}")

                # Fetch file info for latest named version
                if display_versions:
                    latest_named = next((v for v in versions if v.get("version") == display_versions[0]), None)
                    if latest_named:
                        files = api.package_files(owner_login, pkg_type, pkg_name, latest_named["version"])
                        if files:
                            lines.append("\n**Files:**")
                            for f in files[:10]:
                                size_mb = f.get("Size", f.get("size", 0)) / 1048576
                                fname = f.get("name", f.get("Name", "?"))
                                lines.append(f"- {fname} ({size_mb:.1f} MB)")

                content = "\n".join(lines)
                tags = [self.name, "package", pkg_type, pkg_name]
                self._upsert(store, key, content, tags, {"full_name": f"{owner_login}/{pkg_name}"}, result)

        # --- Cleanup removed items ---
        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result

    def _upsert(self, store, key, content, tags, meta_extra, result):
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
            meta = {"source": self.name, "content_hash": content_hash, **meta_extra}
            if ttl_sec:
                meta["ttl_seconds"] = ttl_sec
            mem = Memory(key=key, value=content, tags=tags, metadata=meta,
                         expires_at=expires_at)
            store.set(mem)
            result.added += 1
