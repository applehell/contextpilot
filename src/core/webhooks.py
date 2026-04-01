"""Webhook notifications — send alerts via WAHA (WhatsApp) or generic HTTP webhooks."""
from __future__ import annotations

import ipaddress
import json
import os
import stat
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


_DATA_DIR = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
WEBHOOKS_CONFIG = _DATA_DIR / "webhooks.json"


@dataclass
class WebhookConfig:
    name: str
    type: str                  # "waha", "generic"
    url: str
    enabled: bool = True
    events: List[str] = field(default_factory=list)  # e.g. ["secrets.found", "sync.error"]
    # WAHA-specific
    chat_id: str = ""
    session: str = "default"


class WebhookManager:

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._dir = data_dir or _DATA_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._config_path = self._dir / "webhooks.json"
        self._config: Dict[str, Any] = self._load()

    def _load(self) -> Dict[str, Any]:
        if self._config_path.exists():
            return json.loads(self._config_path.read_text())
        return {"hooks": {}}

    def _save(self) -> None:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(self._config_path.parent), suffix=".tmp")
        try:
            with os.fdopen(tmp_fd, 'w') as f:
                json.dump(self._config, f, indent=2)
            os.replace(tmp_path, str(self._config_path))
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        try:
            self._config_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def list(self) -> List[WebhookConfig]:
        return [WebhookConfig(name=n, **d) for n, d in self._config["hooks"].items()]

    def add(self, name: str, type: str, url: str, chat_id: str = "", session: str = "default",
            events: Optional[List[str]] = None) -> None:
        self._config["hooks"][name] = {
            "type": type, "url": url.rstrip("/"), "enabled": True,
            "events": events or [], "chat_id": chat_id, "session": session,
        }
        self._save()

    def remove(self, name: str) -> None:
        if name not in self._config["hooks"]:
            raise KeyError(f"Webhook '{name}' not found")
        del self._config["hooks"][name]
        self._save()

    def update(self, name: str, **kwargs) -> None:
        if name not in self._config["hooks"]:
            raise KeyError(f"Webhook '{name}' not found")
        for k, v in kwargs.items():
            if v is not None:
                self._config["hooks"][name][k] = v
        self._save()

    def notify(self, event: str, message: str) -> List[dict]:
        """Send notification to all matching webhooks. Returns results."""
        results = []
        for hook in self.list():
            if not hook.enabled:
                continue
            if hook.events and event not in hook.events:
                continue
            try:
                if hook.type == "waha":
                    _send_waha(hook, message)
                else:
                    _send_generic(hook, event, message)
                results.append({"name": hook.name, "ok": True})
            except Exception as e:
                results.append({"name": hook.name, "ok": False, "error": str(e)})
        return results


_BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}


def _validate_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Blocked host: {host}")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"Blocked private address: {addr}")
    except ValueError as e:
        if "Blocked" in str(e):
            raise
        # hostname, not IP — allow


def _send_waha(hook: WebhookConfig, message: str) -> None:
    url = f"{hook.url}/api/sendText"
    _validate_url(url)
    payload = json.dumps({
        "chatId": hook.chat_id,
        "text": message,
        "session": hook.session,
    }).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()


def _send_generic(hook: WebhookConfig, event: str, message: str) -> None:
    _validate_url(hook.url)
    payload = json.dumps({"event": event, "message": message}).encode()
    req = urllib.request.Request(
        hook.url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read()
