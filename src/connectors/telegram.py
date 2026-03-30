"""Telegram Bot connector plugin — sync messages from Telegram chats."""
from __future__ import annotations

import hashlib
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


def _api_call(token: str, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{token}/{method}"
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))
    return data["result"]


def _format_date(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _safe_key(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", text)[:80]


class TelegramConnector(ConnectorPlugin):
    name = "telegram"
    display_name = "Telegram"
    description = "Sync messages from Telegram chats via Bot API"
    icon = "TG"
    category = "Communication"
    setup_guide = "Create a bot via @BotFather, get the bot token. Add the bot to groups/channels you want to sync."
    color = "#0088cc"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("bot_token", "Bot Token", type="password", required=True,
                        placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"),
            ConfigField("chat_ids", "Chat IDs (comma-separated, empty=all)", type="text",
                        placeholder="-1001234567890, 987654321"),
            ConfigField("message_limit", "Max messages per sync", type="number", default=100),
            ConfigField("include_media_captions", "Include media captions", type="boolean", default=True),
            ConfigField("ttl_days", "Auto-expire after N days (0=never)", type="number", default=0),
        ]

    def _get_token(self) -> str:
        return self._config.get("bot_token", "")

    def _get_chat_ids(self) -> List[str]:
        raw = self._config.get("chat_ids", "")
        if not raw or not raw.strip():
            return []
        return [cid.strip() for cid in raw.split(",") if cid.strip()]

    def test_connection(self) -> Dict[str, Any]:
        token = self._get_token()
        if not token:
            return {"ok": False, "error": "No bot token configured"}
        try:
            bot = _api_call(token, "getMe")
            return {
                "ok": True,
                "bot_name": bot.get("first_name", ""),
                "bot_username": bot.get("username", ""),
                "message": f"Connected as @{bot.get('username', 'unknown')}",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        token = self._get_token()
        if not token:
            r = SyncResult()
            r.errors.append("No bot token configured")
            return r

        result = SyncResult()
        message_limit = int(self._config.get("message_limit", 100))
        include_captions = self._config.get("include_media_captions", True)
        if isinstance(include_captions, str):
            include_captions = include_captions.lower() in ("true", "1", "yes")
        chat_filter = set(self._get_chat_ids())
        prefix = f"{self.name}/"
        synced_keys = set()

        try:
            updates = _api_call(token, "getUpdates", {"limit": message_limit, "allowed_updates": '["message","channel_post"]'})
        except Exception as e:
            result.errors.append(f"Failed to fetch updates: {e}")
            self._update_sync_stats(0)
            return result

        messages = []
        for update in updates:
            msg = update.get("message") or update.get("channel_post")
            if not msg:
                continue
            messages.append(msg)

        result.total_remote = len(messages)

        chat_cache: Dict[int, str] = {}

        for msg in messages:
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))

            if chat_filter and chat_id not in chat_filter:
                result.skipped += 1
                continue

            chat_title = chat_cache.get(chat.get("id"))
            if chat_title is None:
                chat_title = chat.get("title") or chat.get("first_name") or chat.get("username") or chat_id
                chat_cache[chat.get("id", 0)] = chat_title

            message_id = msg.get("message_id", 0)
            sender = msg.get("from", {})
            sender_name = sender.get("first_name", "")
            if sender.get("last_name"):
                sender_name += f" {sender['last_name']}"
            if not sender_name:
                sender_name = sender.get("username", "Unknown")

            text = msg.get("text", "")
            if not text and include_captions:
                text = msg.get("caption", "")
            if not text:
                media_type = None
                for mt in ("photo", "video", "document", "audio", "voice", "sticker", "animation"):
                    if mt in msg:
                        media_type = mt
                        break
                if media_type:
                    text = f"[{media_type}]"
                else:
                    continue

            date_ts = msg.get("date", 0)
            date_str = _format_date(date_ts) if date_ts else ""

            safe_title = _safe_key(chat_title)
            key = f"{prefix}{safe_title}/{message_id}"
            synced_keys.add(key)

            content = f"From: {sender_name}\nDate: {date_str}\n\n{text}"
            content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

            tags = [self.name, chat_title]

            try:
                existing = store.get(key)
                if existing.metadata.get("content_hash") == content_hash:
                    result.skipped += 1
                    continue
                existing.value = content
                existing.tags = tags
                existing.metadata["content_hash"] = content_hash
                store.set(existing)
                result.updated += 1
            except KeyError:
                mem = Memory(
                    key=key,
                    value=content,
                    tags=tags,
                    metadata={
                        "source": self.name,
                        "chat_id": chat_id,
                        "chat_title": chat_title,
                        "content_hash": content_hash,
                        "sender": sender_name,
                        "date": date_str,
                        "message_id": message_id,
                    },
                    expires_at=self._compute_expires_at(),
                )
                store.set(mem)
                result.added += 1

        self._update_sync_stats(len(synced_keys))
        return result
