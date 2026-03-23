# Context Pilot

Smart context and memory management for AI models. Web-App + MCP Server fuer die Verwaltung von Wissensdatenbanken, die Claude Code und andere MCP-Clients on-demand nutzen koennen.

## Features

- **Web UI** — Dashboard, Memory-Verwaltung, Knowledge Graph, Assembler, Secrets Scanner
- **MCP Server (SSE)** — Stellt Wissen nur bereit wenn die App laeuft
- **Token-Budget Assembler** — 3-Phasen-Strategie: Drop LOW, Compress MEDIUM, Truncate HIGH
- **7 Compressoren** — bullet_extract, yaml_struct, mermaid, table, code_compact, dedup_cross
- **Knowledge Graph** — Interaktive vis.js Visualisierung der Memory-Zusammenhaenge
- **Profile** — Mehrere Wissensdatenbanken (z.B. "Arbeit", "Smarthome", "Privat")
- **Secrets Scanner** — Erkennt Passwoerter, API Keys, Tokens, IPs (OWASP patterns)
- **Auto-Compress** — Memories bekommen automatisch den besten Compressor zugewiesen
- **Import** — CLAUDE.md, copilot-instructions.md, memory-mcp SQLite
- **Activity Tracking** — Zeigt welche Memories geladen, erstellt, geaendert wurden
- **Docker** — Laeuft als Container auf NAS, Pi, oder jedem Docker-Host

## Schnellstart

### Lokal (Python)

```bash
# Venv erstellen und Dependencies installieren
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Starten (Web UI + MCP Server)
python -m src.web

# Nur Web UI (ohne MCP)
python -m src.web --no-mcp

# Nur MCP Server
python -m src.interfaces.mcp_server --transport sse --port 8400
```

Web UI: http://localhost:8080
MCP SSE: http://localhost:8400/sse

### Docker

```bash
docker compose up -d
```

Oder manuell:

```bash
docker build -t context-pilot .
docker run -d -p 8080:8080 -p 8400:8400 -v context-pilot-data:/data context-pilot
```

### NAS / NAS

1. Docker-Image bauen oder `docker compose` per SSH
2. Ports: 8080 (Web UI), 8400 (MCP)
3. Volume fuer persistente Daten anlegen

## Architektur

```
Browser ──→ Web UI (FastAPI + HTMX, Port 8080)
               │
               ├── Dashboard (Stats, Skills, Activity, Import)
               ├── Memories (CRUD, Suche, Tags, NEU/UPD Badges)
               ├── Skills (Live MCP Skill Monitor)
               ├── Knowledge Graph (vis.js, Suche)
               ├── Secrets Scanner (Sensitivity Scan, Redacted View)
               └── Assembler (Token Budget, Compression Test)

Claude Code ──→ MCP Server (SSE, Port 8400)
                   │
                   ├── get_skill_context (relevante Memories + Auto-Compress)
                   ├── memory_set / memory_get / memory_delete
                   ├── memory_search (FTS5)
                   ├── register_skill / heartbeat
                   └── assemble_context / submit_feedback

Beide nutzen ──→ SQLite DB (~/.contextpilot/data.db)
                   ├── memories (+ FTS5 Volltextsuche)
                   ├── memory_activity (Aenderungs-Log)
                   ├── skill_registry (verbundene Skills)
                   ├── block_usage + feedback (Relevance Learning)
                   └── skill_block_relevance (Score pro Skill)
```

## Memory-Import

### Ueber die Web UI (Dashboard)

Im Dashboard gibt es Import-Buttons fuer:

| Format | Button | Was wird importiert |
|---|---|---|
| **CLAUDE.md** | `CLAUDE.md` | Sektionen aus Claude Code Instruktionsdateien |
| **copilot-instructions.md** | `Copilot.md` | GitHub Copilot Instruktionsdateien |
| **memory-mcp SQLite** | `SQLite .db` | Datenbank vom memory-mcp MCP Server |

### Ueber CLI

```bash
# CLAUDE.md importieren
context-pilot memories import-claude --in-path ~/.claude/CLAUDE.md

# Copilot Instructions importieren
context-pilot memories import-copilot --in-path .github/copilot-instructions.md

# memory-mcp SQLite importieren
context-pilot memories import-mcp --in-path ~/.local/share/claude-memories/memory.db

# Memories exportieren / importieren (JSON)
context-pilot memories export --out export.json
context-pilot memories import --in-path export.json
```

## Profile (Wissensdatenbanken)

Profile erlauben mehrere isolierte Wissensdatenbanken:

- **default** — Standard-Datenbank (`~/.contextpilot/data.db`)
- Weitere Profile liegen in `~/.contextpilot/profiles/<name>/data.db`

### Web UI

Im Header oben rechts:
- Dropdown zum Wechseln zwischen Profilen
- `+` Button fuer neues Profil
- `Del` Button zum Loeschen (nicht fuer "default")

### API

```
GET    /api/profiles              — Liste aller Profile
POST   /api/profiles              — Neues Profil erstellen
POST   /api/profiles/{name}/switch — Profil wechseln
DELETE /api/profiles/{name}       — Profil loeschen
POST   /api/profiles/{name}/duplicate — Profil duplizieren
```

## MCP Server — On-Demand

Der MCP Server laeuft **nur wenn Context Pilot gestartet ist**:

1. App starten → MCP Server startet auf Port 8400 (SSE)
2. Registriert sich automatisch in `~/.claude.json`
3. Claude Code kann sich verbinden und Memories nutzen
4. App beenden → MCP deregistriert sich → Claude hat keinen Zugriff mehr

### Ohne MCP (nur Web UI)

```bash
python -m src.web --no-mcp
```

## Secrets Scanner

Der Secrets Scanner erkennt sensitive Inhalte in Memories:

| Severity | Erkennt |
|---|---|
| **Critical** | Private Keys, Passwoerter (`password=`), Connection Strings |
| **High** | API Keys, Bearer Tokens, GitHub/AWS Tokens |
| **Medium** | WiFi-Passwoerter, Inline-Credentials, env Secrets |
| **Low** | Private IPs, E-Mail-Adressen, Telefonnummern |

- **Secrets Tab** in der Web UI: Scan aller Memories, Filter nach Severity
- **Redacted View**: Critical/High Secrets werden durch `[REDACTED]` ersetzt
- **API**: `GET /api/sensitivity`, `GET /api/memories/{key}/redacted`

## Assembler — Wie Wissen komprimiert wird

Wenn ein Skill (`get_skill_context`) Wissen anfragt:

1. **Auto-Detect**: Jede Memory bekommt einen Compress-Hint (code_compact, mermaid, bullet_extract, yaml_struct)
2. **Relevance Scoring**: 40% Content-Match + 60% History
3. **Assembly** (wenn Budget knapp):
   - Phase 1: LOW-Prio Blocks droppen
   - Phase 2: MEDIUM-Prio Blocks **komprimieren** (Mermaid-Diagramme, Bullet-Points, etc.)
   - Phase 3: HIGH-Prio Blocks abschneiden

## Entwicklung

```bash
# Venv einrichten
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Tests
pytest tests/ -v

# Web App mit Hot-Reload
python -m src.web --reload --no-mcp
```

### VS Code

- **F5**: Launch-Configs fuer Web App, MCP Server, Tests
- **Ctrl+Shift+B**: Tasks fuer Docker Build/Run/Stop

## API-Uebersicht

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/api/dashboard` | GET | Aggregierte Stats |
| `/api/memories` | GET/POST | Memory CRUD |
| `/api/memories/{key}` | GET/DELETE | Einzelne Memory |
| `/api/memories/search` | GET | Volltextsuche + Tags |
| `/api/memory-tags` | GET | Alle Tags |
| `/api/memory-activity` | GET | Aenderungs-Log |
| `/api/sensitivity` | GET | Secrets Scan |
| `/api/memories/{key}/redacted` | GET | Redacted View |
| `/api/knowledge-graph` | GET | Graph-Daten (vis.js) |
| `/api/skills` | GET | Registrierte MCP Skills |
| `/api/profiles` | GET/POST | Profil-Verwaltung |
| `/api/profiles/{name}/switch` | POST | Profil wechseln |
| `/api/import/claude-md` | POST | CLAUDE.md Upload |
| `/api/import/copilot-md` | POST | Copilot.md Upload |
| `/api/import/sqlite` | POST | SQLite DB Upload |
| `/api/preview-context` | POST | Assembly Preview |
| `/api/test-compress` | POST | Compressor testen |
| `/api/estimate` | POST | Token-Schaetzung |
| `/api/assemble` | POST | Block Assembly |
| `/api/mcp-status` | GET | MCP Server Status |

## Technologie

- **Backend**: Python 3.11+, FastAPI, uvicorn
- **Frontend**: HTMX, vis.js (Knowledge Graph)
- **Storage**: SQLite (WAL-Mode) + FTS5 Volltextsuche
- **MCP**: FastMCP mit SSE Transport
- **Token Counting**: tiktoken (cl100k_base)
- **Container**: Docker (python:3.11-slim, ~557MB)
