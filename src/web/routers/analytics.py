"""Analytics endpoints: summary, top memories/tags, connector stats, growth, duplicates, similar."""
from __future__ import annotations

import asyncio
import time
from typing import Dict

from fastapi import APIRouter, HTTPException, Query

from src.core.analytics import AnalyticsEngine
from src.core.token_budget import TokenBudget
from src.web.deps import (
    _events,
    _estimate_total_tokens,
    _get_db,
    _get_memory_store,
    _get_usage_store,
)

router = APIRouter(tags=["analytics"])


# --- Dashboard Statistics ---

@router.get("/api/dashboard/stats")
async def dashboard_stats():
    def _compute_stats():
        store = _get_memory_store()
        total_count = store.count()
        total_tokens = _estimate_total_tokens(_get_db())

        db = _get_db()
        now = time.time()
        day_ago = now - 86400
        week_ago = now - 604800

        row = db.conn.execute("SELECT count(*) FROM memories WHERE created_at > ?", (day_ago,)).fetchone()
        new_today = row[0] if row else 0
        row = db.conn.execute("SELECT count(*) FROM memories WHERE updated_at > ? AND created_at <= ?", (day_ago, day_ago)).fetchone()
        updated_today = row[0] if row else 0
        row = db.conn.execute("SELECT count(*) FROM memories WHERE created_at > ? OR updated_at > ?", (week_ago, week_ago)).fetchone()
        new_this_week = row[0] if row else 0

        pinned_count = 0
        try:
            row = db.conn.execute("SELECT count(*) FROM memories WHERE pinned = 1").fetchone()
            pinned_count = row[0] if row else 0
        except Exception:
            pass

        tag_counts: Dict[str, int] = {}
        size_dist = {"small": 0, "medium": 0, "large": 0}
        for m in store.list():
            tokens = TokenBudget.estimate(m.value)
            if tokens < 100:
                size_dist["small"] += 1
            elif tokens < 500:
                size_dist["medium"] += 1
            else:
                size_dist["large"] += 1
            for t in m.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

        top_tags = sorted(tag_counts.items(), key=lambda x: -x[1])[:10]
        return {
            "total": total_count,
            "total_tokens": total_tokens,
            "new_today": new_today,
            "updated_today": updated_today,
            "new_this_week": new_this_week,
            "pinned": pinned_count,
            "size_distribution": size_dist,
            "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
            "trash_count": len(store.trash_list()),
        }

    return await asyncio.to_thread(_compute_stats)


# --- Scheduled Reports ---

@router.post("/api/reports/summary")
async def generate_summary_report():
    store = _get_memory_store()
    total_count = store.count()
    now = time.time()
    day_ago = now - 86400

    new_memories = store.list(sort="created", order="desc")
    new_memories = [m for m in new_memories if m.created_at > day_ago]
    updated_memories = [m for m in store.list(sort="updated", order="desc") if m.updated_at > day_ago and m.created_at <= day_ago]

    lines = [f"Context Pilot Report ({time.strftime('%Y-%m-%d %H:%M')})", ""]
    lines.append(f"Total: {total_count} memories")
    lines.append(f"New today: {len(new_memories)}")
    lines.append(f"Updated today: {len(updated_memories)}")

    if new_memories:
        lines.append("\nNew:")
        for m in new_memories[:10]:
            lines.append(f"  + {m.key}")
    if updated_memories:
        lines.append("\nUpdated:")
        for m in updated_memories[:10]:
            lines.append(f"  ~ {m.key}")

    report = "\n".join(lines)

    webhooks_sent = 0
    try:
        from src.core.webhooks import WebhookManager
        from src.web.deps import _get_profile_dir
        wm = WebhookManager(_get_profile_dir())
        results = wm.notify("report.summary", report)
        webhooks_sent = sum(1 for r in results if r.get("ok"))
    except Exception:
        pass

    return {"report": report, "webhooks_sent": webhooks_sent}


# --- Analytics ---

@router.get("/api/analytics/summary")
async def analytics_summary():
    engine = AnalyticsEngine(_get_db(), _get_memory_store(), _get_usage_store())
    return engine.summary()


@router.get("/api/analytics/top-memories")
async def analytics_top_memories(limit: int = Query(20, ge=1, le=100)):
    engine = AnalyticsEngine(_get_db(), _get_memory_store(), _get_usage_store())
    return engine.top_memories(limit)


@router.get("/api/analytics/top-tags")
async def analytics_top_tags(limit: int = Query(20, ge=1, le=100)):
    engine = AnalyticsEngine(_get_db(), _get_memory_store(), _get_usage_store())
    return engine.top_tags(limit)


@router.get("/api/analytics/connector-stats")
async def analytics_connector_stats():
    engine = AnalyticsEngine(_get_db(), _get_memory_store(), _get_usage_store())
    return engine.connector_stats()


@router.get("/api/analytics/memory-growth")
async def analytics_memory_growth(days: int = Query(30, ge=1, le=365)):
    engine = AnalyticsEngine(_get_db(), _get_memory_store(), _get_usage_store())
    return engine.memory_growth(days)


# --- Duplicate Detection ---

@router.get("/api/duplicates")
async def find_duplicates_api(
    threshold: float = Query(0.6, ge=0.3, le=1.0),
    limit: int = Query(500, ge=10, le=2000),
):
    from src.core.duplicates import find_duplicates
    store = _get_memory_store()

    def _do_find():
        return find_duplicates(store.list(limit=limit), threshold)

    groups = await asyncio.to_thread(_do_find)
    return [{"keys": g.keys, "similarity": g.similarity, "sample": g.sample} for g in groups]


@router.get("/api/similar/{key:path}")
async def find_similar_api(key: str, threshold: float = Query(0.5, ge=0.3, le=1.0)):
    from src.core.duplicates import find_similar
    store = _get_memory_store()
    try:
        target = store.get(key)
    except KeyError:
        raise HTTPException(404, f"Memory '{key}' not found")
    results = find_similar(target, store.list(), threshold)
    return [{"key": k, "similarity": s} for k, s in results]
