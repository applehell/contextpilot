"""Assembly endpoints: assemble, templates, preview, compress, estimate, export."""
from __future__ import annotations

import re as _re
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query, Request

from src.core.block import Block, Priority
from src.core.token_budget import TokenBudget
from src.storage.templates import TemplateStore, ContextTemplate
from src.storage.usage import UsageRecord
from src.web.deps import (
    _block_to_dict,
    _detect_compress_hint,
    _events,
    _get_db,
    _get_memory_store,
    _get_usage_store,
    _make_assembler,
    AssembleRequest,
    CompressRequest,
    EstimateRequest,
    block_hash,
)

router = APIRouter(tags=["assembly"])


@router.post("/api/estimate")
async def estimate_tokens(req: EstimateRequest):
    return {"tokens": TokenBudget.estimate(req.text)}


@router.post("/api/assemble")
async def assemble(req: AssembleRequest):
    blocks = []
    for b in req.blocks:
        try:
            prio = Priority(b.priority)
        except ValueError:
            raise HTTPException(400, f"Invalid priority value: {b.priority}")
        blocks.append(Block(
            content=b.content,
            priority=prio,
            compress_hint=b.compress_hint,
        ))
    assembler = _make_assembler()
    result = assembler.assemble_tracked(blocks, req.budget)

    store = _get_usage_store()
    import time
    records = [
        UsageRecord(
            block_hash=block_hash(b.content),
            project_name=None,
            context_name=None,
            skill_name=None,
            model_id=None,
            included=True,
            token_count=b.token_count,
        )
        for b in result.blocks
    ]
    store.record_usage(records)

    return {
        "assembly_id": result.assembly_id,
        "budget": result.budget,
        "used_tokens": result.used_tokens,
        "block_count": len(result.blocks),
        "blocks": [_block_to_dict(b) for b in result.blocks],
        "dropped_count": len(result.dropped_blocks),
        "dropped": [_block_to_dict(b) for b in result.dropped_blocks],
    }


@router.post("/api/preview-context")
async def preview_context(budget: int = Query(8000, ge=100)):
    _CODE = _re.compile(r"(```|def |class |function |import |from |curl |export |const |let |var )")
    _STEP = _re.compile(r"^(\d+[.)]\s|[-*]\s|#{1,3}\s)", _re.MULTILINE)
    _KV = _re.compile(r"^[A-Za-z][^:=\n]{0,40}(?::[ \t]|[ \t]*=[ \t])", _re.MULTILINE)

    def _detect_hint(text: str):
        if len(_CODE.findall(text)) >= 3: return "code_compact"
        if len(_STEP.findall(text)) >= 3: return "mermaid"
        if len(_KV.findall(text)) >= 3: return "yaml_struct"
        if len(text) > 200: return "bullet_extract"
        return None

    store = _get_memory_store()
    memories = store.list()
    if not memories:
        return {"blocks": [], "dropped": [], "used_tokens": 0, "budget": budget,
                "input_count": 0, "block_count": 0, "dropped_count": 0}

    blocks = []
    for m in memories:
        content = f"[{m.key}] {m.value}"
        hint = _detect_hint(m.value)
        blocks.append(Block(content=content, priority=Priority.MEDIUM, compress_hint=hint))

    selected = []
    dropped = []
    remaining = budget
    for b in blocks:
        if b.token_count <= remaining:
            selected.append(b)
            remaining -= b.token_count
        else:
            dropped.append(b)

    assembler = _make_assembler()
    if selected:
        assembled = assembler.assemble(selected, budget)
    else:
        assembled = []

    return {
        "budget": budget,
        "used_tokens": sum(b.token_count for b in assembled),
        "input_count": len(blocks),
        "block_count": len(assembled),
        "dropped_count": len(dropped),
        "blocks": [_block_to_dict(b) for b in assembled],
        "dropped": [
            {"content_preview": b.content[:80], "token_count": b.token_count}
            for b in dropped[:20]
        ],
    }


@router.post("/api/test-compress")
async def test_compress(req: CompressRequest):
    block = Block(content=req.content, priority=Priority.MEDIUM, compress_hint=req.compress_hint)
    assembler = _make_assembler()
    compressor = assembler._registry.get(req.compress_hint)
    if not compressor:
        return {"error": f"Compressor '{req.compress_hint}' not found."}
    original_tokens = block.token_count
    compressed = compressor.compress(block)
    return {
        "original_tokens": original_tokens,
        "compressed_tokens": compressed.token_count,
        "savings_pct": round((1 - compressed.token_count / max(1, original_tokens)) * 100, 1),
        "compressed_content": compressed.content,
    }


# --- Templates ---

@router.get("/api/templates")
async def list_templates():
    from src.web.deps import _db
    ts = TemplateStore(_db)
    return [{"name": t.name, "description": t.description, "tag_filter": t.tag_filter,
             "key_filter": t.key_filter, "budget": t.budget} for t in ts.list()]


@router.post("/api/templates", status_code=201)
async def save_template(request: Request):
    from src.web.deps import _db
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    if not body.get("name"):
        raise HTTPException(400, "name is required")
    budget = body.get("budget", 4000)
    if not isinstance(budget, (int, float)) or budget <= 0 or budget > 128000:
        raise HTTPException(400, "budget must be > 0 and <= 128000")
    ts = TemplateStore(_db)
    t = ContextTemplate(
        name=body["name"], description=body.get("description", ""),
        tag_filter=body.get("tag_filter", []), key_filter=body.get("key_filter", ""),
        budget=int(budget),
    )
    ts.save(t)
    _events.emit("template", "save", t.name)
    return {"status": "saved", "name": t.name}


@router.get("/api/templates/suggest")
async def suggest_templates():
    from src.web.deps import _db
    store = _get_memory_store()
    memories = store.list()
    if not memories:
        return {"suggestions": []}

    from collections import Counter
    from src.core.token_budget import TokenBudget as _TB

    tag_counts: Counter = Counter()
    prefix_counts: Counter = Counter()
    tag_tokens: Dict[str, int] = {}
    prefix_tokens: Dict[str, int] = {}

    for m in memories:
        tokens = _TB.estimate(m.value)
        prefix = m.key.split("/")[0] if "/" in m.key else m.key
        prefix_counts[prefix] += 1
        prefix_tokens[prefix] = prefix_tokens.get(prefix, 0) + tokens
        for tag in m.tags:
            tag_counts[tag] += 1
            tag_tokens[tag] = tag_tokens.get(tag, 0) + tokens

    existing = {t.name for t in TemplateStore(_db).list()}
    suggestions = []

    for prefix, count in prefix_counts.most_common(20):
        if count < 3:
            continue
        name = f"{prefix}-context"
        if name in existing:
            continue
        total_tok = prefix_tokens[prefix]
        budget = min(max(total_tok, 2000), 16000)
        suggestions.append({
            "name": name,
            "description": f"{count} memories under {prefix}/",
            "tag_filter": [],
            "key_filter": f"{prefix}/",
            "budget": budget,
            "memory_count": count,
            "total_tokens": total_tok,
            "reason": "key_prefix",
        })

    covered_names = {s["name"] for s in suggestions}
    for tag, count in tag_counts.most_common(15):
        if count < 5:
            continue
        name = f"{tag}-context"
        if name in existing or name in covered_names:
            continue
        total_tok = tag_tokens[tag]
        budget = min(max(total_tok, 2000), 16000)
        suggestions.append({
            "name": name,
            "description": f"{count} memories tagged '{tag}'",
            "tag_filter": [tag],
            "key_filter": "",
            "budget": budget,
            "memory_count": count,
            "total_tokens": total_tok,
            "reason": "tag_cluster",
        })

    if len(memories) >= 10 and "all-context" not in existing:
        total = sum(_TB.estimate(m.value) for m in memories)
        suggestions.append({
            "name": "all-context",
            "description": f"All {len(memories)} memories",
            "tag_filter": [],
            "key_filter": "",
            "budget": min(total, 16000),
            "memory_count": len(memories),
            "total_tokens": total,
            "reason": "all",
        })

    suggestions.sort(key=lambda s: s["memory_count"], reverse=True)
    return {"suggestions": suggestions[:12]}


@router.delete("/api/templates/{name}")
async def delete_template(name: str):
    from src.web.deps import _db
    ts = TemplateStore(_db)
    try:
        ts.delete(name)
        return {"status": "deleted"}
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.post("/api/templates/{name}/assemble")
async def assemble_template(name: str):
    from src.web.deps import _db
    ts = TemplateStore(_db)
    try:
        t = ts.get(name)
    except KeyError:
        raise HTTPException(404, f"Template '{name}' not found")

    store = _get_memory_store()
    memories = store.list()

    if t.tag_filter:
        memories = [m for m in memories if any(tag in m.tags for tag in t.tag_filter)]
    if t.key_filter:
        memories = [m for m in memories if t.key_filter.lower() in m.key.lower()]

    from src.core.weight_adjuster import WeightAdjuster
    adjuster = WeightAdjuster(_get_usage_store())

    blocks = []
    for m in memories:
        hint = _detect_compress_hint(m.value)
        b = Block(
            content=m.value,
            priority=Priority.HIGH if getattr(m, "pinned", False) else Priority.MEDIUM,
            compress_hint=hint,
        )
        b = adjuster.adjust_priority(b, adjuster.compute_weight(m.value))
        b.source_key = m.key
        blocks.append(b)

    assembler = _make_assembler()
    result = assembler.assemble_tracked(blocks, t.budget)

    try:
        included_hashes = {block_hash(b.content) for b in result.blocks}
        records = [
            UsageRecord(block_hash=block_hash(b.content), included=block_hash(b.content) in included_hashes, token_count=b.token_count)
            for b in result.input_blocks
        ]
        _get_usage_store().record_usage(records)
    except Exception:
        pass

    def _block_result(b: Block) -> Dict[str, Any]:
        d = _block_to_dict(b)
        d["key"] = b.source_key or ""
        return d

    return {
        "template": t.name,
        "description": t.description,
        "budget": t.budget,
        "assembly_id": result.assembly_id,
        "used_tokens": result.used_tokens,
        "total_matching": len(memories),
        "block_count": len(result.blocks),
        "blocks": [_block_result(b) for b in result.blocks],
        "dropped_count": len(result.dropped_blocks),
        "dropped": [_block_result(b) for b in result.dropped_blocks],
    }


# --- Export as CLAUDE.md ---

@router.get("/api/export-claude-md")
async def export_claude_md(tags: str = Query(""), key_prefix: str = Query("")):
    store = _get_memory_store()
    memories = store.list()

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        memories = [m for m in memories if any(t in m.tags for t in tag_list)]
    if key_prefix:
        memories = [m for m in memories if m.key.startswith(key_prefix)]

    sections = []
    for m in sorted(memories, key=lambda x: x.key):
        heading = m.key.replace("/", " > ").title()
        sections.append(f"## {heading}\n\n{m.value}")

    content = "# Context Pilot Export\n\n" + "\n\n---\n\n".join(sections)
    return {"content": content, "memory_count": len(memories),
            "token_count": TokenBudget.estimate(content)}


@router.get("/api/export-markdown")
async def export_markdown(tags: str = Query(""), key_prefix: str = Query("")):
    store = _get_memory_store()
    memories = store.list()

    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        memories = [m for m in memories if any(t in m.tags for t in tag_list)]
    if key_prefix:
        memories = [m for m in memories if m.key.startswith(key_prefix)]

    grouped: Dict[str, list] = {}
    for m in sorted(memories, key=lambda x: x.key):
        group = m.tags[0] if m.tags else "Untagged"
        grouped.setdefault(group, []).append(m)

    lines = ["# Context Pilot -- Knowledge Export", ""]
    lines.append(f"*{len(memories)} memories exported*\n")
    for group, mems in sorted(grouped.items()):
        lines.append(f"## {group}\n")
        for m in mems:
            lines.append(f"### {m.key}\n")
            tag_str = " ".join(f"`{t}`" for t in m.tags)
            if tag_str:
                lines.append(f"Tags: {tag_str}\n")
            lines.append(m.value)
            lines.append("")
        lines.append("---\n")

    content = "\n".join(lines)
    return {"content": content, "memory_count": len(memories),
            "token_count": TokenBudget.estimate(content)}
