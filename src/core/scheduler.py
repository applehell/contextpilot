"""Background sync scheduler — periodically syncs connectors and folder sources."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from .events import EventBus


class SyncScheduler:
    _instance: Optional[SyncScheduler] = None

    def __init__(self, interval_minutes: int = 30) -> None:
        self.interval = interval_minutes * 60
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_run: Optional[float] = None
        self._events = EventBus.instance()

    @classmethod
    def instance(cls, interval_minutes: int = 30) -> SyncScheduler:
        if cls._instance is None:
            cls._instance = cls(interval_minutes)
        return cls._instance

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_run(self) -> Optional[float]:
        return self._last_run

    def start(self, get_store_fn, get_db_fn) -> None:
        if self._running:
            return
        self._running = True
        self._get_store = get_store_fn
        self._get_db = get_db_fn
        self._task = asyncio.create_task(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def set_interval(self, minutes: int) -> None:
        self.interval = minutes * 60

    async def run_once(self) -> dict:
        """Run all syncs once and return results."""
        results = {"folders": {}, "connectors": {}}

        try:
            from ..storage.folders import FolderManager
            fm = FolderManager()
            store = self._get_store()
            folder_results = fm.scan_all(store)
            for name, r in folder_results.items():
                results["folders"][name] = {"added": r.added, "updated": r.updated, "removed": r.removed}
                if r.added + r.updated + r.removed > 0:
                    self._events.emit("scheduler", "folder-sync", name, f"+{r.added} ~{r.updated} -{r.removed}")
        except Exception as e:
            results["folders"]["_error"] = str(e)

        try:
            from ..connectors.registry import ConnectorRegistry
            registry = ConnectorRegistry.instance()
            store = self._get_store()
            for connector in registry.list():
                if connector.configured and connector.enabled:
                    try:
                        r = connector.sync(store)
                        results["connectors"][connector.name] = {"added": r.added, "updated": r.updated, "removed": r.removed}
                        if r.added + r.updated + r.removed > 0:
                            self._events.emit("scheduler", "connector-sync", connector.name, f"+{r.added} ~{r.updated} -{r.removed}")
                    except Exception as e:
                        results["connectors"][connector.name] = {"error": str(e)}
        except Exception as e:
            results["connectors"]["_error"] = str(e)

        self._last_run = time.time()
        return results

    async def _loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self.interval)
                if not self._running:
                    break
                self._events.emit("scheduler", "run", "auto-sync", f"interval={self.interval // 60}m")
                await self.run_once()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._events.emit("scheduler", "error", "auto-sync", str(e))

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "interval_minutes": self.interval // 60,
            "last_run": self._last_run,
        }
