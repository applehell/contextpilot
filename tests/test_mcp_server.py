"""Tests for the MCP server tools."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src.interfaces.mcp_server import (
    assemble_context, list_blocks, submit_feedback, get_block_weight,
    list_templates, assemble_template, suggest_templates,
    memory_set, memory_get, memory_delete, memory_search,
    register_skill,
)


SAMPLE_BLOCKS = [
    {"content": "High priority instructions for the model.", "priority": "high"},
    {"content": "Medium priority background context.", "priority": "medium"},
    {"content": "Low priority extra info.", "priority": "low"},
]


class TestAssembleContext:
    def test_basic_assembly(self):
        result = assemble_context(budget=500, blocks=SAMPLE_BLOCKS)
        assert "blocks" in result
        assert "used_tokens" in result
        assert "budget" in result
        assert result["budget"] == 500
        assert result["block_count"] == len(result["blocks"])

    def test_all_fit_within_budget(self):
        result = assemble_context(budget=500, blocks=SAMPLE_BLOCKS)
        assert result["used_tokens"] <= 500

    def test_tight_budget_drops_low(self):
        result = assemble_context(budget=10, blocks=SAMPLE_BLOCKS)
        priorities = [b["priority"] for b in result["blocks"]]
        assert "low" not in priorities

    def test_empty_blocks(self):
        result = assemble_context(budget=500, blocks=[])
        assert result["blocks"] == []
        assert result["used_tokens"] == 0
        assert result["block_count"] == 0

    def test_blocks_have_token_count(self):
        result = assemble_context(budget=500, blocks=SAMPLE_BLOCKS)
        for b in result["blocks"]:
            assert "token_count" in b
            assert b["token_count"] > 0

    def test_default_priority_medium(self):
        result = assemble_context(budget=500, blocks=[{"content": "Hello world."}])
        assert result["blocks"][0]["priority"] == "medium"

    def test_high_priority_block_retained(self):
        result = assemble_context(budget=5, blocks=SAMPLE_BLOCKS)
        priorities = [b["priority"] for b in result["blocks"]]
        assert "high" in priorities

    def test_result_tokens_match_sum(self):
        result = assemble_context(budget=500, blocks=SAMPLE_BLOCKS)
        computed = sum(b["token_count"] for b in result["blocks"])
        assert computed == result["used_tokens"]


class TestListBlocks:
    def test_basic_list(self):
        result = list_blocks(SAMPLE_BLOCKS)
        assert len(result) == 3

    def test_indices(self):
        result = list_blocks(SAMPLE_BLOCKS)
        for i, item in enumerate(result):
            assert item["index"] == i

    def test_token_counts(self):
        result = list_blocks(SAMPLE_BLOCKS)
        for item in result:
            assert "token_count" in item
            assert item["token_count"] > 0

    def test_content_preview(self):
        result = list_blocks(SAMPLE_BLOCKS)
        for item in result:
            assert "content_preview" in item
            assert len(item["content_preview"]) <= 80

    def test_priorities(self):
        result = list_blocks(SAMPLE_BLOCKS)
        assert result[0]["priority"] == "high"
        assert result[1]["priority"] == "medium"
        assert result[2]["priority"] == "low"

    def test_empty_list(self):
        result = list_blocks([])
        assert result == []

    def test_default_priority(self):
        result = list_blocks([{"content": "plain content"}])
        assert result[0]["priority"] == "medium"


class TestSubmitFeedback:
    def test_records_helpful(self):
        result = submit_feedback(
            assembly_id="asm-001",
            block_content="Some block content",
            helpful=True,
        )
        assert result["status"] == "recorded"
        assert result["helpful"] is True
        assert "block_hash" in result

    def test_records_not_helpful(self):
        result = submit_feedback(
            assembly_id="asm-002",
            block_content="Bad content",
            helpful=False,
        )
        assert result["status"] == "recorded"
        assert result["helpful"] is False


class TestGetBlockWeight:
    def test_returns_weight_info(self):
        result = get_block_weight(block_content="Test block for weight")
        assert "weight" in result
        assert "block_hash" in result
        assert "usage_count" in result
        assert "feedback_score" in result
        assert "suggested_priority" in result

    def test_with_project_name(self):
        result = get_block_weight(block_content="Project block", project_name="myproject")
        assert "weight" in result
        assert result["suggested_priority"] in ("high", "medium", "low")


class TestListTemplates:
    def test_returns_list(self):
        result = list_templates()
        assert isinstance(result, list)

    def test_template_fields(self):
        from src.storage.templates import TemplateStore, ContextTemplate
        from src.interfaces.mcp_server import _get_db
        ts = TemplateStore(_get_db())
        ts.save(ContextTemplate(name="_test_tpl", description="Test", tag_filter=["t"], budget=100))
        try:
            result = list_templates()
            tpl = next(t for t in result if t["name"] == "_test_tpl")
            assert tpl["description"] == "Test"
            assert tpl["tag_filter"] == ["t"]
            assert tpl["budget"] == 100
        finally:
            ts.delete("_test_tpl")


class TestAssembleTemplate:
    def test_not_found(self):
        result = assemble_template(name="_nonexistent_template_xyz")
        assert "error" in result

    def test_assembles_matching_memories(self):
        from src.storage.templates import TemplateStore, ContextTemplate
        from src.storage.memory import Memory
        from src.interfaces.mcp_server import _get_db, _get_memory_store
        db = _get_db()
        ts = TemplateStore(db)
        store = _get_memory_store()

        ts.save(ContextTemplate(name="_test_asm", tag_filter=["_test_tag"], budget=500))
        store.set(Memory(key="_test/mem1", value="Test memory content one", tags=["_test_tag"]))
        store.set(Memory(key="_test/mem2", value="Unrelated memory", tags=["other"]))
        try:
            result = assemble_template(name="_test_asm")
            assert result["template"] == "_test_asm"
            assert result["budget"] == 500
            assert result["total_matching"] == 1
            assert result["block_count"] >= 1
            assert "assembly_id" in result
        finally:
            ts.delete("_test_asm")
            store.delete("_test/mem1")
            store.delete("_test/mem2")


class TestSuggestTemplates:
    def test_empty_returns_empty(self):
        result = suggest_templates()
        assert isinstance(result, list)

    def test_suggests_by_prefix_or_tag(self):
        result = suggest_templates()
        if not result:
            return
        for s in result:
            assert "name" in s
            assert "reason" in s
            assert s["reason"] in ("key_prefix", "tag_cluster", "all")
            assert s["memory_count"] >= 3 or s["reason"] == "all"
            assert s["budget"] > 0


class TestInputValidation:
    # -- assemble_context budget edge cases --

    def test_assemble_zero_budget(self):
        result = assemble_context(budget=0, blocks=SAMPLE_BLOCKS)
        assert "error" in result

    def test_assemble_negative_budget(self):
        result = assemble_context(budget=-1, blocks=SAMPLE_BLOCKS)
        assert "error" in result

    def test_assemble_huge_budget(self):
        result = assemble_context(budget=999999, blocks=SAMPLE_BLOCKS)
        assert "error" in result

    def test_assemble_empty_blocks(self):
        result = assemble_context(budget=4000, blocks=[])
        assert result["blocks"] == []
        assert result["used_tokens"] == 0

    # -- assemble_context malformed blocks --

    def test_assemble_block_missing_content(self):
        result = assemble_context(budget=4000, blocks=[{"priority": "high"}])
        assert "error" not in result
        assert result["block_count"] == 0

    def test_assemble_block_invalid_priority(self):
        result = assemble_context(
            budget=4000,
            blocks=[{"content": "x", "priority": "invalid"}],
        )
        assert result["block_count"] == 0

    # -- memory_set key validation --

    def test_memory_set_empty_key(self):
        result = memory_set(key="", value="x")
        assert "error" in result

    def test_memory_set_whitespace_key(self):
        result = memory_set(key="  ", value="x")
        assert "error" in result

    # -- memory_get / memory_delete nonexistent --

    def test_memory_get_nonexistent(self):
        result = memory_get(key="nonexistent_xyz_123")
        assert isinstance(result, dict)
        assert "error" in result

    def test_memory_delete_nonexistent(self):
        result = memory_delete(key="nonexistent_xyz_123")
        assert isinstance(result, dict)
        assert "error" in result

    # -- memory_search special inputs --

    def test_memory_search_special_chars(self):
        result = memory_search(query="test* AND (foo)")
        assert isinstance(result, list)

    def test_memory_search_empty(self):
        result = memory_search(query="")
        assert isinstance(result, list)

    def test_memory_search_quotes(self):
        result = memory_search(query='"hello world"')
        assert isinstance(result, list)

    # -- register_skill validation --

    def test_register_skill_empty_name(self):
        result = register_skill(name="", description="x")
        assert "error" in result

    # -- templates edge cases --

    def test_list_templates_empty_db(self):
        result = list_templates()
        assert isinstance(result, list)

    def test_suggest_templates_empty(self):
        result = suggest_templates()
        assert isinstance(result, list)

    def test_assemble_template_nonexistent(self):
        result = assemble_template(name="xyz_nonexistent")
        assert "error" in result


class TestAssembleContextUsageTracking:
    @patch("src.interfaces.mcp_server._get_usage_store")
    def test_usage_tracking_error_does_not_fail_assembly(self, mock_store):
        mock_store.side_effect = Exception("DB connection failed")
        result = assemble_context(budget=500, blocks=SAMPLE_BLOCKS)
        assert "blocks" in result
        assert result["block_count"] >= 0
