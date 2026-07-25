"""Sleep cycle — autonomous nightly memory consolidation.

Runs once per day (after a configurable local hour) via the SyncScheduler,
for every profile:

- **Episodic consolidation** — distills ``episodic`` memories older than
  ``episodic_age_days`` into per-topic monthly digest memories. Originals stay
  in place, are linked to their digest and skipped on later runs.
- **Relation detection** — refreshes auto-detected knowledge-graph edges.
- **Duplicates** — reports duplicate groups; optional ``auto_merge`` (off by
  default) folds near-identical unpinned groups into one record.
- **Contradiction & confidence report** — surfaces conflicting and
  low-confidence memories without touching them.

Config-gated per profile (``sleep.json`` in the profile dir); defaults are
additive and non-destructive.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..storage.db import Database
from ..storage.memory import Memory, MemoryStore
from ..storage.relations import RelationStore
from .consolidation import confidence_score, find_contradictions, merge_group
from .dependency_detector import detect_dependencies
from .duplicates import find_duplicates
from .events import EventBus

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": True,
    "hour": 3,
    "detect_relations": True,
    "auto_merge": False,
    "merge_threshold": 0.9,
    "episodic_enabled": True,
    "episodic_age_days": 14,
    "max_memories": 5000,
    "keep_reports": 14,
}

CONFIG_FILE = "sleep.json"
REPORTS_FILE = "sleep_reports.json"
STATE_FILE = "sleep_state.json"

DIGEST_PREFIX = "digest/"

# O(n²)/output guards for a single cycle
MAX_CONTRADICTIONS = 200
MAX_AUTO_RELATIONS = 5000

# One sleep run at a time per process — concurrent runs race on
# digest read-modify-write and duplicate the O(n²) work.
_RUN_LOCK = threading.Lock()


def _clamp_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    cfg["hour"] = min(23, max(0, int(cfg["hour"])))
    cfg["episodic_age_days"] = max(0, int(cfg["episodic_age_days"]))
    cfg["max_memories"] = max(1, int(cfg["max_memories"]))
    cfg["keep_reports"] = min(100, max(1, int(cfg["keep_reports"])))
    cfg["merge_threshold"] = min(1.0, max(0.6, float(cfg["merge_threshold"])))
    return cfg


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        tmp.replace(path)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _data_dir() -> Path:
    from ..storage.profiles import _DATA_DIR
    return _DATA_DIR


def load_config(profile_dir: Optional[Path] = None) -> Dict[str, Any]:
    path = (profile_dir or _data_dir()) / CONFIG_FILE
    cfg = dict(DEFAULT_CONFIG)
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
            cfg = _clamp_config(cfg)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            cfg = dict(DEFAULT_CONFIG)
    return cfg


def save_config(profile_dir: Optional[Path], updates: Dict[str, Any]) -> Dict[str, Any]:
    profile_dir = profile_dir or _data_dir()
    cfg = load_config(profile_dir)
    for k, v in updates.items():
        if k not in DEFAULT_CONFIG:
            continue
        default = DEFAULT_CONFIG[k]
        if isinstance(default, bool):
            cfg[k] = bool(v)
        elif isinstance(default, int):
            cfg[k] = int(v)
        elif isinstance(default, float):
            cfg[k] = float(v)
        else:
            cfg[k] = v
    cfg = _clamp_config(cfg)
    _atomic_write(profile_dir / CONFIG_FILE, json.dumps(cfg, indent=2))
    return cfg


def load_state() -> Dict[str, Any]:
    path = _data_dir() / STATE_FILE
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    _atomic_write(_data_dir() / STATE_FILE, json.dumps(state, indent=2))


def load_reports(profile_dir: Optional[Path] = None, limit: int = 10) -> List[Dict[str, Any]]:
    path = (profile_dir or _data_dir()) / REPORTS_FILE
    if not path.exists():
        return []
    try:
        reports = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return reports[:limit] if isinstance(reports, list) else []


def _save_report(profile_dir: Path, report: Dict[str, Any], keep: int) -> None:
    keep = max(1, keep)
    reports = load_reports(profile_dir, limit=keep)
    reports.insert(0, report)
    _atomic_write(profile_dir / REPORTS_FILE, json.dumps(reports[:keep], indent=2))


def sleep_due(now: Optional[float] = None) -> bool:
    """True when the nightly run for today has not happened yet and the
    configured hour has passed.

    The *schedule* (hour, once per day) is global and read from the default
    profile's config; whether an individual profile participates is that
    profile's own ``enabled`` flag, checked in :func:`run_for_profiles`.
    """
    cfg = load_config(_data_dir())
    now = now if now is not None else time.time()
    lt = time.localtime(now)
    today = time.strftime("%Y-%m-%d", lt)
    return lt.tm_hour >= int(cfg["hour"]) and load_state().get("last_date") != today


def _summary_line(m: Memory, max_len: int = 200) -> str:
    text = m.value.strip()
    first = text.splitlines()[0] if text else ""
    return first[:max_len] + "…" if len(first) > max_len else first


def _consolidate_episodic(store: MemoryStore, rel_store: RelationStore,
                          memories: List[Memory], cfg: Dict[str, Any],
                          now: Optional[float] = None) -> Dict[str, Any]:
    now = now if now is not None else time.time()
    cutoff = now - cfg["episodic_age_days"] * 86400
    eligible = [m for m in memories
                if m.category == "episodic"
                and m.updated_at <= cutoff
                and not m.metadata.get("consolidated_into")]

    groups: Dict[str, List[Memory]] = {}
    for m in eligible:
        prefix = m.key.split("/", 1)[0] if "/" in m.key else "misc"
        month = time.strftime("%Y-%m", time.localtime(m.created_at))
        groups.setdefault(f"{DIGEST_PREFIX}{prefix}/{month}", []).append(m)

    created = updated = consolidated = 0
    for digest_key, members in sorted(groups.items()):
        members.sort(key=lambda m: m.created_at)
        try:
            digest = store.get(digest_key)
            is_new = False
        except KeyError:
            digest = Memory(key=digest_key, value="", category="persistent")
            is_new = True
        already = set(digest.metadata.get("consolidated_from", []))
        members = [m for m in members if m.key not in already]
        if not members:
            continue

        lines = []
        for m in members:
            day = time.strftime("%Y-%m-%d", time.localtime(m.created_at))
            lines.append(f"- **{day}** `{m.key}` — {_summary_line(m)}")
        body = "\n".join(lines)
        digest.value = digest.value.rstrip() + "\n" + body if digest.value.strip() else body

        if "digest" not in digest.tags:
            digest.tags.insert(0, "digest")
        for m in members:
            for t in m.tags:
                if t not in digest.tags and len(digest.tags) < 12:
                    digest.tags.append(t)
        digest.metadata["consolidated_from"] = sorted(already | {m.key for m in members})
        store.set(digest, reset_ttl=False)

        for m in members:
            store.update_metadata(m.key, {"consolidated_into": digest_key})
            try:
                rel_store.add(m.key, digest_key, "consolidated_into")
            except Exception:
                pass
        consolidated += len(members)
        if is_new:
            created += 1
        else:
            updated += 1

    return {"eligible": len(eligible), "digests_created": created,
            "digests_updated": updated, "consolidated": consolidated}


def run_sleep_cycle(db: Database, profile_dir: Path,
                    config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Run one full sleep cycle against a single profile database."""
    cfg = {**DEFAULT_CONFIG, **(config or load_config(profile_dir))}
    store = MemoryStore(db)
    rel_store = RelationStore(db)
    started = time.time()
    report: Dict[str, Any] = {"started_at": started, "errors": []}

    memories = store.list()
    report["total_memories"] = len(memories)
    report["truncated"] = len(memories) > cfg["max_memories"]
    memories = memories[:cfg["max_memories"]]

    if cfg["episodic_enabled"]:
        try:
            report["episodic"] = _consolidate_episodic(store, rel_store, memories, cfg)
            if report["episodic"]["consolidated"] > 0:
                memories = store.list()[:cfg["max_memories"]]
        except Exception as e:
            report["errors"].append(f"episodic: {e}")

    if cfg["detect_relations"]:
        try:
            rels = detect_dependencies(memories)
            capped = len(rels) > MAX_AUTO_RELATIONS
            if capped:
                rels = sorted(rels, key=lambda r: -r["confidence"])[:MAX_AUTO_RELATIONS]
            cleared = rel_store.clear_auto()
            added = rel_store.bulk_add_auto(rels)
            report["relations"] = {"detected": len(rels), "added": added,
                                   "cleared": cleared, "capped": capped}
        except Exception as e:
            report["errors"].append(f"relations: {e}")

    try:
        dups = find_duplicates(memories, threshold=0.6)
        by_key = {m.key: m for m in memories}
        auto_merged = []
        if cfg["auto_merge"]:
            for g in dups:
                if g.similarity < cfg["merge_threshold"]:
                    continue
                group_mems = [by_key[k] for k in g.keys if k in by_key]
                if len(group_mems) < 2 or any(m.pinned for m in group_mems):
                    continue
                if any(m.key.startswith(DIGEST_PREFIX)
                       or m.metadata.get("consolidated_into") for m in group_mems):
                    continue
                try:
                    survivor = merge_group(store, [m.key for m in group_mems])
                    auto_merged.append({"survivor": survivor,
                                        "merged": [m.key for m in group_mems if m.key != survivor]})
                except Exception as e:
                    report["errors"].append(f"merge {g.keys[:2]}: {e}")
        report["duplicates"] = {
            "groups": len(dups),
            "auto_merged": len(auto_merged),
            "merged": auto_merged,
            "samples": [{"keys": g.keys, "similarity": g.similarity} for g in dups[:10]],
        }
    except Exception as e:
        report["errors"].append(f"duplicates: {e}")

    try:
        contras = find_contradictions(memories, max_results=MAX_CONTRADICTIONS)
        report["contradictions"] = {
            "count": len(contras),
            "capped": len(contras) >= MAX_CONTRADICTIONS,
            "samples": [{"key_a": c.key_a, "key_b": c.key_b,
                         "similarity": c.similarity, "reason": c.reason}
                        for c in contras[:10]],
        }
    except Exception as e:
        report["errors"].append(f"contradictions: {e}")

    try:
        now = time.time()
        low = sorted(
            ({"key": m.key, "confidence": confidence_score(m, now=now)} for m in memories),
            key=lambda x: x["confidence"])
        low = [x for x in low if x["confidence"] < 0.4]
        report["low_confidence"] = {"count": len(low), "samples": low[:10]}
    except Exception as e:
        report["errors"].append(f"confidence: {e}")

    report["duration_ms"] = int((time.time() - started) * 1000)
    try:
        _save_report(profile_dir, report, keep=int(cfg["keep_reports"]))
    except Exception as e:
        report["errors"].append(f"report: {e}")
    return report


def run_for_profiles(profile_ids: Optional[List[str]] = None,
                     record_state: bool = False) -> List[Dict[str, Any]]:
    """Run the sleep cycle for the given (default: all) profiles.

    Opens a private DB connection per profile so it is safe to call from a
    worker thread regardless of which profile is currently active.
    """
    from ..storage.profiles import DEFAULT_ID, PROFILES_DIR, ProfileManager
    if not _RUN_LOCK.acquire(blocking=False):
        return [{"skipped": "already_running"}]
    try:
        return _run_for_profiles_locked(profile_ids, record_state,
                                        DEFAULT_ID, PROFILES_DIR, ProfileManager)
    finally:
        _RUN_LOCK.release()


def _run_for_profiles_locked(profile_ids, record_state,
                             DEFAULT_ID, PROFILES_DIR, ProfileManager) -> List[Dict[str, Any]]:
    pm = ProfileManager()
    events = EventBus.instance()
    reports: List[Dict[str, Any]] = []

    for p in pm.list():
        if profile_ids is not None and p.id not in profile_ids:
            continue
        db_path = Path(p.db_path)
        if not db_path.exists():
            continue
        profile_dir = _data_dir() if p.id == DEFAULT_ID else PROFILES_DIR / p.id
        cfg = load_config(profile_dir)
        if not cfg["enabled"]:
            reports.append({"profile": p.id, "profile_name": p.name, "skipped": "disabled"})
            continue

        db = Database(db_path)
        try:
            report = run_sleep_cycle(db, profile_dir, cfg)
            changed = (report.get("episodic", {}).get("consolidated", 0)
                       + report.get("duplicates", {}).get("auto_merged", 0))
            # Embedding refresh only works for the active profile (the
            # embeddings module is bound to it); other profiles reindex on
            # their next activation via _trigger_background_index.
            if changed and p.id == pm.active_id:
                try:
                    from . import embeddings
                    embeddings.index_memories(MemoryStore(db).list(), profile_dir)
                except Exception:
                    pass
        finally:
            db.close()

        report["profile"] = p.id
        report["profile_name"] = p.name
        reports.append(report)
        ep = report.get("episodic", {})
        events.emit("sleep", "cycle", p.name,
                    f"{ep.get('consolidated', 0)} consolidated, "
                    f"{report.get('duplicates', {}).get('groups', 0)} dup-groups, "
                    f"{report.get('contradictions', {}).get('count', 0)} contradictions")

    if record_state:
        save_state({"last_date": time.strftime("%Y-%m-%d"), "last_run": time.time()})
    return reports
