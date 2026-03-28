<p align="center">
  <img src="https://img.shields.io/docker/pulls/applehell/contextpilot?style=flat-square&color=blue" alt="Docker Pulls">
  <img src="https://img.shields.io/docker/image-size/applehell/contextpilot/latest?style=flat-square&color=blue" alt="Image Size">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="License">
  <img src="https://img.shields.io/badge/arch-amd64%20%7C%20arm64-lightgrey?style=flat-square" alt="Architecture">
</p>

<h1 align="center">Context Pilot</h1>

<p align="center">
  <strong>Open source AI knowledge management platform</strong><br>
  Web App + MCP Server — built with Python, MIT licensed
</p>

<p align="center">
  <a href="https://contextpilot.net">Website</a> &bull;
  <a href="https://github.com/applehell/contextpilot">GitHub</a> &bull;
  <a href="https://github.com/applehell/contextpilot#features">Features</a> &bull;
  <a href="https://github.com/applehell/contextpilot#api-reference">API Reference</a>
</p>

---

## What is Context Pilot?

Context Pilot gives your AI assistant **persistent, structured memory**. Store knowledge once, use it with any AI model — Claude Code, GitHub Copilot, Ollama, LM Studio, or any MCP-compatible client.

- **No registration required** — install and use immediately
- **No data leaves your machine** — everything runs on localhost
- **MIT License** — use, modify, distribute freely
- **Plugin-based connectors** — extend with simple Python modules

---

## Quick Start

```bash
docker pull applehell/contextpilot:latest

docker run -d --name context-pilot \
  -p 8080:8080 -p 8400:8400 \
  -v context-pilot-data:/data \
  applehell/contextpilot:latest
```

**Web UI:** [http://localhost:8080](http://localhost:8080)
**MCP Server:** `http://localhost:8400/sse`
**Health Check:** [http://localhost:8080/health](http://localhost:8080/health)

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

---

## Connect to Claude Code

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "context-pilot": {
      "type": "sse",
      "url": "http://localhost:8400/sse"
    }
  }
}
```

Claude Code now has full access to your knowledge base.

---

## Features

| Feature | Description |
|---|---|
| **Memories** | Create, search (FTS5), tag, pin, TTL, bulk operations |
| **50+ Connectors** | GitHub, Gitea, Paperless-ngx, Email (IMAP), local folders |
| **Plugin Architecture** | Every connector is a Python module — write your own in minutes |
| **MCP Server** | Built-in Model Context Protocol server (SSE, port 8400) |
| **Knowledge Graph** | Interactive network visualization of memory relationships |
| **Smart Assembler** | Token-budget assembly with 7 compressors |
| **Secrets Scanner** | Detects API keys, passwords, tokens (OWASP patterns) |
| **Profiles** | Fully isolated workspaces per project/client |
| **Import** | CLAUDE.md, Copilot instructions, SQLite databases |
| **REST API** | Full API for custom integrations |

---

## Tags

| Tag | Description |
|---|---|
| `latest` | Latest stable release |
| `3.4.0` | Current version |

## Volumes

| Path | Purpose |
|---|---|
| `/data` | Database, profiles, configs (persistent) |
| `/mnt/docs` | Optional: local folder for indexing (read-only) |

## Ports

| Port | Service |
|---|---|
| `8080` | Web UI + REST API |
| `8400` | MCP SSE Server |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `CONTEXTPILOT_DATA_DIR` | `/data` | Data directory inside container |

---

## Tech Stack

Python 3.11+ · FastAPI · SQLite (WAL + FTS5) · Server-Sent Events · MCP (FastMCP) · tiktoken

---

## License

MIT License — free to use, modify, and distribute.

Source code: [github.com/applehell/contextpilot](https://github.com/applehell/contextpilot)
Website: [contextpilot.net](https://contextpilot.net)
