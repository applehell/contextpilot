"""Context Pilot CLI — Click-based command-line interface."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import click

from src.core.assembler import Assembler
from src.core.block import Block, Priority
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.mermaid import MermaidCompressor
from src.core.compressors.yaml_struct import YamlStructCompressor
from src.storage.db import Database
from src.storage.project import ProjectStore, ProjectMeta, ContextConfig
from src.storage.memory import MemoryStore, Memory
from src.storage.usage import UsageStore, FeedbackRecord, block_hash


DEFAULT_DB_PATH = Path.home() / ".contextpilot" / "data.db"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_context(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with open(path) as f:
        data = json.load(f)
    return data.get("blocks", [])


def _save_context(path: Path, blocks: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"blocks": blocks}, f, indent=2)


def _dict_to_block(d: Dict[str, Any]) -> Block:
    return Block(
        content=d["content"],
        priority=Priority(d.get("priority", "medium")),
        compress_hint=d.get("compress_hint"),
    )


def _block_to_dict(b: Block) -> Dict[str, Any]:
    return {
        "content": b.content,
        "priority": b.priority.value,
        "compress_hint": b.compress_hint,
        "token_count": b.token_count,
    }


def _make_assembler() -> Assembler:
    return Assembler(compressors=[
        BulletExtractCompressor(),
        YamlStructCompressor(),
        MermaidCompressor(),
    ])


def _get_db(ctx: click.Context) -> Database:
    if "db" not in ctx.obj:
        db_path = ctx.obj.get("db_path", DEFAULT_DB_PATH)
        ctx.obj["db"] = Database(db_path)
    return ctx.obj["db"]


# ---------------------------------------------------------------------------
# CLI root
# ---------------------------------------------------------------------------

@click.group()
@click.option("--db-path", default=None, type=click.Path(),
              help="SQLite database path (default: ~/.contextpilot/data.db).")
@click.pass_context
def cli(ctx: click.Context, db_path: Optional[str]) -> None:
    """Context Pilot — smart context management for AI models."""
    ctx.ensure_object(dict)
    if db_path:
        ctx.obj["db_path"] = Path(db_path)


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--budget", required=True, type=int, help="Token budget for assembly.")
@click.option("--context", "context_path", required=True, type=click.Path(), help="Path to context JSON file.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
def assemble(budget: int, context_path: str, fmt: str) -> None:
    """Assemble context blocks within a token budget."""
    path = Path(context_path)
    raw_blocks = _load_context(path)
    if not raw_blocks:
        click.echo("No blocks found in context file.", err=True)
        sys.exit(1)

    blocks = [_dict_to_block(d) for d in raw_blocks]
    assembler = _make_assembler()
    result = assembler.assemble(blocks, budget)

    if fmt == "json":
        out = {
            "budget": budget,
            "used_tokens": sum(b.token_count for b in result),
            "block_count": len(result),
            "blocks": [_block_to_dict(b) for b in result],
        }
        click.echo(json.dumps(out, indent=2))
    else:
        total = sum(b.token_count for b in result)
        click.echo(f"Assembled {len(result)} block(s), {total}/{budget} tokens used.\n")
        for i, b in enumerate(result, 1):
            click.echo(f"--- Block {i} [{b.priority.value}] ({b.token_count} tokens) ---")
            click.echo(b.content)
            click.echo()


# ---------------------------------------------------------------------------
# blocks
# ---------------------------------------------------------------------------

@cli.group()
def blocks() -> None:
    """Manage blocks in a context file."""


@blocks.command("list")
@click.option("--context", "context_path", required=True, type=click.Path(), help="Path to context JSON file.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
def blocks_list(context_path: str, fmt: str) -> None:
    """List all blocks in a context file."""
    path = Path(context_path)
    raw_blocks = _load_context(path)

    if fmt == "json":
        click.echo(json.dumps(raw_blocks, indent=2))
    else:
        if not raw_blocks:
            click.echo("No blocks.")
            return
        for i, d in enumerate(raw_blocks):
            hint = d.get("compress_hint") or "-"
            preview = d["content"][:60].replace("\n", " ")
            click.echo(f"[{i}] {d.get('priority', 'medium'):6s}  hint={hint:20s}  {preview!r}")


@blocks.command("add")
@click.option("--context", "context_path", required=True, type=click.Path(), help="Path to context JSON file.")
@click.option("--content", required=True, help="Block content.")
@click.option("--priority", default="medium", type=click.Choice(["high", "medium", "low"]), show_default=True)
@click.option("--compress-hint", default=None, help="Compressor name hint (e.g. bullet_extract).")
def blocks_add(context_path: str, content: str, priority: str, compress_hint: Optional[str]) -> None:
    """Add a block to a context file."""
    path = Path(context_path)
    raw_blocks = _load_context(path)
    entry: Dict[str, Any] = {"content": content, "priority": priority}
    if compress_hint:
        entry["compress_hint"] = compress_hint
    raw_blocks.append(entry)
    _save_context(path, raw_blocks)
    click.echo(f"Added block [{len(raw_blocks) - 1}] to {path}.")


@blocks.command("remove")
@click.option("--context", "context_path", required=True, type=click.Path(), help="Path to context JSON file.")
@click.option("--index", required=True, type=int, help="Zero-based index of block to remove.")
def blocks_remove(context_path: str, index: int) -> None:
    """Remove a block from a context file by index."""
    path = Path(context_path)
    raw_blocks = _load_context(path)
    if index < 0 or index >= len(raw_blocks):
        click.echo(f"Index {index} out of range (0–{len(raw_blocks) - 1}).", err=True)
        sys.exit(1)
    removed = raw_blocks.pop(index)
    _save_context(path, raw_blocks)
    click.echo(f"Removed block [{index}]: {removed['content'][:40]!r}")


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------

@cli.group()
@click.pass_context
def projects(ctx: click.Context) -> None:
    """Manage projects."""
    ctx.ensure_object(dict)
    ctx.obj["project_store"] = ProjectStore(_get_db(ctx))


@projects.command("list")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def projects_list(ctx: click.Context, fmt: str) -> None:
    """List all projects."""
    store: ProjectStore = ctx.obj["project_store"]
    items = store.list_projects()
    if fmt == "json":
        click.echo(json.dumps([m.to_dict() for m in items], indent=2))
    else:
        if not items:
            click.echo("No projects.")
            return
        for m in items:
            click.echo(f"  {m.name:30s}  {m.description[:50]}")


@projects.command("create")
@click.option("--name", required=True, help="Project name.")
@click.option("--description", "desc", default="", help="Project description.")
@click.pass_context
def projects_create(ctx: click.Context, name: str, desc: str) -> None:
    """Create a new project."""
    store: ProjectStore = ctx.obj["project_store"]
    try:
        store.create(ProjectMeta(name=name, description=desc))
        click.echo(f"Project '{name}' created.")
    except FileExistsError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@projects.command("delete")
@click.option("--name", required=True, help="Project name.")
@click.pass_context
def projects_delete(ctx: click.Context, name: str) -> None:
    """Delete a project."""
    store: ProjectStore = ctx.obj["project_store"]
    try:
        store.delete(name)
        click.echo(f"Project '{name}' deleted.")
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@projects.command("show")
@click.option("--name", required=True, help="Project name.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def projects_show(ctx: click.Context, name: str, fmt: str) -> None:
    """Show project details."""
    store: ProjectStore = ctx.obj["project_store"]
    try:
        meta, contexts = store.load(name)
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if fmt == "json":
        click.echo(json.dumps({"meta": meta.to_dict(), "contexts": [c.to_dict() for c in contexts]}, indent=2))
    else:
        click.echo(f"Project: {meta.name}")
        click.echo(f"Description: {meta.description}")
        click.echo(f"Contexts: {len(contexts)}")
        for c in contexts:
            click.echo(f"  - {c.name} ({len(c.blocks)} blocks)")


@projects.command("add-context")
@click.option("--name", required=True, help="Project name.")
@click.option("--context-name", required=True, help="Context configuration name.")
@click.pass_context
def projects_add_context(ctx: click.Context, name: str, context_name: str) -> None:
    """Add an empty context configuration to a project."""
    store: ProjectStore = ctx.obj["project_store"]
    try:
        store.add_context(name, ContextConfig(name=context_name))
        click.echo(f"Context '{context_name}' added to project '{name}'.")
    except (FileNotFoundError, ValueError) as e:
        click.echo(str(e), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# memories
# ---------------------------------------------------------------------------

@cli.group()
@click.pass_context
def memories(ctx: click.Context) -> None:
    """Manage memories (key-value store)."""
    ctx.ensure_object(dict)
    ctx.obj["memory_store"] = MemoryStore(_get_db(ctx))


@memories.command("list")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def memories_list(ctx: click.Context, fmt: str) -> None:
    """List all memories."""
    store: MemoryStore = ctx.obj["memory_store"]
    items = store.list()
    if fmt == "json":
        click.echo(json.dumps([m.to_dict() for m in items], indent=2))
    else:
        if not items:
            click.echo("No memories.")
            return
        for m in items:
            tags = ", ".join(m.tags) if m.tags else "-"
            preview = m.value[:50].replace("\n", " ")
            click.echo(f"  {m.key:30s}  tags=[{tags}]  {preview!r}")


@memories.command("get")
@click.option("--key", required=True, help="Memory key.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def memories_get(ctx: click.Context, key: str, fmt: str) -> None:
    """Get a memory by key."""
    store: MemoryStore = ctx.obj["memory_store"]
    try:
        m = store.get(key)
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    if fmt == "json":
        click.echo(json.dumps(m.to_dict(), indent=2))
    else:
        click.echo(f"Key: {m.key}")
        click.echo(f"Tags: {', '.join(m.tags) if m.tags else '-'}")
        click.echo(f"Value:\n{m.value}")


@memories.command("set")
@click.option("--key", required=True, help="Memory key.")
@click.option("--value", required=True, help="Memory value.")
@click.option("--tags", default="", help="Comma-separated tags.")
@click.pass_context
def memories_set(ctx: click.Context, key: str, value: str, tags: str) -> None:
    """Set a memory (creates or updates)."""
    store: MemoryStore = ctx.obj["memory_store"]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    store.set(Memory(key=key, value=value, tags=tag_list))
    click.echo(f"Memory '{key}' saved.")


@memories.command("delete")
@click.option("--key", required=True, help="Memory key.")
@click.pass_context
def memories_delete(ctx: click.Context, key: str) -> None:
    """Delete a memory."""
    store: MemoryStore = ctx.obj["memory_store"]
    try:
        store.delete(key)
        click.echo(f"Memory '{key}' deleted.")
    except KeyError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@memories.command("search")
@click.option("--query", "q", default="", help="Search query (matches key and value).")
@click.option("--tags", default="", help="Comma-separated tags to filter by.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def memories_search(ctx: click.Context, q: str, tags: str, fmt: str) -> None:
    """Search memories by query and/or tags."""
    store: MemoryStore = ctx.obj["memory_store"]
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    results = store.search(q, tag_list)
    if fmt == "json":
        click.echo(json.dumps([m.to_dict() for m in results], indent=2))
    else:
        if not results:
            click.echo("No results.")
            return
        for m in results:
            tag_str = ", ".join(m.tags) if m.tags else "-"
            preview = m.value[:50].replace("\n", " ")
            click.echo(f"  {m.key:30s}  tags=[{tag_str}]  {preview!r}")


@memories.command("export")
@click.option("--output", "out_path", required=True, type=click.Path(), help="Output file path.")
@click.pass_context
def memories_export(ctx: click.Context, out_path: str) -> None:
    """Export all memories to a JSON file."""
    store: MemoryStore = ctx.obj["memory_store"]
    Path(out_path).write_text(store.export_json())
    click.echo(f"Exported to {out_path}.")


@memories.command("import")
@click.option("--input", "in_path", required=True, type=click.Path(exists=True), help="Input JSON file path.")
@click.option("--merge/--replace", default=True, help="Merge with existing or replace all.")
@click.pass_context
def memories_import(ctx: click.Context, in_path: str, merge: bool) -> None:
    """Import memories from a JSON file."""
    store: MemoryStore = ctx.obj["memory_store"]
    data = Path(in_path).read_text()
    count = store.import_json(data, merge=merge)
    mode = "merged" if merge else "replaced"
    click.echo(f"Imported {count} memories ({mode}).")


@memories.command("import-claude")
@click.option("--input", "in_path", required=True, type=click.Path(exists=True),
              help="Path to CLAUDE.md file.")
@click.option("--merge/--replace", default=True, help="Merge with existing or replace all.")
@click.pass_context
def memories_import_claude(ctx: click.Context, in_path: str, merge: bool) -> None:
    """Import memories from a Claude CLAUDE.md file."""
    from src.importers.claude import import_claude_file

    store: MemoryStore = ctx.obj["memory_store"]
    memories = import_claude_file(Path(in_path))
    if not merge:
        for m in store.search("", ["claude"]):
            store.delete(m.key)
    for m in memories:
        store.set(m)
    click.echo(f"Imported {len(memories)} memories from Claude file.")


@memories.command("import-copilot")
@click.option("--input", "in_path", required=True, type=click.Path(exists=True),
              help="Path to copilot-instructions.md file.")
@click.option("--merge/--replace", default=True, help="Merge with existing or replace all.")
@click.pass_context
def memories_import_copilot(ctx: click.Context, in_path: str, merge: bool) -> None:
    """Import memories from a GitHub Copilot copilot-instructions.md file."""
    from src.importers.copilot import import_copilot_file

    store: MemoryStore = ctx.obj["memory_store"]
    memories = import_copilot_file(Path(in_path))
    if not merge:
        for m in store.search("", ["copilot"]):
            store.delete(m.key)
    for m in memories:
        store.set(m)
    click.echo(f"Imported {len(memories)} memories from Copilot file.")


# ---------------------------------------------------------------------------
# usage
# ---------------------------------------------------------------------------

@cli.group()
@click.pass_context
def usage(ctx: click.Context) -> None:
    """View usage statistics and block weights."""
    ctx.ensure_object(dict)
    ctx.obj["usage_store"] = UsageStore(_get_db(ctx))


@usage.command("weights")
@click.option("--project", default=None, help="Filter by project name.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def usage_weights(ctx: click.Context, project: Optional[str], fmt: str) -> None:
    """Show block weights computed from usage data."""
    store: UsageStore = ctx.obj["usage_store"]
    from src.core.weight_adjuster import WeightAdjuster
    adjuster = WeightAdjuster(store)
    count = adjuster.recompute_all_weights(project)
    counts = store.get_usage_counts(project)

    if fmt == "json":
        items = []
        for bh, c in counts.items():
            w = store.get_weight(bh, project)
            items.append({
                "block_hash": bh,
                "usage_count": c,
                "weight": w.weight if w else 1.0,
                "feedback_score": w.feedback_score if w else 0.0,
            })
        click.echo(json.dumps(items, indent=2))
    else:
        if not counts:
            click.echo("No usage data yet.")
            return
        click.echo(f"{'Hash':18s} {'Uses':>5s} {'Weight':>7s} {'Feedback':>9s}")
        click.echo("-" * 42)
        for bh, c in sorted(counts.items(), key=lambda x: -x[1]):
            w = store.get_weight(bh, project)
            weight = f"{w.weight:.2f}" if w else "1.00"
            fb = f"{w.feedback_score:+.2f}" if w else "+0.00"
            click.echo(f"{bh:18s} {c:5d} {weight:>7s} {fb:>9s}")


# ---------------------------------------------------------------------------
# feedback
# ---------------------------------------------------------------------------

@cli.group()
@click.pass_context
def feedback(ctx: click.Context) -> None:
    """Provide feedback on assembly results."""
    ctx.ensure_object(dict)
    ctx.obj["usage_store"] = UsageStore(_get_db(ctx))


@feedback.command("add")
@click.option("--assembly-id", required=True, help="Assembly ID to provide feedback for.")
@click.option("--block-content", required=True, help="Content of the block to rate.")
@click.option("--helpful/--not-helpful", required=True, help="Whether the block was helpful.")
@click.pass_context
def feedback_add(ctx: click.Context, assembly_id: str, block_content: str, helpful: bool) -> None:
    """Rate a block from an assembly as helpful or not helpful."""
    store: UsageStore = ctx.obj["usage_store"]
    bh = block_hash(block_content)
    store.record_feedback(FeedbackRecord(
        assembly_id=assembly_id,
        block_hash=bh,
        helpful=helpful,
    ))
    label = "helpful" if helpful else "not helpful"
    click.echo(f"Feedback recorded: block {bh} marked as {label}.")


@feedback.command("show")
@click.option("--assembly-id", required=True, help="Assembly ID to view feedback for.")
@click.option("--format", "fmt", default="text", type=click.Choice(["text", "json"]), show_default=True)
@click.pass_context
def feedback_show(ctx: click.Context, assembly_id: str, fmt: str) -> None:
    """Show feedback for an assembly."""
    store: UsageStore = ctx.obj["usage_store"]
    items = store.get_assembly_feedback(assembly_id)

    if fmt == "json":
        click.echo(json.dumps([
            {"block_hash": f.block_hash, "helpful": f.helpful}
            for f in items
        ], indent=2))
    else:
        if not items:
            click.echo("No feedback for this assembly.")
            return
        for f in items:
            label = "helpful" if f.helpful else "not helpful"
            click.echo(f"  {f.block_hash}  {label}")


@cli.command()
@click.option("--host", default="0.0.0.0", help="Bind host.")
@click.option("--port", default=8080, type=int, help="Bind port.")
@click.option("--reload", is_flag=True, help="Enable auto-reload.")
@click.pass_context
def web(ctx: click.Context, host: str, port: int, reload: bool) -> None:
    """Start the Context Pilot web server."""
    import uvicorn
    from src.web.app import create_app

    db_path = ctx.obj.get("db_path", DEFAULT_DB_PATH)
    create_app(db_path)
    uvicorn.run("src.web.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    cli()
