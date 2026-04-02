"""Event endpoints: SSE stream, recent events, stats."""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from src.web.deps import _events

router = APIRouter(tags=["events"])


@router.get("/api/events")
async def get_events(limit: int = Query(50, ge=1, le=200), category: str = Query("")):
    cat = category if category else None
    return [e.to_dict() for e in _events.recent(limit, cat)]


@router.get("/api/events/stats")
async def event_stats():
    return _events.stats()


@router.get("/api/events/stream")
async def event_stream():
    q = _events.subscribe()

    async def generate():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30)
                    data = json.dumps(event.to_dict())
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _events.unsubscribe(q)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
