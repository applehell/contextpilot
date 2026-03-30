<p align="center">
  <img src="https://img.shields.io/badge/version-3.8.0-blue?style=flat-square" alt="Version">
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

### Memories

| Capability | Details |
|---|---|
| **Create & Edit** | Modal editor with Markdown support (EasyMDE) |
| **Search** | Full-text search via SQLite FTS5 |
| **Tags** | Clickable tag filtering, bulk tag operations |
| **TTL** | Time-to-live with auto-expiry, lifetime indicators |
| **Pin** | Pin important memories to the top |
| **Bulk Ops** | Multi-select, bulk delete, bulk TTL editing |
| **Export** | JSON export (all or filtered by tag) |
| **Diff View** | Compare memory versions side-by-side |

### Connector Store — 17 Sources

Context Pilot pulls knowledge from multiple sources into a unified memory store. The **Connector Store** provides a card-based UI with category filters, brand icons, and setup guides.

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

Each connector tracks **sync history** (last 20 runs) and exposes a **health dashboard** (`GET /api/connectors/health`).

### Import

Upload files directly from the dashboard:

| Format | Source |
|---|---|
| `CLAUDE.md` | Claude Code instruction files |
| `Copilot.md` | GitHub Copilot instruction files |
| `SQLite .db` | memory-mcp MCP Server databases |

### Profiles — Complete Isolation

Every profile is a fully isolated workspace:

```
profiles/{name}/
  data.db              ← Memories, tags, FTS index, templates, relations
  connector_*.json     ← Paperless, GitHub, Gitea, Email configs
  folders.json         ← Folder source configuration
  webhooks.json        ← Webhook configuration
  embeddings.db        ← Semantic search index
```

- Switch instantly via header dropdown
- Create with knowledge import from existing profiles
- Export/import as ZIP archive
- Rename, delete, duplicate from Settings

### Context Assembler

The Assembler optimizes your memories for AI consumption within a token budget:

| Feature | Description |
|---|---|
| **Templates** | Save reusable filter + budget combos (tag filter, key prefix, token budget) |
| **Auto-Suggest** | Analyzes memory clusters and proposes templates automatically |
| **Compression** | 6 compressors: bullet extract, code compact, YAML struct, Mermaid, table, dedup |
| **Weight-Based Priority** | Blocks ranked by usage history and feedback scores |
| **MCP Integration** | `assemble_template` and `suggest_templates` tools for programmatic use |

### More Features

| Feature | Description |
|---|---|
| **Setup Wizard** | 7-step animated onboarding for fresh installs |
| **Knowledge Graph** | Interactive vis.js network — nodes = memories, edges = shared tags |
| **Secrets Scanner** | Detects API keys, passwords, tokens, private keys (OWASP patterns) |
| **Live Activity** | Real-time SSE event stream with color-coded category badges |
| **Dark Mode** | System preference detection + manual toggle |
| **DOMPurify** | XSS protection for Markdown rendering |
| **Security Headers** | X-Content-Type-Options, X-Frame-Options, Referrer-Policy |
| **Settings Page** | MCP control, DB maintenance, import/export hub, scheduler |
| **Skeleton Loading** | Shimmer animations across all loading states |
| **Responsive** | Breakpoints for desktop, tablet, and mobile |

---

## MCP Server

Context Pilot includes a built-in MCP Server (Model Context Protocol) that lets Claude Code access your memories directly.

```
Claude Code ──→ MCP Server (SSE, Port 8400)
                   ├── memory_set / get / delete / search / list
                   ├── assemble_template / list_templates / suggest_templates
                   ├── get_skill_context    → relevance scoring + compression
                   ├── register_skill / heartbeat / list_registered_skills
                   ├── assemble_context / list_blocks
                   └── submit_feedback / get_block_weight
```

**23 MCP Tools** covering: memory CRUD, template assembly, auto-suggest, skill registry, context assembly, and feedback.

**Profile-aware:** The MCP server follows profile switches in real-time — no restart needed.

**How it works:**
1. Start Context Pilot → MCP Server starts on port 8400
2. Auto-registers in `~/.claude.json`
3. Claude Code can now read/write your memories
4. Stop app → auto-deregistration

---

## Claude Code Plugin

The **context-pilot plugin** adds deep integration with Claude Code — auto-profile detection, slash commands, and a skill file that teaches Claude how to use ContextPilot optimally.

### Installation

```bash
# From GitHub
claude plugins marketplace add https://github.com/applehell/context-pilot-plugin.git
claude plugins install context-pilot
```

Or clone directly:

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
| **Skill File** | Teaches Claude all 23 MCP tools, best practices, and when to use what |
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
export CONTEXTPILOT_URL=http://your-server:8080        # Web UI
export CONTEXTPILOT_MCP_URL=http://your-server:8400/sse  # MCP Server
```

---

## Docker

### Available on [Docker Hub](https://hub.docker.com/r/applehell/contextpilot)

| Tag | Description |
|---|---|
| [`applehell/contextpilot:latest`](https://hub.docker.com/r/applehell/contextpilot/tags) | Latest stable release |
| [`applehell/contextpilot:3.8.0`](https://hub.docker.com/r/applehell/contextpilot/tags) | Specific version |

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
Browser ──→ Web UI (FastAPI, Port 8080)
               ├── Dashboard        Stats, Import, Live Activity SSE
               ├── Memories         CRUD, Search, Editor, Tags, TTL
               ├── Knowledge Graph  Interactive vis.js network
               ├── Sources          Connector Store (17), Folder Mapping, Webhooks
               ├── Secrets          Scanner, Redacted View
               ├── Settings         MCP, DB, Import/Export, Scheduler, Profiles
               └── Assembler        Templates, Auto-Suggest, Compression

Claude Code ──→ MCP Server (SSE, Port 8400)
                   ├── memory_set / get / delete / search / list
                   ├── assemble_template / list_templates / suggest_templates
                   ├── get_skill_context / register_skill / heartbeat
                   └── assemble_context / submit_feedback / get_block_weight

            ──→ Plugin (context-pilot)
                   ├── SessionStart hook (auto-profile detection)
                   ├── /context-pilot command
                   └── Skill file (best practices + tool guidance)

Connectors ──→ 17 sources (GitHub, Gitea, Paperless, Obsidian, Email,
               Notion, Teams, Telegram, RSS, Excel, Google Drive,
               KeePass, Bitwarden, Kubernetes, Dockge, Bookmarks, HA)

Storage ──→ SQLite (WAL mode + FTS5, Schema v12)
```

### Data Paths

```
# Local
~/.contextpilot/
  profiles.json                ← Profile registry
  profiles/<name>/data.db      ← Per-profile database + configs

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
| `/api/mcp-status` | GET | MCP server status |

</details>

<details>
<summary><strong>Memories</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/memories` | GET | List memories (pagination, filters) |
| `/api/memories` | POST | Create memory |
| `/api/memories/{key}` | GET | Read single memory |
| `/api/memories/{key}` | PUT | Update memory |
| `/api/memories/{key}` | DELETE | Delete memory |
| `/api/memories/search` | GET | Full-text search + tag filter |
| `/api/memories/bulk-delete` | POST | Bulk delete |
| `/api/export-memories` | GET | Export as JSON |
| `/api/memory-tags` | GET | All tags |

</details>

<details>
<summary><strong>Connectors</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/connectors` | GET | List all connectors with status |
| `/api/connectors/{name}` | GET | Connector details + schema |
| `/api/connectors/{name}/setup` | POST | Configure connector |
| `/api/connectors/{name}/test` | POST | Test connection |
| `/api/connectors/{name}/sync` | POST | Sync data |
| `/api/connectors/{name}/enable` | POST | Enable/disable |
| `/api/connectors/{name}/history` | GET | Sync history (last 20) |
| `/api/connectors/health` | GET | Health dashboard for all connectors |
| `/api/folders` | GET/POST | List/add folder sources |
| `/api/folders/{name}` | PUT/DELETE | Update/remove folder source |
| `/api/folders/{name}/scan` | POST | Scan single folder |

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

</details>

<details>
<summary><strong>Profiles</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/profiles` | GET/POST | List/create profiles |
| `/api/profiles/{name}` | PUT/DELETE | Rename/delete |
| `/api/profiles/{name}/switch` | POST | Switch active profile |
| `/api/profiles/{name}/duplicate` | POST | Duplicate profile |

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
| `/api/knowledge-graph` | GET | Graph data (vis.js) |

</details>

<details>
<summary><strong>Import</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/import/claude-md` | POST | Upload CLAUDE.md |
| `/api/import/copilot-md` | POST | Upload Copilot.md |
| `/api/import/sqlite` | POST | Upload SQLite DB |

</details>

---

## Project Structure

```
src/
  core/                        Core logic
    assembler.py               3-phase token-budget assembler
    block.py                   Block data model
    compressors/               7 compressors (bullet, mermaid, yaml, code, ...)
    events.py                  Global EventBus with SSE broadcast
    relevance.py               Relevance scoring engine
    secrets.py                 Secrets detector (OWASP patterns)
    token_budget.py            tiktoken wrapper
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
  storage/                     SQLite persistence
    db.py                      DB engine + migrations (v1-v12)
    memory.py                  MemoryStore (CRUD + FTS5)
    profiles.py                Profile manager
    folders.py                 Folder source manager + file indexer
  web/                         Web app (FastAPI + vanilla JS)
    app.py                     API endpoints
    templates/index.html       Single-page frontend
    static/app.js              Frontend logic
    static/style.css           Themes (light + dark)
  interfaces/                  External interfaces
    mcp_server.py              MCP Server (stdio + SSE)
    cli.py                     Click CLI
  importers/                   Memory import
    claude.py                  CLAUDE.md parser
    copilot.py                 copilot-instructions.md parser
    sqlite.py                  memory-mcp SQLite importer
tests/                         Test suite
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
| **Frontend** | Vanilla JS, vis.js, EasyMDE |
| **Database** | SQLite (WAL mode, FTS5) |
| **Realtime** | Server-Sent Events (SSE) |
| **AI Integration** | MCP Server (FastMCP), tiktoken |
| **Connectors** | requests, openpyxl, PyJWT, pykeepass, PyYAML |
| **Security** | DOMPurify, Security Headers, non-root Docker |
| **Deployment** | Docker (arm64 + amd64), 697+ tests |

---

<p align="center">
  <a href="https://contextpilot.net"><strong>contextpilot.net</strong></a> — Screenshots, demos, and detailed documentation<br><br>
  Built with Claude Code
</p>
