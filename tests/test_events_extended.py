"""Extended tests for EventBus — coverage for SSE broadcasting, stats, filtering."""
from __future__ import annotations

import asyncio
import time

import pytest

from src.core.events import Event, EventBus


class TestEvent:
    def test_to_dict_just_now(self):
        e = Event(category="test", action="create", subject="foo")
        d = e.to_dict()
        assert d["age"] == "just now"
        assert d["category"] == "test"
        assert d["action"] == "create"

    def test_to_dict_minutes_ago(self):
        e = Event(category="test", action="x", subject="y", timestamp=time.time() - 120)
        d = e.to_dict()
        assert "m ago" in d["age"]

    def test_to_dict_hours_ago(self):
        e = Event(category="test", action="x", subject="y", timestamp=time.time() - 7200)
        d = e.to_dict()
        assert "h ago" in d["age"]

    def test_to_dict_days_ago(self):
        e = Event(category="test", action="x", subject="y", timestamp=time.time() - 172800)
        d = e.to_dict()
        assert "d ago" in d["age"]


class TestEventBus:
    def test_emit_and_recent(self):
        bus = EventBus(max_history=100)
        bus.emit("mem", "create", "test/key", "detail")
        recent = bus.recent(10)
        assert len(recent) >= 1
        assert recent[0].category == "mem"

    def test_recent_with_category_filter(self):
        bus = EventBus(max_history=100)
        bus.emit("mem", "create", "a")
        bus.emit("api", "get", "b")
        bus.emit("mem", "delete", "c")
        mem_events = bus.recent(10, category="mem")
        assert all(e.category == "mem" for e in mem_events)
        assert len(mem_events) == 2

    def test_stats(self):
        bus = EventBus(max_history=100)
        bus.emit("mem", "create", "a")
        bus.emit("mem", "create", "b")
        bus.emit("api", "get", "c")
        stats = bus.stats()
        assert stats["mem.create"] == 2
        assert stats["api.get"] == 1

    def test_subscribe_unsubscribe(self):
        bus = EventBus(max_history=100)
        q = bus.subscribe()
        assert q is not None
        bus.unsubscribe(q)

    def test_max_history(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.emit("test", "x", str(i))
        assert len(bus.recent(100)) == 5
