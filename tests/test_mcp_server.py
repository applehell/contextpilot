"""Tests for the MCP server tools."""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from src.interfaces.mcp_server import assemble_context, list_blocks, submit_feedback, get_block_weight


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


class TestAssembleContextUsageTracking:
    @patch("src.interfaces.mcp_server._get_usage_store")
    def test_usage_tracking_error_does_not_fail_assembly(self, mock_store):
        mock_store.side_effect = Exception("DB connection failed")
        result = assemble_context(budget=500, blocks=SAMPLE_BLOCKS)
        assert "blocks" in result
        assert result["block_count"] >= 0
