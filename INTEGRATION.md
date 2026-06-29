# ContextPilot Integration Guide

How to connect an AI assistant or script to ContextPilot. ContextPilot exposes
**two surfaces over one shared, profile-isolated knowledge store**:

| Surface | For | Default address |
|---|---|---|
| **MCP server** (streamable-http) | AI agents that speak MCP — Claude Code, GitHub Copilot agent mode, Cursor, custom clients | `http://<host>:8400/mcp` |
| **HTTP REST API** | scripts, dashboards, health checks, anything non-MCP | `http://<host>:8080` |

Both read and write the **same memories** in the **currently active profile**. A
profile switch (via HTTP) is picked up by the MCP server in real time — no restart.

---

## 1. Starting the server

```bash
python -m src.web                       # Web UI on :8080, auto-starts MCP on :8400
python -m src.web --port 8080 --mcp-port 8400 --host 0.0.0.0
python -m src.web --no-mcp              # Web UI only
```

Starting the web server also:
- launches the MCP server as a subprocess (`--transport streamable-http`), and
- auto-registers it in `~/.claude.json` (removed again on shutdown).

Run the MCP server standalone:

```bash
python -m src.interfaces.mcp_server --transport streamable-http --host 0.0.0.0 --port 8400
```

---

## 2. Connecting an MCP client

### Transport — read this first

- Use **`streamable-http`**. The server is **stateless** (`stateless_http=True`).
- **Never use SSE.** The SSE transport produces `-32602 Invalid request parameters`
  errors against this stateless server. The CLI accepts `--transport sse` but do
  not use it for clients.
- Endpoint path is **`/mcp`** → `http://<host>:8400/mcp`.
- No per-request auth at the MCP layer. If exposed beyond localhost/LAN, put it
  behind a reverse proxy that enforces auth.

### Client config (same for every MCP client)

Claude Code (`~/.claude.json`, auto-written by the app):

```json
{
  "mcpServers": {
    "context-pilot": {
      "type": "http",
      "url": "http://127.0.0.1:8400/mcp"
    }
  }
}
```

GitHub Copilot agent mode and Cursor use the same remote streamable-http URL —
only the file name and wrapper key differ.

GitHub Copilot — `.vscode/mcp.json`:

```json
{
  "servers": {
    "context-pilot": { "type": "http", "url": "http://127.0.0.1:8400/mcp" }
  }
}
```

Cursor — `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "context-pilot": { "url": "http://127.0.0.1:8400/mcp" }
  }
}
```

Once connected, the client discovers all tools and their argument schemas
automatically from the server — no manual tool list needed.

---

## 3. MCP tool catalog (20 tools)

Each tool is self-describing (name, args, docstring) over MCP. Summary:

**Memory CRUD**
- `memory_set(key, value, tags=[], category="persistent")` — create/update; updates keep version history.
- `memory_get(key)` — fetch one memory (value, tags, metadata, ttl).
- `memory_delete(key)` — soft-delete (goes to trash).
- `memory_search(query, tags=None, semantic=False)` — keyword/FTS search; `semantic=True` adds embedding ranking.
- `memory_list(tag="")` — list keys, optionally filtered by tag.

**Context assembly**
- `get_context_for_task(task_description, budget=4000, include_tags=None)` — hybrid-search + **rerank** + budget-fit; returns ranked `blocks`.
- `assemble_context(budget, blocks)` — assemble caller-supplied blocks to a token budget.
- `list_blocks(blocks)` — token-estimate a block set without assembling.
- `assemble_template(name)` / `list_templates()` / `suggest_templates()` — reusable context bundles.

**Skills**
- `register_skill(name, description, context_hints=None)` / `unregister_skill(name)` / `list_registered_skills()` / `heartbeat(name)`.
- `get_skill_context(skill_name, token_budget=4000, blocks=None)` — budget-optimized context for a registered skill.

**Intelligence / feedback**
- `capture_learnings(learnings)` — bulk-save memories (auto-tags `source:auto-capture` + date).
- `get_related_memories(key)` — explicit relations + semantic neighbours.
- `submit_feedback(assembly_id, block_content, helpful)` — trains the relevance/weight loop.
- `get_block_weight(block_content, project_name="")` — current usage-derived weight of a block.

---

## 4. HTTP REST API

Base `http://<host>:8080`. JSON in/out. Memory keys are path params and may
contain `/` (FastAPI `:path`).

**Health & profiles** (scripts use these for switching)
| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | status, active profile, memory count, version (auth-exempt) |
| GET | `/api/profiles` | list profiles **with their IDs** |
| POST | `/api/profiles/{id}/switch` | switch active profile — **by ID, not name** |
| GET | `/api/profiles/{id}/export` | export a profile as a ZIP |

**Memories**
| Method | Path | Purpose |
|---|---|---|
| GET | `/api/memories` | list (paged) |
| GET | `/api/memories/search?q=` | search |
| GET | `/api/memories/{key}` | fetch one |
| POST | `/api/memories` | create (`{key, value, tags, category, ttl_seconds}`) |
| PUT | `/api/memories/{key}` | update |
| DELETE | `/api/memories/{key}` | delete (to trash) |

**Assembly & search**
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/context-for-task` | `{task_description, budget, tags}` → ranked blocks (HTTP twin of the MCP tool) |
| POST | `/api/assemble` | assemble caller blocks to a budget |
| GET | `/api/semantic-search?q=` | embedding search |
| GET | `/api/knowledge-graph` | nodes/edges for the graph view |

**Maintenance & analytics**
| Method | Path | Purpose |
|---|---|---|
| POST | `/api/maintenance/vacuum` · `/api/maintenance/rebuild-fts` | DB compaction / FTS rebuild |
| GET | `/api/duplicates` · `/api/similar/{key}` | duplicate / similarity detection |
| GET | `/api/consolidation-report` · `/api/contradictions` | consolidation findings (limit-bounded) |
| POST | `/api/duplicates/merge` | merge a group of memories (`{keys, into?}`) |
| GET | `/api/retrieval-eval` | retrieval quality (baseline vs reranked) |
| GET | `/api/analytics/summary` · `/api/analytics/top-tags` | usage stats |

### Optional API key

Off by default (LAN multi-agent store). If `CONTEXTPILOT_API_KEY` is set, every
`/api/*` call (except `/health`) must send the key as header `X-API-Key: <key>`
(or `?api_key=<key>`).

---

## 5. Response shapes

`get_context_for_task` / `POST /api/context-for-task`:

```json
{
  "blocks": [{ "key": "infra/nginx", "content": "[infra/nginx] ...", "priority": "high", "tokens": 120 }],
  "total_tokens": 1840,
  "memories_considered": 30,
  "memories_included": 12
}
```

`memory_get` / `GET /api/memories/{key}`:

```json
{
  "key": "infra/nginx", "value": "Reverse proxy ...",
  "tags": ["infra", "nginx"], "metadata": { "source": "manual" },
  "category": "persistent", "pinned": false, "expires_at": null, "ttl_label": null
}
```

---

## 6. Profiles

Memories are isolated per profile (`profiles/<name>/data.db` + embeddings).

- Switch **by ID**: `GET /api/profiles` to resolve name → id, then `POST /api/profiles/{id}/switch`.
- After a switch the MCP server serves the new profile automatically.
- A `404` on a memory key usually means the profile changed — re-resolve, don't treat it as a network error.

---

## 7. A note on GitHub Copilot

Two unrelated directions, don't confuse them:

- **Copilot as a consumer** — connect Copilot agent mode as an MCP client (section 2). It then reads/writes memories exactly like Claude Code; no Copilot-specific server code or extra docs are required, because the tools are self-describing over MCP.
- **Copilot as a source** — the importer `src/importers/copilot.py` parses `copilot-instructions.md` files **into** ContextPilot as memories. This is one-way ingestion and needs no MCP/HTTP wiring.
