"""App settings persistence — JSON file in user config directory."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def _settings_path() -> Path:
    config = Path.home() / ".config" / "contextpilot"
    config.mkdir(parents=True, exist_ok=True)
    return config / "settings.json"


def load_settings() -> Dict[str, Any]:
    path = _settings_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_settings(data: Dict[str, Any]) -> None:
    path = _settings_path()
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_last_project() -> Optional[str]:
    settings = load_settings()
    return settings.get("last_project_db")


def set_last_project(db_path: str) -> None:
    settings = load_settings()
    settings["last_project_db"] = db_path
    save_settings(settings)
