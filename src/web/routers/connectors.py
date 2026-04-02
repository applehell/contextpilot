"""Connector endpoints: list, setup, sync, health, email accounts."""
from __future__ import annotations

import asyncio
import json
import os

from fastapi import APIRouter, HTTPException, Query, Request

from src.core.log import get_logger

logger = get_logger("routers.connectors")

from src.web.deps import (
    _events,
    _get_connectors,
    _get_connector,
    _get_memory_store,
    _get_profile_dir,
    InboundPayload,
)
from src.storage.memory import Memory

router = APIRouter(tags=["connectors"])


@router.get("/api/connectors/health")
async def connectors_health():
    def _check_health():
        results = []
        for c in _get_connectors().list():
            status = c.get_status()
            sync_history = status.get("sync_history", [])
            last_error_detail = None
            for s in sync_history:
                if s.get("error_details"):
                    last_error_detail = s["error_details"]
                    break
            health = {
                "name": status["name"],
                "display_name": status.get("display_name", ""),
                "configured": status.get("configured", False),
                "enabled": status.get("enabled", False),
                "last_sync": status.get("last_sync"),
                "error_count": status.get("error_count", 0),
                "total_synced": status.get("synced_count", 0),
                "last_error_detail": last_error_detail,
            }
            if status.get("configured"):
                try:
                    test = c.test_connection()
                    health["reachable"] = test.get("ok", False)
                    health["detail"] = test.get("message", "")
                except Exception as e:
                    health["reachable"] = False
                    health["detail"] = str(e)
            else:
                health["reachable"] = None
                health["detail"] = "not configured"
            results.append(health)
        return results

    return await asyncio.to_thread(_check_health)


@router.get("/api/connectors")
async def list_connectors():
    return [c.get_status() for c in _get_connectors().list()]


@router.get("/api/connectors/{name}")
async def connector_status(name: str):
    return _get_connector(name).get_status()


@router.post("/api/connectors/{name}/setup")
async def connector_setup(name: str, request: Request):
    c = _get_connector(name)
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    c.configure(body)
    result = c.test_connection()
    logger.info("Connector '%s' configured, test ok=%s", name, result.get("ok"))
    _events.emit("connector", "setup", name, f"ok={result.get('ok')}")
    return {"status": "configured", "test": result}


@router.put("/api/connectors/{name}")
async def connector_update(name: str, request: Request):
    c = _get_connector(name)
    if not c.configured:
        raise HTTPException(400, f"Connector '{name}' not configured yet.")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    c.update(body)
    return {"status": "updated"}


@router.post("/api/connectors/{name}/test")
async def connector_test(name: str):
    c = _get_connector(name)
    return c.test_connection()


@router.post("/api/connectors/{name}/sync")
async def connector_sync(name: str):
    c = _get_connector(name)
    store = _get_memory_store()
    result = await asyncio.to_thread(c.sync, store)
    c._record_sync(result)
    logger.info("Connector '%s' synced: +%d ~%d -%d", name, result.added, result.updated, result.removed)
    _events.emit("connector", "sync", name, f"+{result.added} ~{result.updated} -{result.removed}")
    return {"status": "synced", **result.to_dict()}


@router.get("/api/connectors/{name}/history")
async def connector_history(name: str):
    c = _get_connector(name)
    return c._config.get("_sync_history", [])


@router.post("/api/connectors/{name}/enable")
async def connector_enable(name: str, enabled: bool = Query(True)):
    c = _get_connector(name)
    c.set_enabled(enabled)
    return {"status": "updated", "enabled": enabled}


@router.delete("/api/connectors/{name}")
async def connector_remove(name: str, purge: bool = Query(False)):
    c = _get_connector(name)
    purged = 0
    if purge:
        store = _get_memory_store()
        purged = c.purge(store)
    c.remove()
    logger.info("Connector '%s' removed, purged=%d memories", name, purged)
    _events.emit("connector", "remove", name, f"purged={purged}")
    return {"status": "removed", "purged_memories": purged}


# --- Email Connector Account Management ---

@router.get("/api/connectors/email/accounts")
async def email_accounts():
    c = _get_connector("email")
    accounts = c._get_accounts()
    safe = []
    for acc in accounts:
        a = dict(acc)
        if a.get("password"):
            a["password"] = "********"
        safe.append(a)
    return safe


@router.post("/api/connectors/email/accounts")
async def add_email_account(request: Request):
    c = _get_connector("email")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON")
    required = ["name", "host", "user", "password"]
    for f in required:
        if not body.get(f):
            raise HTTPException(400, f"'{f}' is required")
    acc = {
        "name": body["name"],
        "host": body["host"],
        "port": int(body.get("port", 993)),
        "user": body["user"],
        "password": body["password"],
        "ssl": body.get("ssl", True),
        "folders": body.get("folders", ["INBOX"]),
        "tags": body.get("tags", ["email"]),
    }
    accounts = c._get_accounts()
    accounts = [a for a in accounts if a.get("name") != acc["name"]]
    accounts.append(acc)
    c._config["accounts"] = accounts
    c._config["_configured"] = True
    c._config["_enabled"] = True
    c._save()
    _events.emit("connector", "add-account", "email", acc["name"])
    return {"status": "added", "name": acc["name"], "total": len(accounts)}


@router.delete("/api/connectors/email/accounts/{account_name}")
async def remove_email_account(account_name: str):
    c = _get_connector("email")
    accounts = c._get_accounts()
    before = len(accounts)
    accounts = [a for a in accounts if a.get("name") != account_name]
    if len(accounts) == before:
        raise HTTPException(404, f"Account '{account_name}' not found")
    c._config["accounts"] = accounts
    if not accounts:
        c._config["_configured"] = False
    c._save()
    _events.emit("connector", "remove-account", "email", account_name)
    return {"status": "removed", "name": account_name, "remaining": len(accounts)}


# --- Inbound Webhook ---

@router.post("/api/inbound/{token}")
async def inbound_webhook(token: str, payload: InboundPayload):
    expected = os.environ.get("CONTEXTPILOT_INBOUND_TOKEN")
    if expected is None:
        raise HTTPException(status_code=403, detail="Inbound webhooks not configured")
    if token != expected:
        raise HTTPException(status_code=403, detail="Invalid token")
    if not payload.key or not payload.key.strip():
        raise HTTPException(status_code=400, detail="Missing key")
    if not payload.value or not payload.value.strip():
        raise HTTPException(status_code=400, detail="Missing value")
    store = _get_memory_store()
    store.set(Memory(key=payload.key.strip(), value=payload.value.strip(), tags=payload.tags))
    return {"status": "ok", "key": payload.key.strip()}
