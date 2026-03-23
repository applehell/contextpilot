# Context Pilot

Smart context and memory management for AI models. Assembles blocks of content within a token budget, compressing or dropping lower-priority blocks as needed.

## Features

- **Token-Budget Assembler** — 3-phase strategy: drop low, compress medium, truncate high
- **7 Compressors** — bullet_extract, yaml_struct, mermaid, table, code_compact, dedup_cross
- **SQLite Storage** — Projects, contexts, memories with FTS5 full-text search
- **Usage Tracking** — Block weights, feedback scoring, skill adaptation profiles
- **Weight Adjuster** — Automatic priority adjustment based on usage patterns and feedback
- **Skill Connector** — Pluggable skill system with built-in `GitStatusSkill`
- **Simulation Engine** — Budget sweep, clustering, compression analysis
- **4 Interfaces** — CLI, MCP Server, PySide6 GUI, FastAPI Web App

## Setup

```bash
pip install -e .
```

Or install from requirements:
```bash
pip install -r requirements.txt
```

Raspberry Pi OS (system packages):
```bash
sudo apt install python3-tiktoken python3-click python3-pytest python3-pyside6
pip install mcp --break-system-packages  # or use a venv
```

## Architecture

```
src/
├── core/
│   ├── assembler.py        # Token-budget assembler (3-phase reduction)
│   ├── block.py            # Block data model (content, priority, compress_hint)
│   ├── token_budget.py     # tiktoken-based token estimation (cl100k_base)
│   ├── context.py          # Context container
│   ├── weight_adjuster.py  # Usage/feedback-based priority adjustment
│   ├── skill_connector.py  # Pluggable skill interface + GitStatusSkill
│   ├── simulator.py        # Budget sweep simulation engine
│   ├── clustering.py       # Jaccard-based block clustering
│   ├── skill_graph.py      # Skill dependency DAG
│   └── compressors/
│       ├── base.py
│       ├── bullet_extract.py
│       ├── yaml_struct.py
│       ├── mermaid.py
│       ├── table.py
│       ├── code_compact.py
│       └── dedup_cross.py
├── gui/
│   ├── __main__.py         # GUI entry point
│   ├── main_window.py      # PySide6 main window (tabs: Blocks, Memories, Simulation)
│   ├── block_editor.py     # Block editor with drag-drop reordering
│   ├── memory_editor.py    # Memory editor with FTS search + tag filtering
│   └── widgets/
│       ├── block_card.py   # Block display card
│       ├── budget_bar.py   # Token usage progress bar
│       └── simulation_panel.py  # Cluster map + budget impact chart
├── interfaces/
│   ├── cli.py              # Click CLI (assemble, blocks, projects, memories, usage, feedback, web)
│   └── mcp_server.py       # MCP server (stdio transport)
├── web/
│   ├── app.py              # FastAPI REST API + HTMX frontend
│   ├── templates/          # Jinja2 templates
│   └── static/             # JS + CSS assets
└── storage/
    ├── db.py               # SQLite engine + schema migrations (WAL mode)
    ├── memory.py           # Memory store (KV + FTS5 search)
    ├── project.py          # Project + context store
    └── usage.py            # Usage tracking, feedback, block weights, skill profiles
```

## CLI

```bash
# Assemble context within a token budget
context-pilot assemble --budget 4000 --context project.json
context-pilot assemble --budget 4000 --context project.json --format json

# Manage blocks
context-pilot blocks list --context project.json
context-pilot blocks add --context project.json --content "Text" --priority high
context-pilot blocks add --context project.json --content "Text" --priority medium --compress-hint bullet_extract
context-pilot blocks remove --context project.json --index 2

# Projects
context-pilot projects list
context-pilot projects create --name myproject --description "Description"
context-pilot projects show --name myproject
context-pilot projects delete --name myproject

# Memories (SQLite + FTS5)
context-pilot memories list
context-pilot memories get --key mykey
context-pilot memories set --key mykey --value "value" --tags tag1,tag2
context-pilot memories search --query "search term" --tags tag1
context-pilot memories export --output memories.json
context-pilot memories import --input memories.json

# Usage & feedback
context-pilot usage weights
context-pilot usage skills
context-pilot feedback add --assembly-id ID --block-content "text" --helpful
context-pilot feedback show --assembly-id ID

# Start web server
context-pilot web --host 0.0.0.0 --port 8080
```

### Context file format

```json
{
  "blocks": [
    { "content": "System instructions.", "priority": "high" },
    { "content": "Background context.", "priority": "medium", "compress_hint": "bullet_extract" },
    { "content": "Nice-to-have info.", "priority": "low" }
  ]
}
```

Priority values: `high`, `medium`, `low`.
Compressor hints: `bullet_extract`, `yaml_struct`, `mermaid`, `table`, `code_compact`, `dedup_cross`.

## MCP Server

Start the MCP server (stdio transport, for use with AI tools):

```bash
python -m src.interfaces.mcp_server
```

### Tools

| Tool | Description |
|------|-------------|
| `assemble_context(budget, blocks)` | Assemble blocks within a token budget |
| `list_blocks(blocks)` | Return block summaries with token counts |
| `submit_feedback(assembly_id, block_content, helpful)` | Record assembly feedback |
| `get_block_weight(block_content, project_name?)` | Get block weight and suggested priority |

## Assembler Logic

When total tokens exceed the budget:

1. **Drop** LOW-priority blocks (cheapest loss)
2. **Compress** MEDIUM-priority blocks with a registered `compress_hint`
3. **Truncate** HIGH-priority blocks as last resort (binary search for longest prefix)

## GUI

```bash
python -m src.gui
# or via entry point:
context-pilot-gui
```

Features:
- **Block Editor** — Add, edit, duplicate, delete blocks with drag-drop reordering
- **Memory Editor** — Full-text search, tag filtering, CRUD, context preview
- **Simulation Panel** — Cluster treemap visualization, budget impact chart
- **Budget Bar** — Real-time token usage with colour coding (green/orange/red)
- **Project Management** — Create, open, save projects with multiple contexts

## Web App

```bash
context-pilot web --port 8080
```

HTMX frontend with REST API. Endpoints for token estimation, assembly, projects, memories, and feedback.

## Compressors

| Name | Input | Output |
|------|-------|--------|
| `bullet_extract` | Prose / long sentences | Bullet list (<=12 words/bullet) |
| `yaml_struct` | Key-value text / structured | Compact YAML |
| `mermaid` | Numbered/bulleted steps, process text | `flowchart TD` diagram |
| `table` | Tabular / CSV-like data | Compact key-value rows |
| `code_compact` | Source code | Minified (comments/whitespace removed) |
| `dedup_cross` | Multiple blocks | Cross-block deduplication |

## Building Portable Installers

```bash
# Install build dependencies
pip install -r requirements-dev.txt
sudo apt-get install binutils  # Linux

# Build CLI
python scripts/build_installer.py

# Build GUI
python scripts/build_installer.py --gui

# Build all
python scripts/build_installer.py --all --clean
```

| Platform | Status | Notes |
|----------|--------|-------|
| Linux (aarch64/Raspberry Pi) | Primary target | Tested, single binary |
| Linux (x86_64) | Supported | Build on target architecture |
| macOS | Planned | Produces `.app` bundle |
| Windows | Planned | Produces `.exe` |

Cross-compilation is not supported — build on the target platform.

## Tests

```bash
PYTHONPATH=. python -m pytest tests/ -v
PYTHONPATH=. python -m pytest tests/ -v --cov=src/core --cov-report=term-missing
```

Target: >80% coverage on `src/core/`.

## License

MIT
