"""Agent-facing documentation.

Single source of truth for the "how do I use ContextPilot" guide, reused by:
- the MCP server (server-level ``instructions`` shown to MCP clients on connect),
- the FastAPI OpenAPI ``description`` (rendered at ``/docs`` and ``/redoc``),
- the ``GET /api/guide`` endpoint (fetchable Markdown for any agent).
"""
from __future__ import annotations

# Instructions surfaced to an MCP client the moment it connects (port 8400,
# streamable-http, path /mcp/). Keep it short: it is the agent's first read.
MCP_INSTRUCTIONS = """\
ContextPilot is a shared, persistent memory + context-assembly store for AI agents.
You reach it over MCP (streamable-http). Everything is scoped to the active *profile*
(an isolated knowledge base); the operator selects the profile, you inherit it.

Core loop for an agent:
1. START a task -> call `get_context_for_task(task, budget)` to pull the most
   relevant memories, already assembled to fit a token budget. This is the
   primary entry point; prefer it over manual search+assemble.
2. WORK using that context.
3. FINISH -> call `capture_learnings([...])` to persist what you learned so the
   next agent (or your next run) starts smarter.

Building blocks:
- Memories are key/value facts with tags and a `category`
  (persistent | working | reference). CRUD: `memory_set`, `memory_get`,
  `memory_list`, `memory_delete`. Find: `memory_search` (add `semantic=True`
  for meaning-based hybrid search). Explore links: `get_related_memories`.
- Templates are saved memory selections. `list_templates`, `suggest_templates`,
  `assemble_template(name)` build a ready-to-use context from one.
- Manual assembly: `assemble_context(budget, blocks)` fits raw blocks to a budget;
  `list_blocks` reports token counts; `submit_feedback` teaches the ranker which
  blocks helped so future assemblies improve.
- Long-lived skills/agents: `register_skill` + periodic `heartbeat`, then
  `get_skill_context` for skill-tailored context.

Conventions: keys are short and stable (e.g. `deploy_procedure`); tags group
related memories; token budgets are integers (e.g. 4000). All tools return JSON.
"""

# Markdown quickstart for the HTTP REST API. Doubles as the OpenAPI description.
HTTP_GUIDE_MD = """\
**ContextPilot** is a shared, persistent memory and context-assembly store for AI
agents. It exposes two interfaces over the LAN:

- **HTTP REST API** (this document, default port `8080`) — used by the web UI and
  for programmatic access.
- **MCP server** (default port `8400`, `streamable-http`, path `/mcp/`) — the
  primary interface for agents; 20 tools mirroring the concepts below.

## Base URL & versioning
All endpoints live under `/api/…`. A version alias `/api/v1/…` is accepted and
rewritten to `/api/…`, so both forms work.

## Authentication
Auth is **optional** and off by default (LAN multi-agent store). If the operator
sets the `CONTEXTPILOT_API_KEY` environment variable, every `/api/*` request
(except `/health`) must send it as the `X-API-Key` header (or `?api_key=` query
param); otherwise the server returns `401`. The MCP interface has no auth.

## Profiles
All data is scoped to the **active profile** — an isolated knowledge base. Switch
with `POST /api/profiles/switch`; list with `GET /api/profiles`. Everything below
operates on whichever profile is active.

## Quickstart for a new agent
1. `GET /health` — confirm the server is up and see counts.
2. `POST /api/context-for-task` `{ "task": "...", "budget": 4000 }` — the main
   entry point: returns the most relevant memories, assembled to fit the budget.
3. Do the work.
4. `POST /api/feedback` and/or create memories via `POST /api/memories` to persist
   what you learned for the next agent.

## Endpoint groups (see the tag sections below for every route)
- **memories** — CRUD, search (`/api/memories/search`), tags, TTL, trash, presets.
- **assembly** — `/api/context-for-task`, `/api/assemble`, `/api/estimate`,
  templates, Markdown/CLAUDE.md export.
- **profiles** — list/create/switch/export/import isolated knowledge bases.
- **graph** — knowledge graph, relations, dependency detection.
- **analytics** — usage, token, and category statistics.
- **folders** — file-folder sources synced into memories.
- **projects** — project-scoped context bundles.
- **import** — ingest JSON, `CLAUDE.md`, or Copilot Markdown.
- **events** — activity feed and SSE stream (`/api/events/stream`).
- **system** — health, setup status, global search.

Interactive docs: **`/docs`** (Swagger UI) and **`/redoc`**. Machine-readable
schema: **`/openapi.json`**. This same guide is available as Markdown at
**`/api/guide`**.
"""

# Tag metadata for OpenAPI grouping (order defines display order in /docs).
OPENAPI_TAGS = [
    {"name": "memories", "description": "Create, read, search, tag and expire memories — the core knowledge units."},
    {"name": "assembly", "description": "Assemble memories into token-budgeted context; templates and exports."},
    {"name": "profiles", "description": "Isolated knowledge bases: list, create, switch, import/export."},
    {"name": "graph", "description": "Knowledge graph: relations between memories and dependency detection."},
    {"name": "analytics", "description": "Usage, token and category statistics."},
    {"name": "folders", "description": "File-folder sources synced into memories."},
    {"name": "projects", "description": "Project-scoped context bundles."},
    {"name": "import", "description": "Ingest external knowledge (JSON, CLAUDE.md, Copilot Markdown)."},
    {"name": "events", "description": "Activity feed and Server-Sent-Events stream."},
    {"name": "system", "description": "Health, setup status and global search."},
]
