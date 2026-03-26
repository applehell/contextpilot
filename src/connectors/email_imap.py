"""Email (IMAP) connector plugin — sync emails from multiple accounts."""
from __future__ import annotations

import email
import email.header
import email.utils
import hashlib
import imaplib
import json
import re
import ssl
import time
from typing import Any, Dict, List, Optional

from ..storage.memory import Memory, MemoryStore
from .base import ConfigField, ConnectorPlugin, SyncResult


def _decode_header(raw: str) -> str:
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _extract_text(msg: email.message.Message) -> str:
    """Extract plain-text body from a message."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain" and part.get("Content-Disposition") != "attachment":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # Fallback: try text/html
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html" and part.get("Content-Disposition") != "attachment":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    return re.sub(r"<[^>]+>", "", html).strip()
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            text = payload.decode(charset, errors="replace")
            if msg.get_content_type() == "text/html":
                return re.sub(r"<[^>]+>", "", text).strip()
            return text
    return ""


def _connect(host: str, port: int, user: str, password: str, use_ssl: bool = True) -> imaplib.IMAP4:
    if use_ssl:
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    else:
        conn = imaplib.IMAP4(host, port)
    conn.login(user, password)
    return conn


def _fetch_emails(conn: imaplib.IMAP4, folder: str, max_emails: int, since_days: int) -> List[Dict[str, Any]]:
    """Fetch recent emails from a folder."""
    status, _ = conn.select(folder, readonly=True)
    if status != "OK":
        return []

    import datetime
    since = (datetime.datetime.now() - datetime.timedelta(days=since_days)).strftime("%d-%b-%Y")
    _, msg_ids = conn.search(None, f'(SINCE "{since}")')

    ids = msg_ids[0].split()
    if not ids:
        return []

    # Take the most recent N
    ids = ids[-max_emails:]
    results = []

    for mid in ids:
        _, data = conn.fetch(mid, "(RFC822)")
        if not data or not data[0]:
            continue
        raw = data[0][1]
        if isinstance(raw, bytes):
            msg = email.message_from_bytes(raw)
        else:
            continue

        subject = _decode_header(msg.get("Subject", "(no subject)"))
        from_addr = _decode_header(msg.get("From", ""))
        to_addr = _decode_header(msg.get("To", ""))
        date_str = msg.get("Date", "")
        message_id = msg.get("Message-ID", "")
        body = _extract_text(msg)

        # Parse date
        parsed_date = email.utils.parsedate_to_datetime(date_str) if date_str else None
        date_iso = parsed_date.isoformat() if parsed_date else date_str

        results.append({
            "message_id": message_id,
            "subject": subject,
            "from": from_addr,
            "to": to_addr,
            "date": date_iso,
            "body": body[:5000],  # limit body size
        })

    return results


class EmailConnector(ConnectorPlugin):
    name = "email"
    display_name = "Email (IMAP)"
    description = "Sync emails from IMAP accounts as knowledge memories"
    icon = "@"

    def config_schema(self) -> List[ConfigField]:
        return [
            ConfigField("max_emails", "Max emails per folder", type="number", default=50),
            ConfigField("since_days", "Sync emails from last N days", type="number", default=30),
            ConfigField("max_body_length", "Max body length (chars)", type="number", default=2000),
        ]

    @property
    def configured(self) -> bool:
        return bool(self._get_accounts())

    def _get_accounts(self) -> List[Dict[str, Any]]:
        raw = self._config.get("accounts", "")
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return []

    def test_connection(self) -> Dict[str, Any]:
        accounts = self._get_accounts()
        if not accounts:
            return {"ok": False, "error": "No accounts configured"}
        results = []
        all_ok = True
        for acc in accounts:
            name = acc.get("name", acc.get("host", "unknown"))
            try:
                conn = _connect(
                    acc["host"], int(acc.get("port", 993)),
                    acc["user"], acc["password"],
                    acc.get("ssl", True),
                )
                _, folders = conn.list()
                folder_count = len(folders) if folders else 0
                conn.logout()
                results.append({"account": name, "ok": True, "folders": folder_count})
            except Exception as e:
                results.append({"account": name, "ok": False, "error": str(e)})
                all_ok = False
        return {
            "ok": all_ok,
            "accounts": results,
            "message": f"{len(accounts)} account(s), {sum(1 for r in results if r['ok'])} connected",
        }

    def sync(self, store: MemoryStore) -> SyncResult:
        accounts = self._get_accounts()
        if not accounts:
            r = SyncResult()
            r.errors.append("No accounts configured")
            return r

        result = SyncResult()
        max_emails = int(self._config.get("max_emails", 50))
        since_days = int(self._config.get("since_days", 30))
        max_body = int(self._config.get("max_body_length", 2000))
        prefix = f"{self.name}/"
        synced_keys = set()

        for acc in accounts:
            acc_name = acc.get("name", acc.get("host", "unknown"))
            acc_tags = acc.get("tags", ["email"])
            if isinstance(acc_tags, str):
                acc_tags = [t.strip() for t in acc_tags.split(",") if t.strip()]
            folders = acc.get("folders", ["INBOX"])
            if isinstance(folders, str):
                folders = [f.strip() for f in folders.split(",") if f.strip()]

            try:
                conn = _connect(
                    acc["host"], int(acc.get("port", 993)),
                    acc["user"], acc["password"],
                    acc.get("ssl", True),
                )
            except Exception as e:
                result.errors.append(f"{acc_name}: connection failed: {e}")
                continue

            try:
                for folder in folders:
                    try:
                        emails = _fetch_emails(conn, folder, max_emails, since_days)
                    except Exception as e:
                        result.errors.append(f"{acc_name}/{folder}: {e}")
                        continue

                    result.total_remote += len(emails)

                    for em in emails:
                        # Generate stable key from message-id or hash
                        mid = em["message_id"] or hashlib.sha256(
                            f"{em['from']}{em['subject']}{em['date']}".encode()
                        ).hexdigest()[:16]
                        safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", mid.strip("<>"))[:80]
                        key = f"{prefix}{acc_name}/{safe_id}"
                        synced_keys.add(key)

                        body = em["body"][:max_body] if em["body"] else "(empty)"
                        content = f"# {em['subject']}\n\nFrom: {em['from']}\nTo: {em['to']}\nDate: {em['date']}\n\n{body}"
                        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

                        tags = [self.name] + acc_tags
                        if folder != "INBOX":
                            tags.append(folder.lower().strip('"'))

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
                                    "account": acc_name,
                                    "content_hash": content_hash,
                                    "subject": em["subject"],
                                    "from": em["from"],
                                    "date": em["date"],
                                    "folder": folder,
                                },
                            )
                            store.set(mem)
                            result.added += 1
            finally:
                try:
                    conn.logout()
                except Exception:
                    pass

        self._update_sync_stats(len(synced_keys))
        return result
