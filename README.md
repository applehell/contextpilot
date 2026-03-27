# Context Pilot

Knowledge management hub for AI workflows. Runs as a web app with real-time activity streaming and connects to Claude Code via MCP Server.

## Quick Start

### Docker (recommended)

```bash
docker compose up -d
```

Web UI: http://localhost:8080 | Health: http://localhost:8080/health

### Local

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.web
```

### CLI Options

```bash
python -m src.web                          # Web UI + MCP Server
python -m src.web --no-mcp                 # Web UI only
python -m src.web --port 9090              # Custom port
python -m src.web --mcp-port 8500          # MCP on custom port
```

## Features

### Memories

- Create, edit, delete with full-text search (FTS5)
- Tag-based filtering (clickable tags)
- NEW/UPD badges for recent changes
- Bulk select and delete
- Export as JSON (all or filtered by tag)

### Knowledge Sources

#### Folder Mapping

Map local directories to index files as memories:

- Recursive or top-level scanning
- Filter by file extension (.pdf, .md, .txt, .json, .py, etc.)
- Content-hash deduplication — unchanged files skipped on re-scan
- Deleted files automatically removed
- PDF text extraction (via pypdf)

#### Paperless-ngx Connector

Sync OCR'd documents from Paperless-ngx:

- Token-based authentication
- Tag-filtered sync (only sync specific document tags)
- Rich content: metadata header (title, correspondent, type, date) + OCR text
- Content-hash deduplication
- Connection test built into the UI

### Import

Dashboard upload buttons for:

| Format | What gets imported |
|---|---|
| **CLAUDE.md** | Sections from Claude Code instruction files |
| **Copilot.md** | GitHub Copilot instruction files |
| **SQLite .db** | Database from memory-mcp MCP Server |

### Profiles — Complete Isolation

Profiles are the central concept. Switching profiles changes **everything**:

| Isolated per profile | Storage location |
|---|---|
| Memories, tags, FTS index | `profiles/{name}/data.db` |
| Connector configs (Paperless, HA, Gitea...) | `profiles/{name}/connector_*.json` |
| Folder sources | `profiles/{name}/folders.json` |
| Webhooks | `profiles/{name}/webhooks.json` |
| Embeddings / semantic search | `profiles/{name}/embeddings.db` |
| Templates, relations, versions | Inside `data.db` |
| Context assembly | Uses profile's memories |
| Dashboard stats | Reflects active profile |
| Secrets scan | Scans active profile only |

- Header dropdown to switch instantly
- Create new profile with optional knowledge import from existing profiles
- Rename, delete, duplicate
- Welcome screen for new profiles
- Scheduler stops on profile switch (restart with new profile's sources)

### Knowledge Graph

Interactive visualization of all memories as a network:

- Nodes = Memories, color-coded by group
- Edges = shared tags
- Search highlights matching nodes
- Click shows details + content

### Secrets Scanner

Detects sensitive content in memories:

| Severity | Examples |
|---|---|
| **Critical** | Private keys, passwords, connection strings |
| **High** | API keys, bearer tokens, GitHub/AWS tokens |
| **Medium** | WiFi passwords, inline credentials |
| **Low** | Private IPs, email addresses |

### Live Activity Feed

Real-time event streaming via Server-Sent Events (SSE):

- All API calls, memory operations, imports, scans, syncs tracked
- Color-coded category badges (memory, api, import, folder, paperless, profile)
- Category filter dropdown
- SSE connection status indicator

### Health Endpoint

`GET /health` returns system metrics:

- Uptime, version, platform, Python version
- Memory/token/tag counts
- Skill status, profile info
- Storage size, disk usage
- Request count and error rate

### Context Preview

Shows how memories are assembled for a skill:

- Set token budget
- See which memories are included/dropped
- Auto-compress: code → code_compact, steps → mermaid, prose → bullet_extract

### MCP Server

The MCP server runs alongside the web app:

1. Start app → MCP Server (SSE) starts on port 8400
2. Registers in `~/.claude.json`
3. Claude Code can access memories
4. Stop app → deregistration

## Docker

### From Gitea Container Registry (recommended)

```bash
# 1. Docker muss die Registry als insecure kennen (einmalig)
# In /etc/docker/daemon.json:
# { "insecure-registries": ["<server-ip>:3300"] }
# Danach: sudo systemctl restart docker

# 2. Login
docker login <server-ip>:3300

# 3. Image pullen und starten
docker pull <server-ip>:3300/constantin/context-pilot:latest
```

`docker-compose.yml` fuer den Betrieb:

```yaml
services:
  context-pilot:
    image: <server-ip>:3300/constantin/context-pilot:latest
    container_name: context-pilot
    restart: unless-stopped
    ports:
      - "8080:8080"   # Web UI
      - "8400:8400"   # MCP SSE Server
    volumes:
      - context-pilot-data:/data
      - /path/to/docs:/mnt/docs:ro    # optional: Ordner fuer Indexierung
    environment:
      - CONTEXTPILOT_DATA_DIR=/data

volumes:
  context-pilot-data:
```

```bash
docker compose up -d
```

### Lokal bauen

```bash
git clone http://<server-ip>:3300/constantin/context-pilot.git
cd context-pilot
docker compose up -d --build
```

### Neues Image bauen und pushen

```bash
cd /path/to/context-pilot
docker build -t <server-ip>:3300/constantin/context-pilot:latest .
docker push <server-ip>:3300/constantin/context-pilot:latest
```

See [DOCKER.md](DOCKER.md) for full NAS device setup guide.

## Architecture

```
Browser ──→ Web UI (FastAPI, Port 8080)
               ├── Dashboard (Stats, Import, Live Activity SSE)
               ├── Memories (CRUD, Search, Edit Modal, Tags)
               ├── Skills (Live MCP Skill Monitor)
               ├── Knowledge Graph (vis.js)
               ├── Secrets (Scanner, Redacted View)
               ├── Sources (Folder Mapping, Paperless-ngx)
               └── Assembler (Token Budget, Compress Test)

Claude Code ──→ MCP Server (SSE, Port 8400)
                   ├── get_skill_context (relevance + compression)
                   ├── memory_set / get / delete / search
                   └── register_skill / heartbeat

Paperless-ngx ──→ REST API Sync (Token auth)

Both ──→ SQLite (~/.contextpilot/data.db)
```

## Data Paths

```
~/.contextpilot/
  data.db                      ← Default database
  profiles.json                ← Profile configuration
  folders.json                 ← Folder source configuration
  paperless.json               ← Paperless-ngx connection config
  profiles/
    <name>/
      data.db                  ← Profile-specific database

# In Docker (CONTEXTPILOT_DATA_DIR=/data):
/data/
  data.db
  profiles.json
  folders.json
  paperless.json
  profiles/<name>/data.db
```

## Project Structure

```
src/
  core/                        ← Core logic
    assembler.py               ← 3-phase token-budget assembler
    block.py                   ← Block data model
    compressors/               ← 7 compressors (bullet, mermaid, yaml, code, ...)
    events.py                  ← Global EventBus with SSE broadcast
    relevance.py               ← Relevance scoring engine
    secrets.py                 ← Secrets detector (OWASP patterns)
    token_budget.py            ← tiktoken wrapper
    weight_adjuster.py         ← Usage-based weight adjustment
  connectors/                  ← External service connectors
    paperless.py               ← Paperless-ngx REST API client + sync
  storage/                     ← SQLite persistence
    db.py                      ← DB engine + migrations (v1-v6)
    memory.py                  ← MemoryStore (CRUD + FTS5)
    memory_activity.py         ← Activity log
    folders.py                 ← Folder source manager + file indexer
    profiles.py                ← Profile manager
    usage.py                   ← Usage tracking + feedback
  web/                         ← Web app (FastAPI + vanilla JS)
    app.py                     ← API endpoints
    templates/index.html       ← Single-page frontend
    static/app.js              ← Frontend logic
    static/style.css           ← Light theme (Inter font)
  interfaces/                  ← External interfaces
    mcp_server.py              ← MCP Server (stdio + SSE)
    cli.py                     ← Click CLI
  importers/                   ← Memory import
    claude.py                  ← CLAUDE.md parser
    copilot.py                 ← copilot-instructions.md parser
    sqlite.py                  ← memory-mcp SQLite importer
tests/                         ← Test suite
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | System metrics and health check |
| `/api/events` | GET | Recent events (with category filter) |
| `/api/events/stream` | GET | SSE real-time event stream |
| `/api/events/stats` | GET | Event count statistics |
| `/api/dashboard` | GET | Aggregated dashboard stats |
| `/api/memories` | GET/POST | List/create memories |
| `/api/memories/{key}` | GET/PUT/DELETE | Read/update/delete memory |
| `/api/memories/search` | GET | Full-text search + tags |
| `/api/memories/bulk-delete` | POST | Bulk delete memories |
| `/api/export-memories` | GET | Export as JSON |
| `/api/memory-tags` | GET | All tags |
| `/api/sensitivity` | GET | Secrets scan |
| `/api/redacted?key=...` | GET | Redacted view |
| `/api/knowledge-graph` | GET | Graph data (vis.js) |
| `/api/skills` | GET | Registered MCP skills |
| `/api/profiles` | GET/POST | List/create profiles |
| `/api/profiles/{name}` | PUT/DELETE | Rename/delete profile |
| `/api/profiles/{name}/switch` | POST | Switch profile |
| `/api/profiles/{name}/duplicate` | POST | Duplicate profile |
| `/api/folders` | GET/POST | List/add folder sources |
| `/api/folders/{name}` | PUT/DELETE | Update/remove folder source |
| `/api/folders/{name}/scan` | POST | Scan single folder |
| `/api/folders/scan-all` | POST | Scan all enabled folders |
| `/api/paperless` | GET/PUT/DELETE | Paperless config/status |
| `/api/paperless/setup` | POST | Configure + test connection |
| `/api/paperless/test` | POST | Test connection |
| `/api/paperless/sync` | POST | Sync documents |
| `/api/import/claude-md` | POST | Upload CLAUDE.md |
| `/api/import/copilot-md` | POST | Upload Copilot.md |
| `/api/import/sqlite` | POST | Upload SQLite DB |
| `/api/preview-context` | POST | Assembly preview |
| `/api/test-compress` | POST | Test compressor |
| `/api/estimate` | POST | Token estimation |
| `/api/assemble` | POST | Block assembly |
| `/api/mcp-status` | GET | MCP server status |

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest tests/ -v
python -m src.web --reload    # Hot-reload
docker build -t context-pilot .
```

## Technology

Python 3.11+, FastAPI, vanilla JS, vis.js, SQLite (WAL + FTS5), SSE, FastMCP, tiktoken, Docker
