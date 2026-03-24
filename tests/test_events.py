"""Tests for the global EventBus."""
from __future__ import annotations

import pytest

from src.core.events import Event, EventBus


@pytest.fixture
def bus():
    b = EventBus(max_history=50)
    return b


class TestEmit:
    def test_emit_adds_to_history(self, bus):
        bus.emit("memory", "create", "test/key")
        events = bus.recent(10)
        assert len(events) == 1
        assert events[0].category == "memory"
        assert events[0].action == "create"
        assert events[0].subject == "test/key"

    def test_emit_with_detail(self, bus):
        bus.emit("folder", "scan", "docs", "+5 ~2 -1")
        e = bus.recent(1)[0]
        assert e.detail == "+5 ~2 -1"

    def test_history_order(self, bus):
        bus.emit("memory", "create", "first")
        bus.emit("memory", "create", "second")
        events = bus.recent(10)
        assert events[0].subject == "second"
        assert events[1].subject == "first"

    def test_history_limit(self):
        bus = EventBus(max_history=3)
        for i in range(5):
            bus.emit("api", "get", f"/path/{i}")
        assert len(bus.recent(10)) == 3
        assert bus.recent(1)[0].subject == "/path/4"


class TestRecent:
    def test_recent_with_limit(self, bus):
        for i in range(10):
            bus.emit("api", "get", f"/path/{i}")
        assert len(bus.recent(5)) == 5

    def test_recent_with_category_filter(self, bus):
        bus.emit("memory", "create", "key1")
        bus.emit("api", "get", "/api/memories")
        bus.emit("memory", "delete", "key2")
        filtered = bus.recent(10, category="memory")
        assert len(filtered) == 2
        assert all(e.category == "memory" for e in filtered)

    def test_recent_empty(self, bus):
        assert bus.recent(10) == []


class TestStats:
    def test_stats_counts(self, bus):
        bus.emit("memory", "create", "a")
        bus.emit("memory", "create", "b")
        bus.emit("api", "get", "/test")
        stats = bus.stats()
        assert stats["memory.create"] == 2
        assert stats["api.get"] == 1

    def test_stats_empty(self, bus):
        assert bus.stats() == {}


class TestEvent:
    def test_to_dict(self):
        e = Event(category="memory", action="create", subject="test/key", detail="tags=[a,b]")
        d = e.to_dict()
        assert d["category"] == "memory"
        assert d["action"] == "create"
        assert d["subject"] == "test/key"
        assert d["detail"] == "tags=[a,b]"
        assert "age" in d
        assert "timestamp" in d

    def test_age_label_just_now(self):
        e = Event(category="api", action="get", subject="/test")
        d = e.to_dict()
        assert d["age"] == "just now"


class TestSubscribe:
    def test_subscriber_receives_events(self, bus):
        q = bus.subscribe()
        bus.emit("memory", "create", "key1")
        assert not q.empty()
        event = q.get_nowait()
        assert event.subject == "key1"
        bus.unsubscribe(q)

    def test_unsubscribe(self, bus):
        q = bus.subscribe()
        bus.unsubscribe(q)
        bus.emit("memory", "create", "key1")
        assert q.empty()

    def test_multiple_subscribers(self, bus):
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        bus.emit("api", "get", "/test")
        assert not q1.empty()
        assert not q2.empty()
        bus.unsubscribe(q1)
        bus.unsubscribe(q2)


class TestSingleton:
    def test_instance_returns_same(self):
        a = EventBus.instance()
        b = EventBus.instance()
        assert a is b
