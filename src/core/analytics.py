"""Analytics Engine — aggregated insights from memories and usage data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..storage.db import Database
from ..storage.memory import MemoryStore
from ..storage.usage import UsageStore


class AnalyticsEngine:
    """Computes analytics from memory and usage data."""

    def __init__(self, db: Database, memory_store: MemoryStore, usage_store: UsageStore) -> None:
        self._db = db
        self._memory_store = memory_store
        self._usage_store = usage_store

    def top_memories(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._db.conn.execute(
            """SELECT block_hash, COUNT(*) as use_count
               FROM block_usage
               WHERE included = 1
               GROUP BY block_hash
               ORDER BY use_count DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [{"block_hash": r["block_hash"], "use_count": r["use_count"]} for r in rows]

    def top_tags(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self._db.conn.execute("SELECT tags FROM memories").fetchall()
        tag_counts: Dict[str, int] = {}
        for r in rows:
            try:
                tags = json.loads(r["tags"])
            except (json.JSONDecodeError, TypeError):
                continue
            for t in tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1
        sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:limit]
        return [{"tag": t, "count": c} for t, c in sorted_tags]

    def connector_stats(self) -> List[Dict[str, Any]]:
        rows = self._db.conn.execute("SELECT key FROM memories").fetchall()
        counts: Dict[str, int] = {}
        for r in rows:
            key = r["key"]
            source = key.split("/")[0] if "/" in key else "(none)"
            counts[source] = counts.get(source, 0) + 1
        return sorted(
            [{"source": s, "count": c} for s, c in counts.items()],
            key=lambda x: -x["count"],
        )

    def memory_growth(self, days: int = 30) -> List[Dict[str, Any]]:
        rows = self._db.conn.execute(
            "SELECT created_at FROM memories ORDER BY created_at ASC"
        ).fetchall()
        daily: Dict[str, int] = {}
        for r in rows:
            dt = datetime.fromtimestamp(r["created_at"], tz=timezone.utc)
            date_str = dt.strftime("%Y-%m-%d")
            daily[date_str] = daily.get(date_str, 0) + 1

        sorted_dates = sorted(daily.keys(), reverse=True)[:days]
        sorted_dates.reverse()
        return [{"date": d, "count": daily[d]} for d in sorted_dates]

    def summary(self) -> Dict[str, Any]:
        total = self._memory_store.count()
        tags = self._memory_store.tags()
        sources = self._memory_store.sources()

        oldest = None
        newest = None
        if total > 0:
            row = self._db.conn.execute(
                "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM memories"
            ).fetchone()
            if row and row["oldest"] is not None:
                oldest = datetime.fromtimestamp(row["oldest"], tz=timezone.utc).isoformat()
                newest = datetime.fromtimestamp(row["newest"], tz=timezone.utc).isoformat()

        return {
            "total_memories": total,
            "total_tags": len(tags),
            "sources": len(sources),
            "oldest_memory": oldest,
            "newest_memory": newest,
        }
