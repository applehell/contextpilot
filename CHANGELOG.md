# Changelog

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
