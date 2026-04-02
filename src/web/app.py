"""Context Pilot Web App -- FastAPI backend with HTMX frontend."""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.core.log import get_logger, setup_logging
from src.core.skill_registry import SkillRegistry
from src.storage.profiles import ProfileManager

import src.web.deps as _deps

logger = get_logger("web.app")

from src.web.deps import (
    API_KEY,
    WEB_DIR,
    _DATA_DIR,
    _events,
    _estimate_total_tokens,
    _get_db,
    _get_memory_store,
    _init_db,
    _trigger_background_index,
    MAX_UPLOAD_BYTES,
)

from src.web.routers import (
    memories,
    connectors,
    profiles,
    assembly,
    analytics,
    system,
    events,
    graph,
    folders,
    projects,
    import_routes,
)


def create_app(db_path: Optional[Path] = None) -> FastAPI:
    setup_logging()
    _init_db(db_path)

    from src.interfaces.mcp_server import APP_VERSION
    app = FastAPI(title="Context Pilot", version=APP_VERSION)
    logger.info("ContextPilot started, version=%s, db=%s", APP_VERSION, db_path)

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

    @app.middleware("http")
    async def api_version_rewrite(request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/v1/"):
            scope = request.scope
            scope["path"] = "/api/" + path[8:]
            scope["raw_path"] = scope["path"].encode("ascii")
        return await call_next(request)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com https://cdn.jsdelivr.net https://fonts.googleapis.com; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self' https://unpkg.com https://cdn.jsdelivr.net https://fonts.gstatic.com"
        )
        return response

    @app.middleware("http")
    async def api_key_auth(request: Request, call_next):
        import sys
        _api_key = sys.modules[__name__].API_KEY
        if _api_key and request.url.path.startswith("/api/") and request.url.path not in ("/health",):
            key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
            if key != _api_key:
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
        return await call_next(request)

    # --- HTML ---

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    # --- Health ---

    _start_time = time.time()
    _request_count = {"total": 0, "errors": 0}

    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        rl = getattr(app.state, "rate_limiter", None)
        if rl is None or not request.url.path.startswith("/api/"):
            return await call_next(request)
        client_ip = request.client.host if request.client else "unknown"
        if not rl.is_allowed(client_ip):
            retry_after = rl.get_retry_after(client_ip)
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        response = await call_next(request)
        response.headers["X-RateLimit-Remaining"] = str(rl.remaining(client_ip))
        return response

    @app.middleware("http")
    async def _count_requests(request: Request, call_next):
        _request_count["total"] += 1
        response = await call_next(request)
        if response.status_code >= 500:
            _request_count["errors"] += 1
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/events/stream", "/api/events"):
            _events.emit("api", request.method.lower(), path)
        return response

    @app.get("/health")
    async def health():
        import platform
        import os
        import shutil

        store = _get_memory_store()
        memory_count = store.count()
        total_tokens = _estimate_total_tokens(_get_db())

        registry = SkillRegistry.instance()
        all_skills = registry.list_all()
        alive_skills = registry.list_alive()

        pm = ProfileManager()
        profiles_list = pm.list()

        uptime = time.time() - _start_time
        days, rem = divmod(int(uptime), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        uptime_str = f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"

        data_dir = Path(os.environ.get("CONTEXTPILOT_DATA_DIR", str(Path.home() / ".contextpilot")))
        db_size = 0
        embeddings_size = 0
        if data_dir.exists():
            for f in data_dir.rglob("*.db"):
                sz = f.stat().st_size
                if "embedding" in f.name.lower():
                    embeddings_size += sz
                else:
                    db_size += sz
        disk = shutil.disk_usage(str(data_dir)) if data_dir.exists() else None

        db = _get_db()
        schema_version = db.conn.execute("PRAGMA user_version").fetchone()[0]

        # Connector health
        from src.connectors.registry import ConnectorRegistry
        from src.web.deps import _get_profile_dir, _index_state
        try:
            connector_reg = ConnectorRegistry.instance(_get_profile_dir())
            connector_list = connector_reg.list()
            last_sync_errors = 0
            for c in connector_list:
                try:
                    info = c.info()
                    hist = info.get("sync_history", [])
                    if hist and hist[0].get("errors", 0) > 0:
                        last_sync_errors += 1
                except Exception:
                    pass
            connectors_info = {
                "total": len(connector_list),
                "configured": sum(1 for c in connector_list if c.configured),
                "enabled": sum(1 for c in connector_list if c.enabled),
                "last_sync_errors": last_sync_errors,
            }
        except Exception:
            connectors_info = None

        # MCP status
        try:
            from src.core.claude_config import is_registered, get_current_config
            mcp_config = get_current_config()
            mcp_info = {
                "registered": is_registered(),
                "port": mcp_config.get("port") if mcp_config else None,
            }
        except Exception:
            mcp_info = None

        # Embeddings status
        embeddings_info = {
            "status": _index_state.get("status", "unknown"),
            "indexed": _index_state.get("indexed", 0),
            "backend": _index_state.get("backend", "unknown"),
        }

        # Backup status
        try:
            from src.core.backup import BackupManager as _HealthBM
            _hbm = _HealthBM(pm.active_data_dir)
            _hb_list = _hbm.list_backups()
            _hb_age = _hbm.backup_age_hours()
            backup_info = {
                "last_backup_hours_ago": round(_hb_age, 1) if _hb_age is not None else None,
                "backup_count": len(_hb_list),
                "needs_backup": _hbm.needs_backup(max_age_hours=24),
            }
        except Exception:
            backup_info = None

        # Determine overall status
        status = "healthy"
        if connectors_info and connectors_info.get("last_sync_errors", 0) > 0:
            status = "degraded"
        if disk and disk.free / disk.total < 0.1:
            status = "degraded"

        return {
            "status": status,
            "version": app.version,
            "uptime": uptime_str,
            "uptime_seconds": int(uptime),
            "python": platform.python_version(),
            "platform": f"{platform.system()} {platform.machine()}",
            "pid": os.getpid(),
            "db_schema_version": schema_version,
            "requests": {
                "total": _request_count["total"],
                "errors": _request_count["errors"],
            },
            "memories": {
                "count": memory_count,
                "tokens": total_tokens,
                "tags": len(store.tags()),
            },
            "skills": {
                "total": len(all_skills),
                "alive": len(alive_skills),
            },
            "profiles": {
                "count": len(profiles_list),
                "active": pm.active_name,
            },
            "storage": {
                "db_size_bytes": db_size,
                "db_size_mb": round(db_size / (1024 * 1024), 2),
                "embeddings_size_mb": round(embeddings_size / (1024 * 1024), 2),
                "disk_free_gb": round(disk.free / (1024**3), 2) if disk else None,
                "disk_total_gb": round(disk.total / (1024**3), 2) if disk else None,
            },
            "connectors": connectors_info,
            "backup": backup_info,
            "mcp": mcp_info,
            "embeddings": embeddings_info,
        }

    # --- API Version ---

    @app.get("/api/version")
    async def api_version():
        return {
            "current": "v1",
            "supported": ["v1"],
            "deprecation_notice": None,
        }

    # --- Include all routers ---

    app.include_router(memories.router)
    app.include_router(connectors.router)
    app.include_router(profiles.router)
    app.include_router(assembly.router)
    app.include_router(analytics.router)
    app.include_router(system.router)
    app.include_router(events.router)
    app.include_router(graph.router)
    app.include_router(folders.router)
    app.include_router(projects.router)
    app.include_router(import_routes.router)

    # Cleanup expired memories on startup
    try:
        store = _get_memory_store()
        expired = store.cleanup_expired()
        if expired > 0:
            _events.emit("system", "ttl-cleanup", f"{expired} expired memories removed at startup")
    except Exception:
        pass

    # Auto-backup if needed (max once per 24h)
    try:
        from src.core.backup import BackupManager as _StartupBM
        _bm = _StartupBM(ProfileManager().active_data_dir)
        if _bm.needs_backup(max_age_hours=24):
            _bm.auto_backup(max_backups=7)
            _events.emit("system", "auto-backup", "automatic backup created at startup")
    except Exception:
        pass

    # Build search index in background on startup
    _trigger_background_index()

    return app


_custom_db = os.environ.get("CONTEXTPILOT_DB_PATH")
app = create_app(Path(_custom_db) if _custom_db else ProfileManager().active_db_path)
