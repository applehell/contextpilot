"""Auto-discover and manage connector plugins."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional, Type

from .base import ConnectorPlugin


class ConnectorRegistry:
    _instance: Optional[ConnectorRegistry] = None
    _current_data_dir: Optional[Path] = None

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir = data_dir
        self._plugins: Dict[str, ConnectorPlugin] = {}
        self._discover()

    @classmethod
    def instance(cls, data_dir: Optional[Path] = None) -> ConnectorRegistry:
        if cls._instance is None or (data_dir and data_dir != cls._current_data_dir):
            cls._instance = cls(data_dir)
            cls._current_data_dir = data_dir
        return cls._instance

    @classmethod
    def reload(cls, data_dir: Optional[Path] = None) -> ConnectorRegistry:
        """Force reload with new data_dir (e.g. after profile switch)."""
        cls._instance = cls(data_dir)
        cls._current_data_dir = data_dir
        return cls._instance

    def _discover(self) -> None:
        import src.connectors as pkg

        for importer, modname, ispkg in pkgutil.iter_modules(pkg.__path__):
            if modname in ("base", "registry", "__init__"):
                continue
            try:
                module = importlib.import_module(f"src.connectors.{modname}")
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type)
                            and issubclass(attr, ConnectorPlugin)
                            and attr is not ConnectorPlugin
                            and hasattr(attr, 'name')
                            and attr.name):
                        plugin = attr(data_dir=self._data_dir)
                        self._plugins[plugin.name] = plugin
            except Exception as e:
                print(f"Warning: Failed to load connector module '{modname}': {e}")

    def list(self) -> List[ConnectorPlugin]:
        return sorted(self._plugins.values(), key=lambda p: p.name)

    def get(self, name: str) -> Optional[ConnectorPlugin]:
        return self._plugins.get(name)

    def names(self) -> List[str]:
        return sorted(self._plugins.keys())
