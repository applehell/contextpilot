<p align="center">
  <img src="https://img.shields.io/badge/version-4.1.1-blue?style=flat-square" alt="Version">
  <img src="https://img.shields.io/docker/pulls/applehell/contextpilot?style=flat-square&color=blue" alt="Docker Pulls">
  <img src="https://img.shields.io/docker/image-size/applehell/contextpilot/latest?style=flat-square&color=blue" alt="Image Size">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <a href="https://contextpilot.net"><img src="https://img.shields.io/badge/web-contextpilot.net-orange?style=flat-square" alt="Website"></a>
  <a href="https://hub.docker.com/r/applehell/contextpilot"><img src="https://img.shields.io/badge/docker-applehell%2Fcontextpilot-2496ED?style=flat-square&logo=docker&logoColor=white" alt="Docker Hub"></a>
</p>

<h1 align="center">Context Pilot</h1>

<p align="center">
  <strong>Smart context and memory management for AI workflows</strong><br>
  Web App + MCP Server for Claude Code
</p>

<p align="center">
  <a href="https://contextpilot.net">Website</a> &bull;
  <a href="#quick-start">Quick Start</a> &bull;
  <a href="#features">Features</a> &bull;
  <a href="#docker">Docker</a> &bull;
  <a href="#mcp-server">MCP Server</a> &bull;
  <a href="#api-reference">API Reference</a>
</p>

---

## What is Context Pilot?

Context Pilot gives your AI assistant **persistent, structured memory**. It stores knowledge as searchable memories with tags, connects to external sources (GitHub, Gitea, Paperless-ngx, Email, local folders), and serves context to Claude Code via an MCP Server — all through a clean web UI.

**Key idea:** Instead of repeating yourself, teach your AI once. Context Pilot remembers.

---

## Quick Start

### Docker (recommended)

```bash
docker pull applehell/contextpilot:latest
docker run -d --name context-pilot \
  -p 8080:8080 -p 8400:8400 \
  -v context-pilot-data:/data \
  applehell/contextpilot:latest
```

> **Web UI:** http://localhost:8080 &nbsp;&nbsp;|&nbsp;&nbsp; **Health:** http://localhost:8080/health

### Docker Compose

```yaml
services:
  context-pilot:
    image: applehell/contextpilot:latest
    container_name: context-pilot
    restart: unless-stopped
    ports:
      - "8080:8080"   # Web UI
      - "8400:8400"   # MCP SSE Server
    volumes:
      - context-pilot-data:/data
      - /path/to/docs:/mnt/docs:ro    # optional: folder for indexing
    environment:
      - CONTEXTPILOT_DATA_DIR=/data

volumes:
  context-pilot-data:
```

```bash
docker compose up -d
```

### From Source

```bash
git clone https://github.com/applehell/contextpilot.git
cd contextpilot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.web
```

### CLI Options

```bash
python -m src.web                          # Web UI + MCP Server
python -m src.web --no-mcp                 # Web UI only
python -m src.web --port 9090              # Custom web port
python -m src.web --mcp-port 8500          # Custom MCP port
```

---

## Features

### Web UI — 8 Tabs

| Tab | Description |
|---|---|
| **Dashboard** | Stats cards, top tags, size distribution, connector health, import, live activity (SSE), context preview |
| **Memories** | Full CRUD with Markdown editor, search, filters, tags, TTL, pin, bulk ops, compact view, collapsible sidebar |
| **Skills** | Connected MCP skill registry with status indicators |
| **Graph** | Interactive knowledge graph (vis.js) with search, physics toggle, navigation buttons, node detail panel |
| **Secrets** | Scan memories for API keys, passwords, tokens (OWASP patterns) |
| **Sources** | Connector Store (17 sources), folder mapping, webhooks, auto-sync scheduler |
| **Assembler** | Templates, auto-suggest, 6 compressors, manual block assembly, export (CLAUDE.md, Markdown) |
| **Settings** | Profiles, MCP server control, DB maintenance, import/export hub, scheduler, system info |

### Memories

| Capability | Details |
|---|---|
| **Create & Edit** | Modal editor with Markdown support (EasyMDE), live preview |
| **Search** | Full-text search via SQLite FTS5 + hybrid semantic search |
| **Tags** | Clickable tag filtering, color-coded top tags, bulk tag operations |
| **Categories** | `persistent`, `session` (24h TTL), `ephemeral` (1h TTL) — auto-expiry |
| **TTL** | Time-to-live with auto-expiry, color-coded lifetime indicators (urgent/soon/limited/permanent) |
| **Pin** | Pin important memories to the top |
| **Relations** | Cross-references between memories, bidirectional graph edges |
| **Versioning** | Track changes with diff view, restore previous versions |
| **Compact View** | Toggle between detail and compact mode (persisted in localStorage) |
| **Bulk Ops** | Multi-select, bulk delete, bulk TTL, bulk tag editing |
| **Backup** | Create, list, restore, delete backups via API |
| **Export** | JSON, CLAUDE.md, Markdown export (all or filtered by tag) |

### Connector Store — 17 Sources

| Category | Connector | What it syncs |
|---|---|---|
| **Documents** | Paperless-ngx | OCR'd documents via REST API |
| | Microsoft Excel | Spreadsheets as markdown tables (openpyxl) |
| | Google Drive | Docs, Sheets, Slides via service account |
| **Development** | GitHub | Repos, releases, READMEs, issues |
| | Gitea | Self-hosted repos, wikis, packages |
| **Knowledge** | Obsidian Vault | Markdown notes with frontmatter |
| | Bookmarks | Web pages fetched and indexed |
| | RSS / Atom Feeds | Feed articles (no external deps) |
| | Notion | Pages and databases via API |
| | KeePass | Notes, titles, URLs only (never passwords) |
| | Bitwarden | Secure Notes only (never logins) |
| **Communication** | Email (IMAP) | Emails from any IMAP server |
| | Telegram | Bot messages via Bot API |
| | Microsoft Teams | Channel messages via Graph API |
| **Infrastructure** | Kubernetes | Deployments, services, configmaps (never secrets) |
| | Dockge | Docker Compose stacks (env values redacted) |
| **Smart Home** | Home Assistant | Automations, scenes, entities |
| **Local** | Folder Mapping | Directories with extension filter, PDF extraction |

Each connector tracks **sync history** (last 20 runs), supports **TTL** for auto-expiring synced memories, and exposes a **health dashboard** (`GET /api/connectors/health`).

### Import

Upload files directly from the dashboard or settings:

| Format | Source |
|---|---|
| `CLAUDE.md` | Claude Code instruction files |
| `Copilot.md` | GitHub Copilot instruction files |
| `SQLite .db` | memory-mcp MCP Server databases |
| `JSON` | Context Pilot JSON export |

### Profiles — Complete Isolation

Every profile is a fully isolated workspace:

```
profiles/{name}/
  data.db              <- Memories, tags, FTS index, templates, relations, versions, activity
  connector_*.json     <- Connector configs (Paperless, GitHub, Gitea, Email, ...)
  folders.json         <- Folder source configuration
  webhooks.json        <- Webhook configuration
  embeddings.db        <- Semantic search index (TF-IDF)
```

- Switch instantly via header dropdown
- Create with knowledge import from existing profiles
- Export/import as ZIP archive (full profile backup & restore)
- Rename, delete, duplicate from Settings

### Context Assembler

The Assembler optimizes your memories for AI consumption within a token budget:

| Feature | Description |
|---|---|
| **Templates** | Save reusable filter + budget combos (tag filter, key prefix, token budget) |
| **Auto-Suggest** | Analyzes memory clusters and proposes templates automatically |
| **Compression** | 6 compressors: bullet extract, code compact, YAML struct, Mermaid, table, dedup |
| **Weight-Based Priority** | Blocks ranked by usage history and feedback scores |
| **Duplicate Detection** | Find and remove duplicate or near-duplicate memories |
| **Export** | Generate CLAUDE.md or Markdown from templates |
| **MCP Integration** | `assemble_template`, `suggest_templates`, `list_templates` tools |

### More Features

| Feature | Description |
|---|---|
| **Setup Wizard** | 7-step animated onboarding for fresh installs |
| **Knowledge Graph** | Interactive vis.js network with search, physics toggle, navigation buttons |
| **Secrets Scanner** | Detects API keys, passwords, tokens, private keys (OWASP patterns) |
| **Live Activity** | Real-time SSE event stream with color-coded category badges |
| **Keyboard Shortcuts** | `?` for cheatsheet, `1`-`8` tabs, `Ctrl+K` search, `N` new memory |
| **Global Search** | `Ctrl+K` fuzzy search across memories, templates, connectors |
| **Dark Mode** | System preference detection + manual toggle, smooth transitions |
| **Compact View** | Toggle dense memory list, persisted per browser |
| **Collapsible Filters** | Sidebar sections fold to save space |
| **Skeleton Loading** | Shimmer animations across all loading states |
| **Responsive** | Desktop, tablet, mobile with bottom nav bar and safe area insets |
| **PWA Ready** | Web app manifest, standalone display mode |
| **Security** | DOMPurify (XSS), Security Headers, non-root Docker, secrets redaction |
| **Inbound Webhooks** | Push memories from external services (n8n, Home Assistant) |
| **Auto-Sync Scheduler** | Automatic connector sync on configurable intervals |
| **Analytics** | Top memories, tag stats, connector stats, memory growth, token usage |

---

## MCP Server

Context Pilot includes a built-in MCP Server (Model Context Protocol) that lets Claude Code access your memories directly.

### 20 MCP Tools

```
Claude Code --> MCP Server (SSE, Port 8400)
                   |
                   |-- Memory CRUD
                   |     memory_set / memory_get / memory_delete
                   |     memory_search / memory_list
                   |
                   |-- Skills
                   |     register_skill / unregister_skill
                   |     list_registered_skills / heartbeat
                   |     get_skill_context
                   |
                   |-- Context Assembly
                   |     assemble_context / list_blocks
                   |     assemble_template / list_templates / suggest_templates
                   |     get_context_for_task
                   |
                   |-- Intelligence
                   |     capture_learnings / get_related_memories
                   |     submit_feedback / get_block_weight
```

**Profile-aware:** The MCP server follows profile switches in real-time — no restart needed.

**How it works:**
1. Start Context Pilot -> MCP Server starts on port 8400
2. Auto-registers in `~/.claude.json`
3. Claude Code can now read/write your memories
4. Stop app -> auto-deregistration

---

## Claude Code Plugin

The **context-pilot plugin** adds deep integration with Claude Code — auto-profile detection, slash commands, and a skill file that teaches Claude how to use ContextPilot optimally.

### Installation

```bash
git clone https://github.com/applehell/context-pilot-plugin.git \
  ~/.claude/plugins/cache/context-pilot/1.0.0
```

### What It Does

| Component | Description |
|---|---|
| **SessionStart Hook** | Auto-detects the right profile based on your working directory |
| **`/context-pilot`** | Dashboard, template assembly, search, profile switch, suggest, status |
| **`/context-pilot-learn`** | Quick-save a memory from your session |
| **Skill File** | Teaches Claude all 20 MCP tools, best practices, and when to use what |
| **MCP Config** | Auto-registers the ContextPilot MCP server |

### Commands

```bash
/context-pilot                    # Show dashboard (profile, memories, templates)
/context-pilot bugfix-context     # Assemble the "bugfix-context" template
/context-pilot search docker      # Search memories for "docker"
/context-pilot profile smarthome  # Switch to smarthome profile
/context-pilot suggest            # Auto-suggest new templates
/context-pilot status             # Show connector health

/context-pilot-learn infra/nginx Reverse proxy config for port 443 || infra,nginx
```

### Profile Auto-Detection

| Working Directory Contains | Profile |
|---|---|
| `contextpilot` or `context-pilot` | `software-development` |
| `homeassistant` or `home-assistant` | `smarthome` |
| *(default)* | Keep current profile |

### Configuration

```bash
# Shell config (~/.claude/context-pilot.conf)
CONTEXTPILOT_URL=http://your-server:8080
CONTEXTPILOT_MCP_URL=http://your-server:8400/sse
```

---

## Docker

### Available on [Docker Hub](https://hub.docker.com/r/applehell/contextpilot)

| Tag | Description |
|---|---|
| [`applehell/contextpilot:latest`](https://hub.docker.com/r/applehell/contextpilot/tags) | Latest stable release |

### Volumes

| Mount | Purpose |
|---|---|
| `/data` | Database, profiles, configs (persistent) |
| `/mnt/docs` | Optional: local folder for indexing (read-only) |

### Build from Source

```bash
git clone https://github.com/applehell/contextpilot.git
cd contextpilot
docker build -t contextpilot .
docker compose up -d
```

---

## Architecture

```
Browser --> Web UI (FastAPI, Port 8080)
               |-- Dashboard        Stats, Import, Live Activity SSE, Context Preview
               |-- Memories         CRUD, Search, Editor, Tags, TTL, Compact View
               |-- Skills           Skill Registry, Status Indicators
               |-- Knowledge Graph  Interactive vis.js network, Search, Navigation
               |-- Secrets          Scanner, Redacted View
               |-- Sources          Connector Store (17), Folder Mapping, Webhooks, Scheduler
               |-- Assembler        Templates, Auto-Suggest, Compression, Export
               |-- Settings         Profiles, MCP, DB, Import/Export, Scheduler

Claude Code --> MCP Server (SSE, Port 8400)
                   |-- 20 tools: memory CRUD, search, templates, assembly,
                   |   skill registry, feedback, context-for-task, learnings
                   |
            --> Plugin (context-pilot)
                   |-- SessionStart hook (auto-profile detection)
                   |-- /context-pilot + /context-pilot-learn commands
                   |-- Skill file (best practices + tool guidance)

Connectors --> 17 sources (GitHub, Gitea, Paperless, Obsidian, Email,
               Notion, Teams, Telegram, RSS, Excel, Google Drive,
               KeePass, Bitwarden, Kubernetes, Dockge, Bookmarks, HA)

Storage --> SQLite (WAL mode + FTS5, Schema v13)
```

### Data Paths

```
# Local
~/.contextpilot/
  profiles.json                <- Profile registry
  profiles/<name>/data.db      <- Per-profile database + configs

# Docker (CONTEXTPILOT_DATA_DIR=/data)
/data/
  profiles.json
  profiles/<name>/data.db
```

---

## API Reference

<details>
<summary><strong>Core</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | System metrics and health check |
| `/api/dashboard` | GET | Aggregated dashboard stats |
| `/api/dashboard/stats` | GET | Detailed stats (tags, sizes, growth) |
| `/api/mcp-status` | GET | MCP server registration status |
| `/api/setup-status` | GET | Fresh install detection |

</details>

<details>
<summary><strong>Memories</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/memories` | GET | List memories (pagination, sort, source filter) |
| `/api/memories` | POST | Create memory |
| `/api/memories/{key}` | GET | Read single memory |
| `/api/memories/{key}` | PUT | Update memory |
| `/api/memories/{key}` | DELETE | Soft-delete memory (trash) |
| `/api/memories/search` | GET | Full-text search + tag/source filter |
| `/api/memories/sources` | GET | List memory sources with counts |
| `/api/memories/category-stats` | GET | Memory count per category |
| `/api/memories/{key}/related` | GET | Related memories (cross-references) |
| `/api/memories/{key}/versions` | GET | Version history |
| `/api/memories/{key}/pin` | POST | Pin/unpin memory |
| `/api/memories/bulk-delete` | POST | Bulk delete |
| `/api/memories/bulk-ttl` | POST | Bulk TTL update |
| `/api/memories/bulk-tag` | POST | Bulk tag operations |
| `/api/semantic-search` | GET | Hybrid/semantic/keyword search (mode param) |
| `/api/export-memories` | GET | Export as JSON |
| `/api/memory-tags` | GET | All tags |
| `/api/memory-presets` | GET | Quick filter presets |

</details>

<details>
<summary><strong>Connectors</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/connectors` | GET | List all connectors with config and schema |
| `/api/connectors/{name}` | GET | Connector details + schema |
| `/api/connectors/{name}/setup` | POST | Configure connector |
| `/api/connectors/{name}` | PUT | Update connector config |
| `/api/connectors/{name}/test` | POST | Test connection |
| `/api/connectors/{name}/sync` | POST | Sync data |
| `/api/connectors/{name}/enable` | POST | Enable/disable |
| `/api/connectors/{name}/history` | GET | Sync history (last 20) |
| `/api/connectors/{name}` | DELETE | Remove connector config |
| `/api/connectors/health` | GET | Health dashboard for all connectors |
| `/api/folders` | GET/POST | List/add folder sources |
| `/api/folders/{name}` | PUT/DELETE | Update/remove folder source |
| `/api/folders/{name}/scan` | POST | Scan single folder |
| `/api/folders/scan-all` | POST | Scan all folders |

</details>

<details>
<summary><strong>Templates & Assembly</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/templates` | GET/POST | List/create templates |
| `/api/templates/{name}` | DELETE | Delete template |
| `/api/templates/{name}/assemble` | POST | Assemble with compression + weighting |
| `/api/templates/suggest` | GET | Auto-suggest templates from memory clusters |
| `/api/assemble` | POST | Manual block assembly |
| `/api/estimate` | POST | Token estimation |
| `/api/test-compress` | POST | Test compressor |
| `/api/duplicates` | GET | Find duplicate memories |
| `/api/preview-context` | POST | Preview context assembly with budget |
| `/api/export-claude-md` | GET | Export as CLAUDE.md |
| `/api/export-markdown` | GET | Export as Markdown |

</details>

<details>
<summary><strong>Profiles</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/profiles` | GET/POST | List/create profiles |
| `/api/profiles/{id}/switch` | POST | Switch active profile (by ID) |
| `/api/profiles/{name}` | PUT/DELETE | Rename/delete |
| `/api/profiles/{name}/duplicate` | POST | Duplicate profile |
| `/api/profiles/{name}/export` | GET | Export profile as ZIP |
| `/api/profiles/import` | POST | Import profile from ZIP |

</details>

<details>
<summary><strong>Events & Security</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/events` | GET | Recent events |
| `/api/events/stream` | GET | SSE real-time stream |
| `/api/events/stats` | GET | Event statistics |
| `/api/sensitivity` | GET | Secrets scan |
| `/api/redacted?key=...` | GET | Redacted memory view |
| `/api/knowledge-graph` | GET | Graph data (vis.js format) |

</details>

<details>
<summary><strong>Import</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/import/claude-md` | POST | Upload CLAUDE.md |
| `/api/import/copilot-md` | POST | Upload Copilot.md |
| `/api/import/sqlite` | POST | Upload SQLite DB |
| `/api/import/json` | POST | Upload JSON export |

</details>

<details>
<summary><strong>Analytics, Backup & Webhooks</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/analytics/summary` | GET | Overview dashboard data |
| `/api/analytics/top-memories` | GET | Most accessed memories |
| `/api/analytics/top-tags` | GET | Most frequent tags |
| `/api/analytics/connector-stats` | GET | Per-connector statistics |
| `/api/analytics/memory-growth` | GET | Daily memory count growth |
| `/api/backups` | GET/POST | List/create backups |
| `/api/backups/{filename}/restore` | POST | Restore backup |
| `/api/backups/{filename}` | DELETE | Delete backup |
| `/api/webhooks` | GET/POST | List/create webhooks |
| `/api/webhooks/{id}` | PUT/DELETE | Update/delete webhook |
| `/api/inbound/{token}` | POST | Inbound webhook (push memories) |

</details>

<details>
<summary><strong>Maintenance</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/maintenance/db-stats` | GET | Database statistics |
| `/api/maintenance/vacuum` | POST | Compact database |
| `/api/maintenance/rebuild-fts` | POST | Rebuild search index |
| `/api/maintenance/cleanup-trash` | POST | Remove old trash entries |
| `/api/maintenance/cleanup-expired` | POST | Remove expired memories |
| `/api/trash` | GET | List trashed memories |
| `/api/trash/{key}/restore` | POST | Restore from trash |
| `/api/trash/purge` | POST | Purge all trash |
| `/api/mcp/register` | POST | Register MCP in ~/.claude.json |
| `/api/mcp/deregister` | POST | Deregister MCP |
| `/api/scheduler/*` | GET/POST | Auto-sync scheduler control |

</details>

---

## Project Structure

```
src/
  core/                        Core logic
    assembler.py               3-phase token-budget assembler
    analytics.py               Usage analytics engine
    backup.py                  Backup & restore manager
    block.py                   Block data model
    claude_config.py           ~/.claude.json reader/writer
    compress_detect.py         Shared compression hint detection
    compressors/               6 compressors (bullet, code, yaml, mermaid, table, dedup)
    context.py                 Context builder for auto-assembly
    dependency_detector.py     Cross-memory dependency detection
    duplicates.py              Duplicate / near-duplicate finder
    embeddings.py              TF-IDF embeddings + hybrid search
    events.py                  Global EventBus with SSE broadcast
    relevance.py               Relevance scoring engine
    scheduler.py               Auto-sync scheduler (APScheduler)
    secrets.py                 Secrets detector (OWASP patterns)
    skill_registry.py          MCP skill lifecycle tracker
    token_budget.py            tiktoken wrapper
    webhooks.py                Inbound webhook processor
    weight_adjuster.py         Usage-based weight adjustment
  connectors/                  17 external service connectors
    github.py, gitea.py        Development sources
    paperless.py, excel.py     Document sources
    gdrive.py                  Google Drive (service account JWT)
    obsidian.py, notion.py     Knowledge sources
    rss.py, bookmarks.py       Web sources
    keepass.py, bitwarden.py   Secure notes (never passwords)
    email_imap.py, telegram.py Communication sources
    teams.py                   Microsoft Teams (Graph API)
    kubernetes.py, dockge.py   Infrastructure sources
    homeassistant.py           Smart Home source
  storage/                     SQLite persistence (Schema v13)
    db.py                      DB engine + migrations (v1-v13)
    memory.py                  MemoryStore (CRUD + FTS5)
    memory_activity.py         Access tracking & usage stats
    profiles.py                Profile manager
    folders.py                 Folder source manager + file indexer
    relations.py               Cross-reference / relation store
    templates.py               Assembly template store
    versions.py                Memory version history
    usage.py                   Usage-based weighting store
    settings.py                Key-value settings store
    project.py                 Project context store
  web/                         Web app (FastAPI + vanilla JS)
    app.py                     API endpoints (~27k lines)
    templates/index.html       Single-page frontend
    static/app.js              Frontend logic (~4.6k lines)
    static/style.css           Themes (light + dark, ~2.7k lines)
  interfaces/                  External interfaces
    mcp_server.py              MCP Server (20 tools, SSE transport)
    cli.py                     Click CLI
  importers/                   Memory import
    claude.py                  CLAUDE.md parser
    copilot.py                 copilot-instructions.md parser
    sqlite.py                  memory-mcp SQLite importer
tests/                         2100+ tests
```

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest tests/ -v
python -m src.web --reload    # Hot-reload
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | Python 3.11+, FastAPI, Uvicorn |
| **Frontend** | Vanilla JS, vis.js (graph), EasyMDE (editor), DOMPurify (XSS) |
| **Database** | SQLite (WAL mode, FTS5, Schema v13) |
| **Realtime** | Server-Sent Events (SSE) |
| **AI Integration** | MCP Server (FastMCP, 20 tools), tiktoken |
| **Connectors** | requests, openpyxl, PyJWT, pykeepass, PyYAML |
| **Security** | DOMPurify, Security Headers, secrets scanner, non-root Docker |
| **Deployment** | Docker (arm64 + amd64), 2100+ tests |

---

<p align="center">
  <a href="https://contextpilot.net"><strong>contextpilot.net</strong></a> — Screenshots, demos, and detailed documentation<br><br>
  Built with Claude Code
</p>
