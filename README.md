# Context Pilot

Wissensdatenbank-Manager fuer AI Models. Laeuft als Web-App im Browser und stellt Wissen per MCP Server on-demand fuer Claude Code bereit.

## Schnellstart

### Docker (empfohlen)

```bash
docker compose up -d
```

Web UI: http://localhost:8080

### Lokal

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.web
```

### Kommandozeilen-Optionen

```bash
python -m src.web                          # Web UI + MCP Server
python -m src.web --no-mcp                 # Nur Web UI
python -m src.web --port 9090              # Anderer Port
python -m src.web --mcp-port 8500          # MCP auf anderem Port
```

## Was die App kann

### Memories verwalten

- Erstellen, bearbeiten, loeschen (Klick auf Memory oeffnet Detail-Ansicht)
- Volltextsuche + Tag-Filter (Tags sind klickbar)
- NEU/UPD Badges fuer kuerzlich erstellte/geaenderte Memories
- Bulk-Auswahl zum Sammelloeschen
- Export als JSON (alle oder nach Tag gefiltert)

### Import

Im Dashboard gibt es Upload-Buttons fuer:

| Format | Was wird importiert |
|---|---|
| **CLAUDE.md** | Sektionen aus Claude Code Instruktionsdateien |
| **Copilot.md** | GitHub Copilot Instruktionsdateien |
| **SQLite .db** | Datenbank vom memory-mcp MCP Server |

### Profile

Mehrere isolierte Wissensdatenbanken (z.B. "Arbeit", "Smarthome", "Privat"):

- Dropdown im Header zum Wechseln
- Neues Profil erstellen (`+` Button)
- Profil umbenennen (Rename Button)
- Profil loeschen oder duplizieren

### Knowledge Graph

Interaktive Visualisierung aller Memories als Netzwerk:

- Nodes = Memories, farbcodiert nach Gruppe
- Edges = gemeinsame Tags
- Suche filtert/hebt Nodes hervor
- Klick zeigt Details + Inhalt

### Secrets Scanner

Erkennt sensitive Inhalte in Memories:

| Severity | Beispiele |
|---|---|
| **Critical** | Private Keys, Passwoerter, Connection Strings |
| **High** | API Keys, Bearer Tokens, GitHub/AWS Tokens |
| **Medium** | WiFi-Passwoerter, Inline-Credentials |
| **Low** | Private IPs, E-Mail-Adressen |

- Eigener Secrets-Tab mit Statistiken und Filter
- Redacted View fuer sensitive Memories

### Context Preview

Zeigt wie Memories fuer einen Skill assembliert werden:

- Token-Budget einstellen
- Sehen welche Memories eingeschlossen/gedroppt werden
- Auto-Compress: Code → code_compact, Schritte → mermaid, Prosa → bullet_extract

### MCP Server (On-Demand)

Der MCP Server laeuft **nur wenn die App gestartet ist**:

1. App starten → MCP Server (SSE) startet auf Port 8400
2. Registriert sich in `~/.claude.json`
3. Claude Code kann Memories nutzen
4. App beenden → Deregistrierung → kein Zugriff mehr

## Docker

```yaml
# docker-compose.yml
services:
  context-pilot:
    build: .
    ports:
      - "8080:8080"   # Web UI
      - "8400:8400"   # MCP SSE
    volumes:
      - context-pilot-data:/data
```

Daten liegen persistent im Docker Volume. Image-Groesse: ~557MB.

## Architektur

```
Browser ──→ Web UI (FastAPI, Port 8080)
               ├── Dashboard (Stats, Import, MCP Status)
               ├── Memories (CRUD, Suche, Edit-Modal, Tags)
               ├── Skills (Live MCP Skill Monitor)
               ├── Knowledge Graph (vis.js)
               ├── Secrets (Scanner, Redacted View)
               └── Assembler (Token Budget, Compress Test)

Claude Code ──→ MCP Server (SSE, Port 8400)
                   ├── get_skill_context (Relevanz + Kompression)
                   ├── memory_set / get / delete / search
                   └── register_skill / heartbeat

Beide ──→ SQLite (~/.contextpilot/data.db)
```

## Datenpfade

```
~/.contextpilot/
  data.db                      ← Standard-Datenbank (default Profil)
  profiles.json                ← Profil-Konfiguration (aktives Profil)
  profiles/
    <profilname>/
      data.db                  ← Datenbank fuer dieses Profil

# Im Docker-Container (CONTEXTPILOT_DATA_DIR=/data):
/data/
  data.db
  profiles.json
  profiles/<name>/data.db
```

## Projektstruktur

```
src/
  core/                        ← Kernlogik (Assembler, Compressoren, Relevanz)
    assembler.py               ← 3-Phasen Token-Budget Assembler
    block.py                   ← Block Datenmodell
    compressors/               ← 7 Kompressoren (bullet, mermaid, yaml, code, ...)
    relevance.py               ← Relevance Scoring Engine
    secrets.py                 ← Secrets Detector (OWASP Patterns)
    token_budget.py            ← tiktoken Wrapper
    claude_config.py           ← MCP Registration in ~/.claude.json
    weight_adjuster.py         ← Usage-basierte Gewichtung
  storage/                     ← SQLite Persistenz
    db.py                      ← DB Engine + Migrationen (v1-v6)
    memory.py                  ← MemoryStore (CRUD + FTS5)
    memory_activity.py         ← Activity Log
    profiles.py                ← Profil-Manager
    usage.py                   ← Usage Tracking + Feedback
  web/                         ← Web-App (FastAPI + HTMX)
    app.py                     ← API Endpoints
    templates/index.html       ← Single-Page Frontend
    static/app.js              ← Frontend-Logik
    static/style.css           ← Styling (Catppuccin Dark)
  interfaces/                  ← Externe Schnittstellen
    mcp_server.py              ← MCP Server (stdio + SSE)
    cli.py                     ← Click CLI
  importers/                   ← Memory-Import
    claude.py                  ← CLAUDE.md Parser
    copilot.py                 ← copilot-instructions.md Parser
    sqlite.py                  ← memory-mcp SQLite Importer
tests/                         ← 444 Tests
```

## API

| Endpoint | Methode | Beschreibung |
|---|---|---|
| `/api/dashboard` | GET | Aggregierte Stats |
| `/api/memories` | GET/POST | Memories auflisten/erstellen |
| `/api/memories/{key}` | GET/PUT/DELETE | Memory lesen/bearbeiten/loeschen |
| `/api/memories/search` | GET | Volltextsuche + Tags |
| `/api/memories/bulk-delete` | POST | Mehrere Memories loeschen |
| `/api/export-memories` | GET | Export als JSON |
| `/api/memory-tags` | GET | Alle Tags |
| `/api/memory-activity` | GET | Aenderungs-Log |
| `/api/sensitivity` | GET | Secrets Scan |
| `/api/redacted?key=...` | GET | Redacted View |
| `/api/knowledge-graph` | GET | Graph-Daten (vis.js) |
| `/api/skills` | GET | Registrierte MCP Skills |
| `/api/profiles` | GET/POST | Profile auflisten/erstellen |
| `/api/profiles/{name}` | PUT/DELETE | Profil umbenennen/loeschen |
| `/api/profiles/{name}/switch` | POST | Profil wechseln |
| `/api/profiles/{name}/duplicate` | POST | Profil duplizieren |
| `/api/import/claude-md` | POST | CLAUDE.md Upload |
| `/api/import/copilot-md` | POST | Copilot.md Upload |
| `/api/import/sqlite` | POST | SQLite DB Upload |
| `/api/preview-context` | POST | Assembly Preview |
| `/api/test-compress` | POST | Compressor testen |
| `/api/estimate` | POST | Token-Schaetzung |
| `/api/assemble` | POST | Block Assembly |
| `/api/mcp-status` | GET | MCP Server Status |

## Entwicklung

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
pytest tests/ -v              # 444 Tests
python -m src.web --reload    # Hot-Reload
docker build -t context-pilot .
```

## Technologie

Python 3.11+, FastAPI, HTMX, vis.js, SQLite (WAL + FTS5), FastMCP (SSE), tiktoken, Docker
