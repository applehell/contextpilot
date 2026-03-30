"""KeePass connector — sync notes, titles, URLs and group structure from .kdbx files.

SECURITY: This connector NEVER syncs passwords, usernames, or other credentials.
Only notes, titles, URLs, group paths, tags, and timestamps are extracted.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

try:
    from pykeepass import PyKeePass
    HAS_PYKEEPASS = True
except ImportError:
    HAS_PYKEEPASS = False


class KeePassConnector(ConnectorPlugin):
    name = "keepass"
    display_name = "KeePass"
    description = "Sync notes, titles, URLs and group structure from a KeePass database"
    icon = "KP"
    category = "Knowledge"
    setup_guide = (
        "Point to your .kdbx file. Requires pykeepass (pip install pykeepass). "
        "Only notes, titles, URLs and group names are synced - never passwords."
    )
    color = "#4e9a06"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("database_path", "Database path", placeholder="/path/to/database.kdbx", required=True),
            ConfigField("password", "Master password", type="password", required=True),
            ConfigField("key_file", "Key file path", placeholder="/path/to/keyfile (optional)"),
            ConfigField("group_filter", "Group filter", type="tags", placeholder="e.g. Notes, Bookmarks (empty = all)"),
        ]

    def test_connection(self) -> Dict[str, Any]:
        if not HAS_PYKEEPASS:
            return {"ok": False, "error": "pykeepass not installed. Run: pip install pykeepass"}

        db_path = self._config.get("database_path", "")
        if not db_path:
            return {"ok": False, "error": "Database path not set"}

        p = Path(db_path)
        if not p.is_file():
            return {"ok": False, "error": f"File not found: {db_path}"}

        password = self._config.get("password", "")
        key_file = self._config.get("key_file", "") or None

        try:
            kp = PyKeePass(str(p), password=password, keyfile=key_file)
            entry_count = len(kp.entries) if kp.entries else 0
            group_count = len(kp.groups) if kp.groups else 0
            return {"ok": True, "entries": entry_count, "groups": group_count, "database": str(p)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        result = SyncResult()

        if not HAS_PYKEEPASS:
            result.errors.append("pykeepass not installed. Run: pip install pykeepass")
            return result

        db_path = self._config.get("database_path", "")
        if not db_path or not Path(db_path).is_file():
            result.errors.append("Database file not found")
            return result

        password = self._config.get("password", "")
        key_file = self._config.get("key_file", "") or None
        group_filter = _parse_csv(self._config.get("group_filter", ""))

        try:
            kp = PyKeePass(str(db_path), password=password, keyfile=key_file)
        except Exception as e:
            result.errors.append(f"Failed to open database: {e}")
            return result

        prefix = f"{self.name}/"
        synced_keys = set()
        entries = kp.entries or []

        for entry in entries:
            try:
                group_path = _group_path(entry.group)

                if group_filter:
                    top_group = group_path.split("/")[0] if group_path else ""
                    if top_group and top_group.lower() not in [g.lower() for g in group_filter]:
                        continue

                title = entry.title or ""
                if not title:
                    result.skipped += 1
                    continue

                result.total_remote += 1

                url = entry.url or ""
                notes = entry.notes or ""
                ctime = _format_time(entry.ctime)
                mtime = _format_time(entry.mtime)
                entry_tags = list(entry.tags) if entry.tags else []

                content_parts = [f"# {title}"]
                if group_path:
                    content_parts.append(f"Group: {group_path}")
                if url:
                    content_parts.append(f"URL: {url}")
                content_parts.append(f"Created: {ctime}")
                if notes:
                    content_parts.append("")
                    content_parts.append(notes)

                full_content = "\n".join(content_parts)

                safe_group = group_path.replace("\\", "/") if group_path else "Root"
                key = f"{prefix}{safe_group}/{title}"
                synced_keys.add(key)

                content_hash = hashlib.sha256(full_content.encode()).hexdigest()[:16]

                mem_tags = [self.name]
                if group_path:
                    top = group_path.split("/")[0].lower()
                    if top:
                        mem_tags.append(top)
                for t in entry_tags:
                    tag = t.lower().strip()
                    if tag and tag not in mem_tags:
                        mem_tags.append(tag)

                try:
                    existing = store.get(key)
                    if existing.metadata.get("content_hash") == content_hash:
                        result.skipped += 1
                        continue
                    existing.value = full_content
                    existing.tags = mem_tags
                    existing.metadata["content_hash"] = content_hash
                    existing.metadata["modified"] = mtime
                    existing.updated_at = time.time()
                    expires = self._compute_expires_at()
                    if expires:
                        existing.expires_at = expires
                    store.set(existing)
                    result.updated += 1
                except KeyError:
                    mem = Memory(
                        key=key, value=full_content, tags=mem_tags,
                        metadata={
                            "source": self.name,
                            "content_hash": content_hash,
                            "group_path": group_path,
                            "url": url,
                            "created": ctime,
                            "modified": mtime,
                        },
                    )
                    expires = self._compute_expires_at()
                    if expires:
                        mem.expires_at = expires
                    store.set(mem)
                    result.added += 1

            except Exception as e:
                result.errors.append(f"Entry error: {e}")

        for m in store.list():
            if m.key.startswith(prefix) and m.key not in synced_keys:
                store.delete(m.key)
                result.removed += 1

        self._update_sync_stats(len(synced_keys))
        return result


def _parse_csv(val) -> List[str]:
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val.strip():
        return [t.strip() for t in val.split(",") if t.strip()]
    return []


def _group_path(group) -> str:
    if group is None:
        return ""
    parts = []
    current = group
    while current and current.name:
        if current.name != "Root" and current.name != current.parentgroup:
            parts.append(current.name)
        try:
            parent = current.parentgroup
            if parent is None or parent == current:
                break
            current = parent
        except Exception:
            break
    parts.reverse()
    return "/".join(parts)


def _format_time(dt) -> str:
    if dt is None:
        return ""
    try:
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(dt)
