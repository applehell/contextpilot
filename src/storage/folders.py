"""Folder source indexer — map external folders into the memory store."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .memory import Memory, MemoryStore

import os

_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
FOLDERS_CONFIG = _DATA_DIR / "folders.json"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".json", ".yaml", ".yml", ".toml",
    ".csv", ".tsv",
    ".py", ".sh", ".bash", ".zsh", ".js", ".ts", ".html", ".css",
    ".conf", ".cfg", ".ini", ".env", ".properties",
    ".xml", ".svg",
    ".sql",
    ".log",
    ".dockerfile",
}

PDF_EXTENSION = ".pdf"

MAX_FILE_SIZE = 2 * 1024 * 1024  # 2 MB per file


@dataclass
class FolderSource:
    name: str
    path: str
    extensions: List[str] = field(default_factory=list)
    recursive: bool = True
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_scan: Optional[float] = None
    indexed_files: int = 0
    description: str = ""


@dataclass
class IndexResult:
    added: int = 0
    updated: int = 0
    removed: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)


class FolderManager:

    def __init__(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._config: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if FOLDERS_CONFIG.exists():
            return json.loads(FOLDERS_CONFIG.read_text())
        return {"sources": {}}

    def _save(self) -> None:
        FOLDERS_CONFIG.write_text(json.dumps(self._config, indent=2))

    def list(self) -> List[FolderSource]:
        result = []
        for name, data in self._config["sources"].items():
            result.append(FolderSource(
                name=name,
                path=data["path"],
                extensions=data.get("extensions", []),
                recursive=data.get("recursive", True),
                enabled=data.get("enabled", True),
                created_at=data.get("created_at", 0),
                last_scan=data.get("last_scan"),
                indexed_files=data.get("indexed_files", 0),
                description=data.get("description", ""),
            ))
        return sorted(result, key=lambda s: s.name)

    def get(self, name: str) -> Optional[FolderSource]:
        sources = {s.name: s for s in self.list()}
        return sources.get(name)

    def add(self, name: str, path: str, extensions: Optional[List[str]] = None,
            recursive: bool = True, description: str = "") -> FolderSource:
        if name in self._config["sources"]:
            raise ValueError(f"Source '{name}' already exists.")
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("Name must be alphanumeric (-, _ allowed).")

        p = Path(path)
        if not p.is_dir():
            raise ValueError(f"Path does not exist or is not a directory: {path}")

        data = {
            "path": str(p.resolve()),
            "extensions": extensions or [],
            "recursive": recursive,
            "enabled": True,
            "created_at": time.time(),
            "last_scan": None,
            "indexed_files": 0,
            "description": description,
        }
        self._config["sources"][name] = data
        self._save()
        return FolderSource(name=name, **data)

    def update(self, name: str, **kwargs) -> FolderSource:
        if name not in self._config["sources"]:
            raise KeyError(f"Source '{name}' not found.")
        for key in ("path", "extensions", "recursive", "enabled", "description"):
            if key in kwargs:
                self._config["sources"][name][key] = kwargs[key]
        self._save()
        return self.get(name)

    def remove(self, name: str) -> None:
        if name not in self._config["sources"]:
            raise KeyError(f"Source '{name}' not found.")
        del self._config["sources"][name]
        self._save()

    def scan(self, name: str, store: MemoryStore) -> IndexResult:
        source = self.get(name)
        if not source:
            raise KeyError(f"Source '{name}' not found.")

        result = IndexResult()
        folder = Path(source.path)
        if not folder.is_dir():
            result.errors.append(f"Directory not found: {source.path}")
            return result

        allowed_ext = set(source.extensions) if source.extensions else None
        prefix = f"folder/{source.name}/"

        # Collect files
        files: List[Path] = []
        pattern = "**/*" if source.recursive else "*"
        for f in folder.glob(pattern):
            if not f.is_file():
                continue
            ext = f.suffix.lower()
            if allowed_ext and ext not in allowed_ext:
                continue
            if not allowed_ext and ext not in TEXT_EXTENSIONS and ext != PDF_EXTENSION:
                continue
            if f.stat().st_size > MAX_FILE_SIZE:
                result.skipped += 1
                continue
            files.append(f)

        # Build set of expected keys
        indexed_keys = set()

        for f in files:
            rel = f.relative_to(folder)
            key = prefix + str(rel)
            indexed_keys.add(key)

            try:
                content = _read_file(f)
                if not content or not content.strip():
                    result.skipped += 1
                    continue
            except Exception as e:
                result.errors.append(f"{rel}: {e}")
                continue

            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            try:
                existing = store.get(key)
                old_hash = existing.metadata.get("content_hash", "")
                if old_hash == content_hash:
                    result.skipped += 1
                    continue
                # Update
                existing.value = content
                existing.metadata["content_hash"] = content_hash
                existing.metadata["file_size"] = f.stat().st_size
                existing.metadata["modified"] = f.stat().st_mtime
                existing.updated_at = time.time()
                store.set(existing)
                result.updated += 1
            except KeyError:
                # New file
                mem = Memory(
                    key=key,
                    value=content,
                    tags=["folder", source.name, f.suffix.lstrip(".")],
                    metadata={
                        "source": "folder",
                        "folder_source": source.name,
                        "file_path": str(f),
                        "relative_path": str(rel),
                        "content_hash": content_hash,
                        "file_size": f.stat().st_size,
                        "modified": f.stat().st_mtime,
                    },
                )
                store.set(mem)
                result.added += 1

        # Remove memories for deleted files
        existing_memories = store.list()
        for m in existing_memories:
            if m.key.startswith(prefix) and m.key not in indexed_keys:
                store.delete(m.key)
                result.removed += 1

        # Update source metadata
        self._config["sources"][name]["last_scan"] = time.time()
        self._config["sources"][name]["indexed_files"] = len(indexed_keys)
        self._save()

        return result

    def scan_all(self, store: MemoryStore) -> Dict[str, IndexResult]:
        results = {}
        for source in self.list():
            if source.enabled:
                results[source.name] = self.scan(source.name, store)
        return results

    def purge(self, name: str, store: MemoryStore) -> int:
        prefix = f"folder/{name}/"
        count = 0
        for m in store.list():
            if m.key.startswith(prefix):
                store.delete(m.key)
                count += 1
        return count


def _read_file(path: Path) -> str:
    ext = path.suffix.lower()

    if ext == PDF_EXTENSION:
        return _read_pdf(path)

    if ext in TEXT_EXTENSIONS or not ext:
        return path.read_text(errors="replace")

    return ""


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return f"[PDF file — install pypdf to extract text: {path.name}]"

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n\n".join(pages)
