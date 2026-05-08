# Changelog

## v4.3.0 — 2026-05-08

Multi-expert review pass: security, code quality, architecture, and dead-code cleanup.
All 1542 tests green. ~250 LOC removed via consolidation and dead-code purge.

### Correctness Fixes
- **ProfileManager consistency** — `web/deps.py` now uses `ProfileManager().active_db_path`
  like the MCP server. Previously the web app stuck to a hard-coded `DEFAULT_DB_PATH`,
  meaning a profile switch from CLI did not take effect in the web UI.
- **Cross-process DB safety** — removed the `BEGIN IMMEDIATE / ROLLBACK` "WAL snapshot
  refresh" hotfix that conflicted with `VACUUM` and held write locks on every read.
  SQLite WAL already provides snapshot freshness on each new read in autocommit mode.
- **`_init_db` race-safe** — waits for any in-flight background indexing to finish
  before closing the connection (prevents segfault when profile is re-init'd while
  the indexer thread is iterating).
- **Stale `_db` references in routers** — 19 inline `from src.web.deps import _db`
  lookups across `memories.py`, `system.py`, `assembly.py`, `graph.py` replaced with
  `_get_db()` calls so router code always sees the live connection.
- **DB Re-init bug** — `_init_db()` now nulls out cached store singletons so they
  rebind to the new connection after a profile switch.
- **Thread-safe deps singletons** — `_get_*_store()` helpers now hold `_db_lock` when
  reading/writing module-level globals.

### Security
- **Webhook token timing-safe compare** — `hmac.compare_digest` instead of `!=`.
- **Webhook DNS-rebinding guard** — outbound webhook URLs are resolved and any IP
  matching the cloud-metadata range (169.254.169.254, AWS IMDSv6) is blocked.
  *LAN-private addresses (192.168/16, 10/8, 172.16/12) remain reachable so webhooks
  to home-server services keep working.*
- **CSP `unsafe-eval` removed** — HTMX does not need it.

### Code Quality
- **Schema migration guards removed** — `_has_pinned_column()`, `_has_expires_column()`,
  `_has_category_column()` and the `_extra_cols()` runtime SQL probes are gone now
  that schema v13 is the minimum (~50 LOC).
- **`MemoryStore.sources()` SQL-side aggregation** — N rows scan replaced with a
  `GROUP BY SUBSTR(...)` query.
- **Connector `_upsert` consolidation** — 5 nearly-identical `_upsert` methods in
  `gitea`, `github`, `notion`, `bitwarden`, `gdrive` removed; logic moved to
  `BaseConnector._upsert` taking a `meta_extra: dict` (~110 LOC).
- **Inline imports cleaned up** — 10+ `import` statements inside MCP tool functions
  hoisted to module top.
- **Dead-code sweep** — ~40 unused imports across 30 files (autoflake), dead
  defensive `hasattr(b.priority, 'value')`, unused `_time`, `Counter`, owner
  variable in `gitea.py`.
- **Type hints** — `category: str = None` → `Optional[str] = None` in
  `MemoryStore.list` and `VersionStore.record`.
- **Removed dead Rate-Limiter** — `web/rate_limit.py` was never wired up
  (`app.state.rate_limiter` was never set). Deleted, including its test file.

### Library Updates
- `mcp` 1.26 → 1.27, `fastapi` 0.135 → 0.136, `pydantic` 2.12 → 2.13,
  `uvicorn` 0.42 → 0.46, `starlette` 0.52 → 1.0, `click` 8.1 → 8.3,
  `python-multipart` 0.0.9 → 0.0.27, `tiktoken` 0.6 → 0.8.

### Misc
- `embeddings.py` import probe restored — `_backend = "transformer"` was always set
  even when `sentence_transformers` was missing because autoflake removed the import
  inside the try-block. Now uses an explicit `import sentence_transformers` probe.
- Test fix: `test_semantic_true_uses_hybrid` now patches `mcp_server.hybrid_search`
  (the actual call site) instead of `core.embeddings.hybrid_search`.

## v4.1.0 — 2026-04-01

Security hardening, bug fixes, and performance improvements. 22 bugs fixed, 94 new tests.

### Security Fixes
- **API Key Authentication** — optional `CONTEXTPILOT_API_KEY` env var protects all `/api/` endpoints
- **SSRF Protection** — webhook URLs validated against private IPs, metadata hosts, non-http schemes
- **SQL Injection Fix** — SQLite importer validates column names against actual table schema
- **XSS Fix** — Knowledge Graph tooltips now HTML-escaped
- **ZIP Path Traversal** — profile import rejects entries with `../../` paths
- **XXE Protection** — RSS parser uses `defusedxml` when available
- **CSP Headers** — Content-Security-Policy added to all responses
- **Upload Size Limit** — all upload endpoints capped at 50 MB
- **Credential Protection** — connector config files now `chmod 0600`
- **IMAP Error Sanitization** — exception messages no longer leak credentials

### Bug Fixes
- **Atomic Config Writes** — `~/.claude.json` and webhook configs use tempfile + rename
- **`wm.send()` AttributeError** — replaced with correct `wm.notify()` call
- **tiktoken Caching** — encoding object cached at module level (was re-created every call)
- **EventBus Thread Safety** — `emit()` uses `call_soon_threadsafe()` for asyncio queues
- **Assembler Deep Copy** — `assemble_tracked()` uses `deepcopy` to prevent mutation leakage
- **DB Migration Rollback** — each migration wrapped in SAVEPOINT with rollback on failure
- **FTS IN-clause Cap** — search limited to 500 FTS keys to prevent SQLite variable overflow
- **Telegram Offset Tracking** — `getUpdates` offset now persisted between syncs
- **`--db-path` CLI Fix** — path passed via env var so uvicorn respects it
- **MCP Error Logging** — replaced 7x `except Exception: pass` with `logger.warning()`
- **Embeddings Race Guard** — profile switch during indexing now detected and aborted

### Performance
- **SQL Aggregates** — `/health`, `/api/dashboard`, `/api/dashboard/stats` use `COUNT(*)` instead of loading all memories
- **PRAGMA busy_timeout** — 5s timeout prevents SQLITE_BUSY errors under concurrent load
- **Suggest-tags Pagination** — no longer loads entire memory store

### Stats
- 1052 tests (was 958), 62% coverage (was 58%)
- 22 bugs fixed across 3 severity batches
- `defusedxml>=0.7.1` added as dependency

## v4.0.0 — 2026-04-01

Major release: 12 new features, 147 new tests, hybrid semantic search, auto-context for Claude Code.

### New Features
- **Hybrid Semantic Search** — fuses FTS5 keyword + TF-IDF semantic scores with configurable weights. Available via `/api/semantic-search?mode=hybrid` and MCP `memory_search(semantic=True)`
- **Auto-Context MCP Tool** — `get_context_for_task(description)` finds relevant memories, assigns priorities, and assembles within a token budget automatically
- **Memory Auto-Capture** — `capture_learnings(learnings)` batch-saves session insights with auto-tagging and merge mode for existing keys
- **Memory Categories** — `persistent` (default), `session` (24h auto-TTL), `ephemeral` (1h auto-TTL). New DB schema v13
- **Memory Relations** — bidirectional cross-references with `GET /api/memories/{key}/related` and MCP `get_related_memories(key)`
- **Backup & Restore** — create, list, restore, delete backups via `POST/GET/DELETE /api/backups`
- **Analytics Dashboard** — top memories, tag stats, connector stats, memory growth via `/api/analytics/*` endpoints
- **Inbound Webhooks** — `POST /api/inbound/{token}` for pushing memories from external services (n8n, Home Assistant)

### Improvements
- **Deduplicated `_detect_compress_hint`** — extracted to shared `src/core/compress_detect.py`, removed 3 copies
- **Fixed double-query in search** — new `search_count()` method replaces full table scan for pagination counts
- **ProfileManager caching** — singleton with thread-safe double-check locking, invalidation on mutations
- **DependencyDetector** — word-boundary matching replaces substring check, minimum key length guard (>= 4 chars)
- **26 MCP tools** (was 23): +`get_context_for_task`, +`capture_learnings`, +`get_related_memories`

### Stats
- 958 tests (was 811), 58% coverage (was 55%)
- 13 new files, 10 modified files
- Schema v13 (was v12)

## v3.5.1 — 2026-03-29

MCP compatibility fix for Claude Code.

- **Fix: MCP tools use simple types instead of Optional unions** — `anyOf`
  schemas with `null` caused Claude Code's MCP client to reject valid
  requests with `-32602: Invalid request parameters`
- Replaced `Optional[str]` with `str = ""` and `Optional[List[str]]` with
  `List[str] = []` in all MCP tool signatures

## v3.5.0 — 2026-03-29

Profile-aware startup, MCP server fixes.

- **Fix: Web app uses active profile on startup** — previously always loaded
  default DB, requiring manual profile switch after container restart
- **Fix: MCP server uses active profile DB** — previously hardcoded to
  default data.db, causing memory_set/search to operate on wrong profile
- **Fix: MCP server reports app version** — was reporting mcp library version
  (1.26.0) instead of ContextPilot version
- **Central APP_VERSION** — single source of truth for Web + MCP version
- **14 new regression tests** for profile startup behavior

## v3.4.0 — 2026-03-27

Memory UX overhaul, DB cleanup, Profile redesign.

- **Memory page redesign**: sidebar layout with filters, accordion-style expandable items
- **New Memory modal** with markdown editor (EasyMDE)
- **Icon buttons** (pin/edit/delete) replace text buttons in memory list
- **Pin icon** (SVG star) replaces "P" text badge
- **Profile switcher redesign**: clean header dropdown with user icon
- **Profile management** (rename/delete/import) moved to Settings page
- **DB stats**: separate embeddings size from core DB size
- **Schema v12**: enable auto_vacuum=INCREMENTAL, drop unused tables
  (skill_profiles, skill_budget_allocation), remove redundant index
- Responsive layout: max-width 1400px, breakpoints for tablet/mobile
- Favicon (inline SVG compass)
- Docker Hub: published as `applehell/contextpilot`

## v3.3.0 — 2026-03-27

Setup Wizard, GitHub Connector, Memory TTL, Settings Page.

- **Setup Wizard**: 7-step animated onboarding for fresh installs
- **GitHub Connector**: track public repos — releases, READMEs, issues, metadata
- **Gitea Connector expanded**: packages/containers, releases, wikis, repo metadata
- **Memory TTL**: time-to-live with auto-expiry, lifetime indicators, filters
  (permanent/expiring/urgent), bulk TTL editing, connector TTL config
- **Settings Page**: MCP register/deregister, DB maintenance (vacuum, FTS rebuild),
  import/export hub, scheduler control, system info, danger zone
- **Skeleton loading**: shimmer animations across all loading states
- Docker: Gitea Container Registry integration
- DB migration v11 (expires_at column)

## v3.2.0 — 2026-03-26

Dark Mode, Email Connector, Smart UI.

- Dark mode with system preference detection
- Email connector (IMAP)
- Memory diff view
- Profile export/import as ZIP
- Dependency graph visualization

## v3.1.0 — 2026-03-24

Profile isolation: switching profiles changes ALL data.

- Profiles now control memories, connectors, folders, webhooks, embeddings,
  templates, assembly, dashboard, secrets scan — complete isolation
- 13 integration tests verify every aspect of profile isolation
- Connector plugin architecture with data_dir parameter per profile
- ConnectorRegistry.reload() on profile switch
- Scheduler stops on profile switch (prevents cross-profile sync)
- 574 tests total

## v3.0.0 — 2026-03-24

Major release: Knowledge Sources, Live Activity, UI Rewrite.

### New Features
- **Folder Sources** — Map external directories as knowledge sources with content-hash deduplication, recursive scanning, extension filtering, and auto-removal of deleted files
- **Paperless-ngx Connector** — Sync OCR'd documents via REST API with tag-filtered sync, connection test UI, and content-hash tracking
- **Live Activity Feed** — Real-time SSE event stream tracking all API calls, memory operations, imports, scans, and syncs with color-coded category badges
- **Health Endpoint** — `GET /health` returns uptime, version, memory/token counts, skill status, storage size, disk usage, request metrics
- **Profile Knowledge Import** — Create new profiles with memories copied from existing profiles (all or filtered by tags)
- **Welcome Screen** — Animated onboarding overlay for first-time users and new profiles

### UI Rewrite
- Complete redesign: light theme with Inter font, CSS variables, warm accent colors
- Animated bot orb in header (pulses on API activity)
- Tab navigation via data attributes (no inline onclick)
- Modal system with footer buttons
- Cache-busting for static assets
- All UI strings in English

### Infrastructure
- EventBus singleton with async SSE subscriber model
- Docker healthcheck uses `/health` endpoint
- Docker deployment guide with NAS/remote server instructions (DOCKER.md)
- 3 new test suites: EventBus, FolderManager, PaperlessConnector

## v2.2.0 — 2026-03-23

- Memory Edit-Modal (Klick zum Anzeigen, Edit-Button zum Bearbeiten)
- Profil umbenennen (Rename-Button im Header)
- Copilot.md Import (Upload-Button im Dashboard)
- Bulk-Operationen (Mehrfachauswahl + Sammelloeschen)
- Memory Export als JSON (alle oder nach Tag)
- Klickbare Tags zum Filtern
- Context Preview Budget-Bug gefixt

## v2.1.0 — 2026-03-23

- README komplett neu geschrieben
- VSCode Debug-Configs (7 Launch-Configs, Docker Tasks)
- dist/ Build-Artefakte aufgeraeumt

## v2.0.0 — 2026-03-23

Kompletter Umbau: Web-only Anwendung, Desktop-GUI entfernt.

- PySide6 Desktop-App entfernt (24 Dateien, ~5000 Zeilen)
- Web-App ist jetzt der einzige Betriebsmodus
- Dockerfile + docker-compose.yml fuer Container-Deployment
- MCP Server On-Demand (SSE, nur aktiv wenn App laeuft)
- Profile-System (mehrere isolierte Wissensdatenbanken)
- Secrets Scanner (Passwoerter, API Keys, Tokens erkennen)
- Auto-Compress Hints fuer Memories
- Memory Activity Tracking (NEU/UPD Badges)
- Knowledge Graph mit Suche (vis.js)
- Dashboard mit Status-Cards, Skill Monitor, Activity Feed
- File-Import (CLAUDE.md, Copilot.md, SQLite) via Upload

## v1.0.0 — 2026-03-22

Erste vollstaendige Version mit Web-App, CLI, MCP Server und Desktop-GUI.

## v0.1.0–v0.5.0

Entwicklungsphasen: Core Engine, Compressoren, MCP Server, Storage, Web-API.
