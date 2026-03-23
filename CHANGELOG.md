# Changelog

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
