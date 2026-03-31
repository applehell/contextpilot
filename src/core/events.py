"""Global event bus — tracks all activity across Context Pilot with SSE broadcast."""
from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class Event:
    category: str       # api, memory, sync, import, profile, folder, paperless, system
    action: str         # e.g. search, create, delete, scan, sync, switch, connect
    subject: str        # what was acted on (key, name, path, etc.)
    detail: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        delta = time.time() - self.timestamp
        if delta < 60:
            age = "just now"
        elif delta < 3600:
            age = f"{int(delta / 60)}m ago"
        elif delta < 86400:
            age = f"{int(delta / 3600)}h ago"
        else:
            age = f"{int(delta / 86400)}d ago"

        return {
            "category": self.category,
            "action": self.action,
            "subject": self.subject,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "age": age,
        }


class EventBus:
    _instance: Optional[EventBus] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self, max_history: int = 200) -> None:
        self._history: deque[Event] = deque(maxlen=max_history)
        self._subscribers: Set[asyncio.Queue] = set()
        self._counts: Dict[str, int] = {}
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> EventBus:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def emit(self, category: str, action: str, subject: str, detail: str = "") -> None:
        event = Event(category=category, action=action, subject=subject, detail=detail)
        with self._lock:
            self._history.appendleft(event)

            key = f"{category}.{action}"
            self._counts[key] = self._counts.get(key, 0) + 1

            # Broadcast to SSE subscribers
            dead = set()
            for q in list(self._subscribers):
                try:
                    q.put_nowait(event)
                except asyncio.QueueFull:
                    dead.add(q)
            self._subscribers -= dead

    def recent(self, limit: int = 50, category: Optional[str] = None) -> List[Event]:
        if category:
            return [e for e in self._history if e.category == category][:limit]
        return list(self._history)[:limit]

    def stats(self) -> Dict[str, int]:
        return dict(self._counts)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subscribers.discard(q)
