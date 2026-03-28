# Context Pilot — Docker Setup

## Quick Start

```bash
docker pull applehell/contextpilot:latest

docker run -d --name context-pilot \
  --restart unless-stopped \
  -p 8080:8080 -p 8400:8400 \
  -v context-pilot-data:/data \
  applehell/contextpilot:latest
```

Web UI: `http://localhost:8080`
MCP SSE: `http://localhost:8400/sse`

## Docker Compose

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

## Build from Source

```bash
git clone https://github.com/applehell/contextpilot.git
cd contextpilot
docker build -t context-pilot:latest .
docker compose up -d
```

## NAS / Remote Server Deployment

To deploy on a NAS or remote server:

1. **Pull or transfer the image**
   ```bash
   # Option A: Pull from Docker Hub
   docker pull applehell/contextpilot:latest

   # Option B: Transfer from build machine
   docker save applehell/contextpilot:latest | gzip > /tmp/context-pilot.tar.gz
   scp /tmp/context-pilot.tar.gz user@server:/tmp/
   ssh user@server "docker load < /tmp/context-pilot.tar.gz"
   ```

2. **Start the container**
   ```bash
   docker run -d --name context-pilot \
     --restart unless-stopped \
     -p 8080:8080 -p 8400:8400 \
     -v context-pilot-data:/data \
     applehell/contextpilot:latest
   ```

3. **Verify**
   ```bash
   curl http://localhost:8080/health
   ```

**Note:** The Docker image supports both `amd64` and `arm64` architectures. If your build machine and target have different architectures, pull from Docker Hub or build directly on the target.

## Ports

| Port | Service | Description |
|------|---------|-------------|
| 8080 | Web UI | Dashboard, memories, graph, assembler |
| 8400 | MCP SSE | Model Context Protocol server for Claude |

## Volumes

| Path | Description |
|------|-------------|
| `/data` | SQLite databases, profiles, all persistent state |

The named volume `context-pilot-data` persists across container restarts. To back up:

```bash
docker run --rm -v context-pilot-data:/data -v $(pwd):/backup \
  alpine tar czf /backup/context-pilot-backup.tar.gz -C /data .
```

## Mapping Folders for Indexing

To make host directories available as knowledge sources, add read-only volume mounts:

```yaml
services:
  context-pilot:
    volumes:
      - context-pilot-data:/data
      - /path/to/documents:/mnt/documents:ro
      - /path/to/configs:/mnt/configs:ro
```

Then in the Web UI: Sources tab > "+ Add Folder" > use `/mnt/documents` as path.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTEXTPILOT_DATA_DIR` | `/data` | Data directory inside container |

## Claude MCP Integration

After starting the container, register the MCP server in Claude's config:

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

This goes into `~/.claude.json` on the machine running Claude Code.

## Update

```bash
docker pull applehell/contextpilot:latest
docker stop context-pilot && docker rm context-pilot
docker run -d --name context-pilot \
  --restart unless-stopped \
  -p 8080:8080 -p 8400:8400 \
  -v context-pilot-data:/data \
  applehell/contextpilot:latest
```

Your data persists in the `context-pilot-data` volume.

## Troubleshooting

**Container won't start:**
```bash
docker logs context-pilot
```

**Port conflict:**
Change host ports in `docker-compose.yml`:
```yaml
ports:
  - "9080:8080"   # Use 9080 instead
  - "9400:8400"
```

**Data recovery:**
```bash
docker exec -it context-pilot ls /data/
docker cp context-pilot:/data/data.db ./backup-data.db
```

**Health check:**
```bash
docker inspect --format='{{.State.Health.Status}}' context-pilot
```
