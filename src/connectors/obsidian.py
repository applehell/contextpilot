"""Obsidian vault connector — sync markdown files with frontmatter parsing."""
from __future__ import annotations

import hashlib
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


class ObsidianConnector(ConnectorPlugin):
    name = "obsidian"
    display_name = "Obsidian Vault"
    description = "Sync markdown notes from an Obsidian vault"
    icon = "O"

    EXTENSIONS = {".md", ".markdown"}
    MAX_FILE_SIZE = 2 * 1024 * 1024

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("vault_path", "Vault path", placeholder="/path/to/vault", required=True),
            ConfigField("folder_filter", "Folder filter", type="tags", placeholder="e.g. notes, projects (empty = all)"),
            ConfigField("tag_filter", "Tag filter", type="tags", placeholder="e.g. important, work (empty = all)"),
        ]

    @property
    def configured(self) -> bool:
        path = self._config.get("vault_path", "")
        return bool(path and Path(path).is_dir())

    def test_connection(self) -> Dict[str, Any]:
        path = self._config.get("vault_path", "")
        if not path:
            return {"ok": False, "error": "Vault path not set"}
        vault = Path(path)
        if not vault.is_dir():
            return {"ok": False, "error": f"Directory not found: {path}"}
        md_files = list(vault.rglob("*.md"))
        return {"ok": True, "file_count": len(md_files), "vault": str(vault)}

    def sync(self, store: MemoryStore) -> SyncResult:
        if not self.configured:
            r = SyncResult()
            r.errors.append("Not configured")
            return r

        result = SyncResult()
        vault = Path(self._config["vault_path"])
        prefix = f"{self.name}/"
        folder_filter = _parse_csv(self._config.get("folder_filter", ""))
        tag_filter = _parse_csv(self._config.get("tag_filter", ""))

        synced_keys = set()

        for f in vault.rglob("*"):
            if not f.is_file() or f.suffix.lower() not in self.EXTENSIONS:
                continue
            if f.stat().st_size > self.MAX_FILE_SIZE:
                result.skipped += 1
                continue
            if f.name.startswith("."):
                continue

            rel = f.relative_to(vault)
            if folder_filter:
                top_folder = rel.parts[0] if len(rel.parts) > 1 else ""
                if top_folder and top_folder.lower() not in [ff.lower() for ff in folder_filter]:
                    continue

            try:
                raw = f.read_text(errors="replace")
            except Exception as e:
                result.errors.append(f"{rel}: {e}")
                continue

            frontmatter, content = _parse_frontmatter(raw)
            if not content.strip():
                result.skipped += 1
                continue

            note_tags = frontmatter.get("tags", [])
            if isinstance(note_tags, str):
                note_tags = [t.strip() for t in note_tags.split(",") if t.strip()]

            if tag_filter and not any(t.lower() in [tf.lower() for tf in tag_filter] for t in note_tags):
                continue

            result.total_remote += 1
            key = prefix + str(rel).replace("\\", "/")
            synced_keys.add(key)

            content_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
            mem_tags = [self.name] + [t.lower().replace("#", "") for t in note_tags]
            if len(rel.parts) > 1:
                mem_tags.append(rel.parts[0].lower())

            title = frontmatter.get("title", f.stem)
            full_content = f"# {title}\n\n{content}"

            try:
                existing = store.get(key)
                if existing.metadata.get("content_hash") == content_hash:
                    result.skipped += 1
                    continue
                existing.value = full_content
                existing.tags = mem_tags
                existing.metadata["content_hash"] = content_hash
                existing.metadata["modified"] = f.stat().st_mtime
                existing.updated_at = time.time()
                store.set(existing)
                result.updated += 1
            except KeyError:
                mem = Memory(
                    key=key, value=full_content, tags=mem_tags,
                    metadata={
                        "source": self.name,
                        "content_hash": content_hash,
                        "file_path": str(f),
                        "relative_path": str(rel),
                        "modified": f.stat().st_mtime,
                        "frontmatter": frontmatter,
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


def _parse_csv(val) -> List[str]:
    if isinstance(val, list):
        return val
    if isinstance(val, str) and val.strip():
        return [t.strip() for t in val.split(",") if t.strip()]
    return []


def _parse_frontmatter(text: str) -> tuple:
    """Extract YAML frontmatter and return (dict, content)."""
    if not text.startswith("---"):
        return {}, text

    end = text.find("---", 3)
    if end < 0:
        return {}, text

    fm_text = text[3:end].strip()
    content = text[end + 3:].strip()

    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'") for v in val[1:-1].split(",") if v.strip()]
            fm[key] = val

    return fm, content
