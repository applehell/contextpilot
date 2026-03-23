# Changelog

## v1.0.0 — 2026-03-22

Final release: all interfaces, storage, simulation, and build tooling complete.

- Version bump to 1.0.0
- Complete README with CLI, MCP, GUI, Web, and build documentation
- CHANGELOG covering all development phases

## v0.5.0 — FastAPI Web App

- FastAPI REST API with HTMX frontend
- Endpoints: token estimation, assembly, projects CRUD, memories CRUD + FTS search, feedback
- Static file serving (JS + CSS)
- `context-pilot web` CLI command to start the server

## v0.4.0 — GUI, Storage, Skills

- PySide6 GUI: Main Window with Block Editor, Memory Editor, Budget Bar
- Block Editor: drag-drop reordering, compression preview, duplicate
- Memory Editor: full-text search, tag filtering, CRUD, context preview
- SQLite storage layer with WAL mode and schema migrations (v1-v3)
- MemoryStore with FTS5 full-text search and tag-based filtering
- ProjectStore for project + context persistence
- UsageStore for block usage tracking, feedback, weights, skill profiles
- SkillConnector: pluggable skill system with built-in GitStatusSkill
- WeightAdjuster: automatic priority adjustment from usage + feedback signals
- Additional compressors: `table`, `code_compact`, `dedup_cross`

## v0.3.0 — Phase 6: Simulation Engine

- Simulator: budget sweep across multiple scenarios
- BlockClusterer: Jaccard-similarity agglomerative clustering
- SkillGraph: DAG of skill-to-block dependencies
- SimulationPanel GUI widget: cluster treemap + budget impact chart
- CompressionDelta tracking for savings analysis

## v0.2.0 — Compressors & MCP

- MCP server (stdio transport) with `assemble_context`, `list_blocks`, `submit_feedback`, `get_block_weight`
- Compressors: `bullet_extract`, `yaml_struct`, `mermaid`
- Click CLI: `assemble`, `blocks list/add/remove`
- Context file format (JSON)

## v0.1.0 — Core Engine

- Block data model with Priority enum and lazy token counting
- Context container
- TokenBudget with tiktoken (cl100k_base encoding)
- Assembler: 3-phase reduction (drop low, compress medium, truncate high)
- BaseCompressor interface
