"""Context Pilot MCP Server — exposes assembler, memories, and skill registry as MCP tools."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from src.core.assembler import Assembler
import re

from src.core.block import Block, Priority
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.code_compact import CodeCompactCompressor
from src.core.compressors.mermaid import MermaidCompressor
from src.core.compressors.yaml_struct import YamlStructCompressor
from src.core.relevance import RelevanceEngine
from src.core.skill_registry import SkillRegistry
from src.storage.db import Database
from src.storage.memory import Memory, MemoryStore
from src.storage.memory_activity import MemoryActivityLog
from src.storage.usage import UsageStore, UsageRecord, FeedbackRecord, block_hash

mcp = FastMCP("context-pilot")

_assembler = Assembler(compressors=[
    BulletExtractCompressor(),
    CodeCompactCompressor(),
    YamlStructCompressor(),
    MermaidCompressor(),
])
_relevance = RelevanceEngine()

_db_path = Path.home() / ".contextpilot" / "data.db"
_db: Optional[Database] = None
_usage_store: Optional[UsageStore] = None
_memory_store: Optional[MemoryStore] = None
_activity_log: Optional[MemoryActivityLog] = None

# ── Shared skill registry (singleton, accessible from GUI) ────────────

_registry = SkillRegistry.instance()


def _get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(_db_path)
    return _db


def _get_usage_store() -> UsageStore:
    global _usage_store
    if _usage_store is None:
        _usage_store = UsageStore(_get_db())
    return _usage_store


def _get_memory_store() -> MemoryStore:
    global _memory_store
    if _memory_store is None:
        _memory_store = MemoryStore(_get_db())
    return _memory_store


def _get_activity_log() -> MemoryActivityLog:
    global _activity_log
    if _activity_log is None:
        _activity_log = MemoryActivityLog(_get_db())
    return _activity_log


def _dicts_to_blocks(raw: List[Dict[str, Any]]) -> List[Block]:
    return [
        Block(
            content=item["content"],
            priority=Priority(item.get("priority", "medium")),
            compress_hint=item.get("compress_hint"),
        )
        for item in raw
    ]


_CODE_INDICATORS = re.compile(
    r"(```|def |class |function |import |from |curl |export |const |let |var )"
)
_STEP_INDICATORS = re.compile(
    r"^(\d+[.)]\s|[-*]\s|#{1,3}\s)", re.MULTILINE
)
_KV_INDICATORS = re.compile(
    r"^[A-Za-z][^:=\n]{0,40}(?::[ \t]|[ \t]*=[ \t])", re.MULTILINE
)


def _detect_compress_hint(text: str) -> Optional[str]:
    """Auto-detect the best compressor for a memory's content."""
    code_matches = len(_CODE_INDICATORS.findall(text))
    step_matches = len(_STEP_INDICATORS.findall(text))
    kv_matches = len(_KV_INDICATORS.findall(text))

    # Code-heavy content
    if code_matches >= 3:
        return "code_compact"
    # Step-based / workflow content → mermaid
    if step_matches >= 3:
        return "mermaid"
    # Key-value structured content
    if kv_matches >= 3:
        return "yaml_struct"
    # General prose
    if len(text) > 200:
        return "bullet_extract"
    return None


def _block_to_dict(b: Block) -> Dict[str, Any]:
    return {
        "content": b.content,
        "priority": b.priority.value if hasattr(b.priority, 'value') else str(b.priority),
        "compress_hint": b.compress_hint,
        "token_count": b.token_count,
    }


# ══════════════════════════════════════════════════════════════════════
# SKILL REGISTRATION
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def register_skill(
    name: str,
    description: str,
    context_hints: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Register an external skill/agent with Context Pilot.

    Once registered, the skill can request its relevant context blocks
    via get_skill_context and read/write memories.

    Args:
        name: Unique skill identifier (e.g. 'my-agent', 'code-reviewer').
        description: What this skill does.
        context_hints: Keywords describing what context is relevant
                       (e.g. ['python', 'testing', 'api']).

    Returns registration confirmation with skill_id.
    """
    _registry.register(name, description, context_hints)
    return {
        "status": "registered",
        "skill_name": name,
        "message": f"Skill '{name}' registered. Use get_skill_context to receive relevant blocks.",
    }


@mcp.tool()
def unregister_skill(name: str) -> Dict[str, Any]:
    """Unregister an external skill from Context Pilot.

    Args:
        name: The skill name used during registration.
    """
    if _registry.unregister(name):
        return {"status": "unregistered", "skill_name": name}
    return {"status": "not_found", "skill_name": name}


@mcp.tool()
def list_registered_skills() -> List[Dict[str, Any]]:
    """List all currently registered external skills.

    Returns a list of skill registrations with name, description,
    context_hints, registration time, and usage stats.
    """
    return [s.to_dict() for s in _registry.list_all()]


@mcp.tool()
def heartbeat(name: str) -> Dict[str, Any]:
    """Send a heartbeat to keep the skill registration alive.

    Args:
        name: The registered skill name.
    """
    if not _registry.heartbeat(name):
        return {"status": "not_registered", "message": "Call register_skill first."}
    return {"status": "ok", "skill_name": name}


# ══════════════════════════════════════════════════════════════════════
# CONTEXT DELIVERY
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_skill_context(
    skill_name: str,
    token_budget: int = 4000,
    blocks: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Get relevant context blocks for a registered skill.

    Uses the skill's context_hints to score and select the most relevant
    blocks from the available pool, fitting within the token budget.

    Args:
        skill_name: The registered skill name.
        token_budget: Max tokens for the context window (default 4000).
        blocks: Optional block pool. If not provided, uses memories as blocks.

    Returns selected blocks with relevance scores.
    """
    skill = _registry.get(skill_name)
    if skill is None:
        return {"error": f"Skill '{skill_name}' not registered. Call register_skill first."}

    _registry.heartbeat(skill_name)
    hints = skill.context_hints

    # Build block pool
    if blocks:
        pool = _dicts_to_blocks(blocks)
    else:
        # Use memories as block pool with auto-detected compress hints
        try:
            store = _get_memory_store()
            memories = store.list()
            pool = []
            for m in memories:
                content = f"[{m.key}] {m.value}"
                hint = _detect_compress_hint(m.value)
                pool.append(Block(
                    content=content,
                    priority=Priority.MEDIUM,
                    compress_hint=hint,
                ))
        except Exception:
            pool = []

    if not pool:
        return {"blocks": [], "total_tokens": 0, "message": "No blocks available."}

    # Load history for this skill
    history = {}
    try:
        usage = _get_usage_store()
        history = usage.get_skill_relevance(skill_name)
    except Exception:
        pass

    # Score and select
    scores = _relevance.score_blocks(pool, skill_name, hints, history)
    selected, dropped = _relevance.select_blocks(pool, scores, token_budget)

    # Assemble within budget (may compress)
    if selected:
        assembled = _assembler.assemble(selected, token_budget)
    else:
        assembled = []

    # Record outcomes
    try:
        usage = _get_usage_store()
        for b in assembled:
            usage.record_skill_relevance(skill_name, block_hash(b.content), included=True)
        for b in dropped:
            usage.record_skill_relevance(skill_name, block_hash(b.content), included=False)
    except Exception:
        pass

    _registry.add_blocks_served(skill_name, len(assembled))

    # Build score map for response
    score_map = {s.block_hash: s.combined for s in scores}

    return {
        "skill_name": skill_name,
        "token_budget": token_budget,
        "total_tokens": sum(b.token_count for b in assembled),
        "blocks_selected": len(assembled),
        "blocks_dropped": len(dropped),
        "blocks": [
            {**_block_to_dict(b), "relevance": score_map.get(block_hash(b.content), 0.5)}
            for b in assembled
        ],
    }


# ══════════════════════════════════════════════════════════════════════
# MEMORY API
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def memory_list(tag: Optional[str] = None) -> List[Dict[str, Any]]:
    """List all memories, optionally filtered by tag.

    Args:
        tag: Optional tag to filter by.
    """
    store = _get_memory_store()
    if tag:
        memories = store.search("", tags=[tag])
    else:
        memories = store.list()
    return [
        {
            "key": m.key,
            "value": m.value[:200],
            "tags": m.tags,
            "token_count": len(m.value.split()) * 2,  # rough estimate
        }
        for m in memories
    ]


@mcp.tool()
def memory_get(key: str) -> Dict[str, Any]:
    """Get a specific memory by key.

    Args:
        key: The memory key.
    """
    store = _get_memory_store()
    try:
        m = store.get(key)
        _get_activity_log().record("loaded", key)
        return {"key": m.key, "value": m.value, "tags": m.tags, "metadata": m.metadata}
    except KeyError:
        return {"error": f"Memory '{key}' not found."}


@mcp.tool()
def memory_set(key: str, value: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """Create or update a memory.

    Args:
        key: Unique memory key.
        value: Memory content.
        tags: Optional list of tags.
    """
    store = _get_memory_store()
    # Determine if this is a create or update
    is_update = False
    try:
        store.get(key)
        is_update = True
    except KeyError:
        pass
    store.set(Memory(key=key, value=value, tags=tags or []))
    op = "updated" if is_update else "created"
    tag_info = f" tags=[{', '.join(tags)}]" if tags else ""
    _get_activity_log().record(op, key, f"{len(value)} chars{tag_info}")
    return {"status": "saved", "key": key}


@mcp.tool()
def memory_delete(key: str) -> Dict[str, Any]:
    """Delete a memory by key.

    Args:
        key: The memory key to delete.
    """
    store = _get_memory_store()
    try:
        store.delete(key)
        _get_activity_log().record("deleted", key)
        return {"status": "deleted", "key": key}
    except KeyError:
        return {"error": f"Memory '{key}' not found."}


@mcp.tool()
def memory_search(query: str, tags: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Search memories by text query and/or tags.

    Args:
        query: Search text.
        tags: Optional tags to filter by.
    """
    store = _get_memory_store()
    results = store.search(query, tags=tags)
    tag_info = f" tags=[{', '.join(tags)}]" if tags else ""
    _get_activity_log().record("searched", query or "*", f"{len(results)} Treffer{tag_info}")
    return [
        {"key": m.key, "value": m.value[:200], "tags": m.tags}
        for m in results
    ]


# ══════════════════════════════════════════════════════════════════════
# ASSEMBLY (existing, unchanged)
# ══════════════════════════════════════════════════════════════════════

@mcp.tool()
def assemble_context(budget: int, blocks: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Assemble blocks into an optimised context within the given token budget.

    Each block dict must have a ``content`` key (str). Optional keys:
    ``priority`` (``"high"`` | ``"medium"`` | ``"low"``, default ``"medium"``)
    and ``compress_hint`` (str, name of a registered compressor).
    """
    block_objs = _dicts_to_blocks(blocks)
    assembly = _assembler.assemble_tracked(block_objs, budget)

    try:
        store = _get_usage_store()
        records = []
        included_hashes = {block_hash(b.content) for b in assembly.blocks}
        for b in assembly.input_blocks:
            bh = block_hash(b.content)
            records.append(UsageRecord(
                block_hash=bh,
                included=bh in included_hashes,
                token_count=b.token_count,
            ))
        store.record_usage(records)
    except Exception:
        pass

    return {
        "budget": budget,
        "assembly_id": assembly.assembly_id,
        "used_tokens": assembly.used_tokens,
        "block_count": len(assembly.blocks),
        "blocks": [_block_to_dict(b) for b in assembly.blocks],
    }


@mcp.tool()
def list_blocks(blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a summary of the provided blocks including token counts."""
    block_objs = _dicts_to_blocks(blocks)
    return [
        {
            "index": i,
            "content_preview": b.content[:80],
            "priority": b.priority.value,
            "compress_hint": b.compress_hint,
            "token_count": b.token_count,
        }
        for i, b in enumerate(block_objs)
    ]


@mcp.tool()
def submit_feedback(assembly_id: str, block_content: str, helpful: bool) -> Dict[str, Any]:
    """Submit feedback on whether a block in an assembly was helpful."""
    bh = block_hash(block_content)
    store = _get_usage_store()
    store.record_feedback(FeedbackRecord(
        assembly_id=assembly_id, block_hash=bh, helpful=helpful,
    ))
    return {"status": "recorded", "block_hash": bh, "helpful": helpful}


@mcp.tool()
def get_block_weight(block_content: str, project_name: Optional[str] = None) -> Dict[str, Any]:
    """Get the computed weight and usage statistics for a block."""
    from src.core.weight_adjuster import WeightAdjuster
    store = _get_usage_store()
    adjuster = WeightAdjuster(store)
    w = adjuster.compute_weight(block_content, project_name)
    return {
        "block_hash": w.block_hash,
        "weight": w.weight,
        "usage_count": w.usage_count,
        "feedback_score": w.feedback_score,
        "suggested_priority": "high" if w.weight >= 1.5 else ("low" if w.weight <= 0.5 else "medium"),
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["stdio", "sse", "streamable-http"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8400)
    args = parser.parse_args()

    if args.transport in ("sse", "streamable-http"):
        import os
        os.environ.setdefault("MCP_SSE_PORT", str(args.port))
        mcp.settings.host = args.host
        mcp.settings.port = args.port
        if args.host == "0.0.0.0":
            mcp.settings.transport_security = None

    mcp.run(transport=args.transport)
