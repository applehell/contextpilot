# Context Pilot — Docker Setup (NAS NAS)

## Quick Start (any Docker host)

```bash
git clone http://<server-ip>:3300/constantin/context-pilot.git
cd context-pilot
docker compose up -d
```

Web UI: `http://<host-ip>:8080`
MCP SSE: `http://<host-ip>:8400/sse`

## NAS device Setup

### Prerequisites

- **Container Manager** installed (DSM Package Center)
- SSH access enabled (Control Panel → Terminal & SNMP → Enable SSH)

### Option A: Container Manager UI

1. **Create project folder**
   - File Station → Create folder: `/docker/context-pilot`

2. **Upload files via SSH**
   ```bash
   ssh <user>@<nas-ip>
   cd ~/docker/context-pilot
   git clone http://constantin:REDACTED@<server-ip>:3300/constantin/context-pilot.git .
   ```

3. **Build & run via Container Manager**
   - Open Container Manager → Project → Create
   - Path: `/docker/context-pilot`
   - It auto-detects `docker-compose.yml`
   - Click "Build" then "Start"

4. **Verify**
   - Open `http://<nas-ip>:8080` in your browser

### Option B: SSH only

```bash
ssh <user>@<nas-ip>

# Clone repo
mkdir -p ~/docker/context-pilot
cd ~/docker/context-pilot
git clone http://constantin:REDACTED@<server-ip>:3300/constantin/context-pilot.git .

# Build and start
docker compose up -d --build

# Check logs
docker logs -f context-pilot

# Verify
curl http://localhost:8080/api/dashboard
```

### Option C: Pre-built image from Pi

Build on the Raspberry Pi and push to the NAS:

```bash
# On Pi (<server-ip>)
cd ~/contextpilot
docker build -t context-pilot:latest .
docker save context-pilot:latest | gzip > /tmp/context-pilot.tar.gz
scp /tmp/context-pilot.tar.gz <user>@<nas-ip>:/tmp/

# On NAS
ssh <user>@<nas-ip>
docker load < /tmp/context-pilot.tar.gz
mkdir -p ~/docker/context-pilot
# Copy docker-compose.yml to that folder, then:
cd ~/docker/context-pilot
docker compose up -d
```

**Note:** The Pi is ARM64, the NAS device has an ARM ARM SoC. If architectures differ, build directly on the NAS instead.

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
docker run --rm -v context-pilot-data:/data -v ~/backup:/backup \
  alpine tar czf /backup/context-pilot-backup.tar.gz -C /data .
```

## Mapping Folders for Indexing

To make host directories available as knowledge sources, add read-only volume mounts:

```yaml
services:
  context-pilot:
    volumes:
      - context-pilot-data:/data
      - ~/documents:/mnt/documents:ro
      - ~/configs:/mnt/configs:ro
```

Then in the Web UI → Sources tab → "+ Add Folder" → use `/mnt/documents` as path.

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
      "url": "http://<nas-ip>:8400/sse"
    }
  }
}
```

This goes into `~/.claude/settings.json` on the machine running Claude Code.

## Update

```bash
cd ~/docker/context-pilot
git pull
docker compose up -d --build
```

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
The SQLite database is in the Docker volume. To access:
```bash
docker exec -it context-pilot ls /data/
docker cp context-pilot:/data/data.db ./backup-data.db
```

**Health check:**
```bash
docker inspect --format='{{.State.Health.Status}}' context-pilot
```
