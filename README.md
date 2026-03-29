<p align="center">
  <img src="https://img.shields.io/badge/version-3.6.0-blue?style=flat-square" alt="Version">
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

### Knowledge Sources — Connectors

Context Pilot pulls knowledge from multiple sources into a unified memory store:

| Connector | What it syncs |
|---|---|
| **Folder Mapping** | Local directories — recursive scan, extension filter, PDF extraction, content-hash dedup |
| **Paperless-ngx** | OCR'd documents via REST API — tag-filtered sync, metadata headers |
| **GitHub** | Public repos — releases, READMEs, issues, metadata |
| **Gitea** | Self-hosted repos — READMEs, issues, releases, wikis, packages |
| **Email (IMAP)** | Import emails as memories |

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

### More Features

| Feature | Description |
|---|---|
| **Setup Wizard** | 7-step animated onboarding for fresh installs |
| **Knowledge Graph** | Interactive vis.js network — nodes = memories, edges = shared tags |
| **Secrets Scanner** | Detects API keys, passwords, tokens, private keys (OWASP patterns) |
| **Live Activity** | Real-time SSE event stream with color-coded category badges |
| **Dark Mode** | System preference detection + manual toggle |
| **Context Preview** | Token budget assembler with auto-compression preview |
| **Settings Page** | MCP control, DB maintenance, import/export hub, scheduler |
| **Skeleton Loading** | Shimmer animations across all loading states |
| **Responsive** | Breakpoints for desktop, tablet, and mobile |

---

## MCP Server

Context Pilot includes a built-in MCP Server (Model Context Protocol) that lets Claude Code access your memories directly.

```
Claude Code ──→ MCP Server (SSE, Port 8400)
                   ├── get_skill_context    → relevance scoring + compression
                   ├── memory_set / get     → read and write memories
                   ├── memory_search        → full-text search
                   ├── memory_delete        → remove memories
                   └── register_skill       → skill registration + heartbeat
```

**How it works:**
1. Start Context Pilot → MCP Server starts on port 8400
2. Auto-registers in `~/.claude.json`
3. Claude Code can now read/write your memories
4. Stop app → auto-deregistration

---

## Docker

### Available on [Docker Hub](https://hub.docker.com/r/applehell/contextpilot)

| Tag | Description |
|---|---|
| [`applehell/contextpilot:latest`](https://hub.docker.com/r/applehell/contextpilot/tags) | Latest stable release |
| [`applehell/contextpilot:3.6.0`](https://hub.docker.com/r/applehell/contextpilot/tags) | Specific version |

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
               ├── Sources          Folder Mapping, Connectors
               ├── Secrets          Scanner, Redacted View
               ├── Settings         MCP, DB, Import/Export, Scheduler
               └── Assembler        Token Budget, Compress Preview

Claude Code ──→ MCP Server (SSE, Port 8400)
                   ├── get_skill_context
                   ├── memory_set / get / delete / search
                   └── register_skill / heartbeat

Connectors ──→ GitHub, Gitea, Paperless-ngx, Email (IMAP)

Storage ──→ SQLite (WAL mode + FTS5)
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
<summary><strong>Knowledge Sources</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/folders` | GET/POST | List/add folder sources |
| `/api/folders/{name}` | PUT/DELETE | Update/remove folder source |
| `/api/folders/{name}/scan` | POST | Scan single folder |
| `/api/folders/scan-all` | POST | Scan all enabled folders |
| `/api/paperless` | GET/PUT/DELETE | Paperless-ngx config |
| `/api/paperless/setup` | POST | Configure + test connection |
| `/api/paperless/sync` | POST | Sync documents |

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
<summary><strong>Import & Assembly</strong></summary>

| Endpoint | Method | Description |
|---|---|---|
| `/api/import/claude-md` | POST | Upload CLAUDE.md |
| `/api/import/copilot-md` | POST | Upload Copilot.md |
| `/api/import/sqlite` | POST | Upload SQLite DB |
| `/api/preview-context` | POST | Assembly preview |
| `/api/test-compress` | POST | Test compressor |
| `/api/estimate` | POST | Token estimation |
| `/api/assemble` | POST | Block assembly |

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
  connectors/                  External service connectors
    github.py                  GitHub REST API client
    gitea.py                   Gitea REST API client
    paperless.py               Paperless-ngx REST API client
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
| **Deployment** | Docker (arm64 + amd64) |

---

<p align="center">
  <a href="https://contextpilot.net"><strong>contextpilot.net</strong></a> — Screenshots, demos, and detailed documentation<br><br>
  Built with Claude Code
</p>
