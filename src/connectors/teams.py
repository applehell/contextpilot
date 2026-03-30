"""Microsoft Teams connector plugin — sync channel messages via Microsoft Graph API."""
from __future__ import annotations

import hashlib
import re
import time
from typing import Any, Dict, List, Optional

import requests

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _acquire_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    resp = requests.post(url, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


def _graph_get(url: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None) -> requests.Response:
    for attempt in range(3):
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 5))
            time.sleep(min(retry_after, 30))
            continue
        return resp
    return resp


class TeamsConnector(ConnectorPlugin):
    name = "teams"
    display_name = "Microsoft Teams"
    description = "Sync channel messages from Microsoft Teams via Graph API"
    icon = "T"
    category = "Communication"
    setup_guide = "Register an app in Azure AD (portal.azure.com > App registrations) with Teams API permissions."
    color = "#6264a7"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("tenant_id", "Tenant ID", required=True, placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"),
            ConfigField("client_id", "Client ID (App Registration)", required=True, placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"),
            ConfigField("client_secret", "Client Secret", type="password", required=True),
            ConfigField("webhook_url", "Incoming Webhook URL", placeholder="https://...webhook.office.com/..."),
            ConfigField("team_name", "Filter to team (optional)", placeholder="My Team"),
            ConfigField("channel_filter", "Channel filter (comma-separated)", placeholder="General, Announcements"),
            ConfigField("message_limit", "Messages per channel", type="number", default=50),
        ]

    def _get_token(self) -> str:
        return _acquire_token(
            self._config["tenant_id"],
            self._config["client_id"],
            self._config["client_secret"],
        )

    def _headers(self, token: str) -> Dict[str, str]:
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def test_connection(self) -> Dict[str, Any]:
        for field_name in ("tenant_id", "client_id", "client_secret"):
            if not self._config.get(field_name):
                return {"ok": False, "error": f"Missing required field: {field_name}"}
        try:
            token = self._get_token()
            resp = _graph_get(f"{GRAPH_BASE}/teams", self._headers(token))
            if resp.status_code == 200:
                teams = resp.json().get("value", [])
                return {"ok": True, "message": f"Connected, {len(teams)} team(s) accessible"}
            return {"ok": False, "error": f"Graph API returned {resp.status_code}: {resp.text[:200]}"}
        except requests.exceptions.ConnectionError as e:
            return {"ok": False, "error": f"Connection failed: {e}"}
        except requests.exceptions.HTTPError as e:
            return {"ok": False, "error": f"Auth failed: {e}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def sync(self, store: MemoryStore) -> SyncResult:
        result = SyncResult()

        for field_name in ("tenant_id", "client_id", "client_secret"):
            if not self._config.get(field_name):
                result.errors.append(f"Missing required field: {field_name}")
                return result

        try:
            token = self._get_token()
        except Exception as e:
            result.errors.append(f"Auth failed: {e}")
            return result

        headers = self._headers(token)
        limit = int(self._config.get("message_limit", 50))
        team_filter = self._config.get("team_name", "").strip()
        channel_filter_raw = self._config.get("channel_filter", "")
        channel_names = {c.strip().lower() for c in channel_filter_raw.split(",") if c.strip()} if channel_filter_raw else set()
        prefix = f"{self.name}/"
        synced_keys = set()

        # List teams
        resp = _graph_get(f"{GRAPH_BASE}/teams", headers)
        if resp.status_code != 200:
            result.errors.append(f"Failed to list teams: {resp.status_code}")
            return result

        teams = resp.json().get("value", [])

        for team in teams:
            team_name = team.get("displayName", "unknown")
            team_id = team["id"]

            if team_filter and team_name.lower() != team_filter.lower():
                continue

            # List channels
            ch_resp = _graph_get(f"{GRAPH_BASE}/teams/{team_id}/channels", headers)
            if ch_resp.status_code != 200:
                result.errors.append(f"Failed to list channels for {team_name}: {ch_resp.status_code}")
                continue

            channels = ch_resp.json().get("value", [])

            for channel in channels:
                channel_name = channel.get("displayName", "unknown")
                channel_id = channel["id"]

                if channel_names and channel_name.lower() not in channel_names:
                    continue

                # Fetch messages
                msg_resp = _graph_get(
                    f"{GRAPH_BASE}/teams/{team_id}/channels/{channel_id}/messages",
                    headers,
                    params={"$top": limit},
                )
                if msg_resp.status_code != 200:
                    result.errors.append(f"Failed to get messages for {team_name}/{channel_name}: {msg_resp.status_code}")
                    continue

                messages = msg_resp.json().get("value", [])
                result.total_remote += len(messages)

                for msg in messages:
                    msg_id = msg.get("id", "")
                    if not msg_id:
                        continue

                    sender_info = msg.get("from", {})
                    user_info = sender_info.get("user", {}) if sender_info else {}
                    sender = user_info.get("displayName", "Unknown") if user_info else "Unknown"

                    timestamp = msg.get("createdDateTime", "")
                    body_obj = msg.get("body", {})
                    body_content = body_obj.get("content", "") if body_obj else ""

                    if body_obj and body_obj.get("contentType") == "html":
                        body_text = _strip_html(body_content)
                    else:
                        body_text = body_content

                    if not body_text.strip():
                        result.skipped += 1
                        continue

                    safe_team = re.sub(r"[^a-zA-Z0-9_-]", "_", team_name)[:40]
                    safe_channel = re.sub(r"[^a-zA-Z0-9_-]", "_", channel_name)[:40]
                    safe_msg_id = re.sub(r"[^a-zA-Z0-9_-]", "_", msg_id)[:60]
                    key = f"{prefix}{safe_team}/{safe_channel}/{safe_msg_id}"
                    synced_keys.add(key)

                    content = f"[{timestamp}] {sender}: {body_text[:3000]}"
                    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                    tags = [self.name, team_name.lower(), channel_name.lower()]

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
                                "content_hash": content_hash,
                                "team": team_name,
                                "channel": channel_name,
                                "sender": sender,
                                "timestamp": timestamp,
                                "message_id": msg_id,
                            },
                        )
                        store.set(mem)
                        result.added += 1

        self._update_sync_stats(len(synced_keys))
        return result
