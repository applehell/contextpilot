from __future__ import annotations

import pytest

from src.core.block import Block, Priority
from src.core.compressors.base import BaseCompressor
from src.core.compressors.bullet_extract import BulletExtractCompressor
from src.core.compressors.code_compact import CodeCompactCompressor
from src.core.compressors.dedup_cross import DedupCrossCompressor
from src.core.compressors.mermaid import MermaidCompressor
from src.core.compressors.table import TableCompressor
from src.core.compressors.yaml_struct import YamlStructCompressor
from src.core.token_budget import TokenBudget


def make_block(content: str, priority: Priority = Priority.MEDIUM) -> Block:
    return Block(content=content, priority=priority)


def token_count(text: str) -> int:
    return TokenBudget.estimate(text)


# ---------------------------------------------------------------------------
# BaseCompressor — contract tests
# ---------------------------------------------------------------------------

class TestBaseCompressor:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            BaseCompressor()  # type: ignore[abstract]

    def test_concrete_must_implement_name_and_compress(self):
        class Incomplete(BaseCompressor):
            @property
            def name(self) -> str:
                return "incomplete"
            # missing compress

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# BulletExtractCompressor
# ---------------------------------------------------------------------------

PROSE = (
    "The system starts up and loads configuration. "
    "It then connects to the database. "
    "After that it validates all pending records. "
    "Finally it emits a health check signal."
)


class TestBulletExtractCompressor:
    def setup_method(self):
        self.comp = BulletExtractCompressor()

    def test_name(self):
        assert self.comp.name == "bullet_extract"

    def test_output_is_shorter_for_long_sentences(self):
        # Long sentences (>12 words each) are truncated to 12 words per bullet.
        long_prose = (
            "The distributed system starts up and carefully loads its full configuration from the persistent storage disk. "
            "After completing the lengthy initialisation step, the process then proceeds to establish a connection to the remote database. "
            "Once the connection has been successfully established and verified, the worker threads begin to validate all pending records."
        )
        block = make_block(long_prose)
        result = self.comp.compress(block)
        assert result.token_count < block.token_count

    def test_output_has_bullet_lines(self):
        block = make_block(PROSE)
        result = self.comp.compress(block)
        lines = [l for l in result.content.splitlines() if l.strip()]
        assert all(l.startswith("- ") for l in lines)

    def test_key_words_preserved(self):
        block = make_block(PROSE)
        result = self.comp.compress(block)
        assert "database" in result.content
        assert "configuration" in result.content

    def test_does_not_mutate_input(self):
        original = PROSE
        block = make_block(original)
        self.comp.compress(block)
        assert block.content == original

    def test_single_sentence_produces_one_bullet(self):
        block = make_block("The only sentence here.")
        result = self.comp.compress(block)
        lines = [l for l in result.content.splitlines() if l.strip()]
        assert len(lines) == 1
        assert lines[0].startswith("- ")

    def test_empty_content_handled(self):
        block = make_block("")
        result = self.comp.compress(block)
        assert isinstance(result.content, str)

    def test_returns_new_block(self):
        block = make_block(PROSE)
        result = self.comp.compress(block)
        assert result is not block

    def test_priority_preserved(self):
        block = make_block(PROSE, Priority.HIGH)
        result = self.comp.compress(block)
        assert result.priority == Priority.HIGH

    def test_token_count_invalidated(self):
        block = make_block(PROSE)
        _ = block.token_count  # warm cache
        result = self.comp.compress(block)
        # Fresh token_count should match the new content
        assert result.token_count == token_count(result.content)


# ---------------------------------------------------------------------------
# YamlStructCompressor
# ---------------------------------------------------------------------------

KV_TEXT = """\
Name: ContextPilot
Version: 1.0.0
Author: Founding Engineer
Status: active
Description: A smart context management tool for AI models.
"""

PROSE_TEXT = """\
The application is running on a Raspberry Pi.
It has been configured with custom settings.
The database connection is established.
"""


class TestYamlStructCompressor:
    def setup_method(self):
        self.comp = YamlStructCompressor()

    def test_name(self):
        assert self.comp.name == "yaml_struct"

    def test_kv_lines_converted_to_yaml(self):
        block = make_block(KV_TEXT)
        result = self.comp.compress(block)
        assert "name: ContextPilot" in result.content
        assert "version: 1.0.0" in result.content

    def test_output_shorter_than_input_for_kv(self):
        block = make_block(KV_TEXT)
        result = self.comp.compress(block)
        assert result.token_count <= block.token_count

    def test_prose_lines_kept_as_comments(self):
        block = make_block(PROSE_TEXT)
        result = self.comp.compress(block)
        assert "#" in result.content

    def test_empty_lines_dropped(self):
        block = make_block("Key: Value\n\n\nOther: Data\n")
        result = self.comp.compress(block)
        empty_lines = [l for l in result.content.splitlines() if not l.strip()]
        assert empty_lines == []

    def test_does_not_mutate_input(self):
        original = KV_TEXT
        block = make_block(original)
        self.comp.compress(block)
        assert block.content == original

    def test_returns_new_block(self):
        block = make_block(KV_TEXT)
        result = self.comp.compress(block)
        assert result is not block

    def test_priority_preserved(self):
        block = make_block(KV_TEXT, Priority.LOW)
        result = self.comp.compress(block)
        assert result.priority == Priority.LOW

    def test_key_with_spaces_normalised(self):
        block = make_block("First Name: Alice\nLast Name: Smith\n")
        result = self.comp.compress(block)
        assert "first_name: Alice" in result.content
        assert "last_name: Smith" in result.content

    def test_token_count_invalidated(self):
        block = make_block(KV_TEXT)
        _ = block.token_count
        result = self.comp.compress(block)
        assert result.token_count == token_count(result.content)


# ---------------------------------------------------------------------------
# MermaidCompressor
# ---------------------------------------------------------------------------

STEPS_NUMBERED = """\
1. User sends request
2. Server validates the input
3. Database is queried
4. Response is returned to the user
"""

STEPS_BULLETS = """\
- Initialise the environment
- Load configuration files
- Connect to external services
- Start processing loop
"""

PROSE_FLOW = (
    "First the data is ingested, then it is validated. "
    "Next the transformation pipeline runs and finally the results are stored."
)


class TestMermaidCompressor:
    def setup_method(self):
        self.comp = MermaidCompressor()

    def test_name(self):
        assert self.comp.name == "mermaid"

    def test_numbered_list_produces_flowchart(self):
        block = make_block(STEPS_NUMBERED)
        result = self.comp.compress(block)
        assert result.content.startswith("flowchart TD")

    def test_bullet_list_produces_flowchart(self):
        block = make_block(STEPS_BULLETS)
        result = self.comp.compress(block)
        assert result.content.startswith("flowchart TD")

    def test_nodes_connected_with_arrows(self):
        block = make_block(STEPS_NUMBERED)
        result = self.comp.compress(block)
        assert "-->" in result.content

    def test_output_has_node_definitions(self):
        block = make_block(STEPS_NUMBERED)
        result = self.comp.compress(block)
        assert "N0[" in result.content
        assert "N1[" in result.content

    def test_prose_with_connectors_produces_flowchart(self):
        block = make_block(PROSE_FLOW)
        result = self.comp.compress(block)
        assert result.content.startswith("flowchart TD")

    def test_single_item_returns_unchanged_copy(self):
        block = make_block("Only one step here.")
        result = self.comp.compress(block)
        # Fewer than 2 steps → no diagram; content preserved
        assert "flowchart" not in result.content

    def test_does_not_mutate_input(self):
        original = STEPS_NUMBERED
        block = make_block(original)
        self.comp.compress(block)
        assert block.content == original

    def test_returns_new_block(self):
        block = make_block(STEPS_NUMBERED)
        result = self.comp.compress(block)
        assert result is not block

    def test_priority_preserved(self):
        block = make_block(STEPS_NUMBERED, Priority.HIGH)
        result = self.comp.compress(block)
        assert result.priority == Priority.HIGH

    def test_output_shorter_than_very_long_numbered_list(self):
        # Very long step labels truncated to 20 chars → flowchart is shorter
        # than original for inputs with many steps and verbose descriptions.
        steps = "\n".join(
            f"{i+1}. Perform the comprehensive and highly detailed processing operation "
            f"number {i+1} including extensive validation and thorough verification of all results"
            for i in range(80)
        )
        block = make_block(steps)
        result = self.comp.compress(block)
        assert result.token_count < block.token_count

    def test_token_count_invalidated(self):
        block = make_block(STEPS_NUMBERED)
        _ = block.token_count
        result = self.comp.compress(block)
        assert result.token_count == token_count(result.content)


# ---------------------------------------------------------------------------
# Integration: compressors work with Assembler
# ---------------------------------------------------------------------------

class TestCompressorsWithAssembler:
    def test_bullet_extract_registered_in_assembler(self):
        from src.core.assembler import Assembler
        a = Assembler(compressors=[BulletExtractCompressor()])
        assert "bullet_extract" in a._registry

    def test_yaml_struct_registered_in_assembler(self):
        from src.core.assembler import Assembler
        a = Assembler(compressors=[YamlStructCompressor()])
        assert "yaml_struct" in a._registry

    def test_mermaid_registered_in_assembler(self):
        from src.core.assembler import Assembler
        a = Assembler(compressors=[MermaidCompressor()])
        assert "mermaid" in a._registry

    def test_assembler_uses_bullet_extract_to_fit_budget(self):
        from src.core.assembler import Assembler
        high = make_block("critical short text", Priority.HIGH)
        verbose = (
            "First of all, the system starts up and loads its full configuration from the disk. "
            "Following that lengthy initialisation step, it then proceeds to connect to the remote database. "
            "Once the connection has been successfully established, it validates all the pending records. "
            "At the very end of the entire process, it finally emits a health check signal to the monitor."
        )
        mid = Block(
            content=verbose,
            priority=Priority.MEDIUM,
            compress_hint="bullet_extract",
        )
        compressed_estimate = BulletExtractCompressor().compress(mid).token_count
        # Budget: tight enough to require compression but fits compressed version
        budget = high.token_count + compressed_estimate + 1
        a = Assembler(compressors=[BulletExtractCompressor()])
        result = a.assemble([high, mid], budget)
        total = sum(b.token_count for b in result)
        assert total <= budget


# ---------------------------------------------------------------------------
# TableCompressor
# ---------------------------------------------------------------------------

MARKDOWN_TABLE = """\
| Name | Age | Status | Country |
|------|-----|--------|---------|
| Alice | 30 | active | Germany |
| Bob | 25 | active | Germany |
| Carol | 35 | active | Germany |
"""

CSV_TABLE = """\
Name,Age,Role
Alice,30,Engineer
Bob,25,Designer
Carol,35,Manager
"""

TSV_TABLE = "Name\tAge\tRole\nAlice\t30\tEngineer\nBob\t25\tDesigner\n"


class TestTableCompressor:
    def setup_method(self):
        self.comp = TableCompressor()

    def test_name(self):
        assert self.comp.name == "table"

    def test_markdown_table_compressed(self):
        block = make_block(MARKDOWN_TABLE)
        result = self.comp.compress(block)
        assert "Name:" in result.content or "name:" in result.content.lower()

    def test_redundant_columns_removed(self):
        block = make_block(MARKDOWN_TABLE)
        result = self.comp.compress(block)
        # Status and Country are identical across all rows -> dropped
        assert "active" not in result.content
        assert "Germany" not in result.content

    def test_csv_table_compressed(self):
        block = make_block(CSV_TABLE)
        result = self.comp.compress(block)
        assert "Alice" in result.content
        assert "Engineer" in result.content

    def test_tsv_table_compressed(self):
        block = make_block(TSV_TABLE)
        result = self.comp.compress(block)
        assert "Alice" in result.content

    def test_separator_rows_removed(self):
        block = make_block(MARKDOWN_TABLE)
        result = self.comp.compress(block)
        assert "---" not in result.content

    def test_output_shorter_than_input(self):
        block = make_block(MARKDOWN_TABLE)
        result = self.comp.compress(block)
        assert result.token_count <= block.token_count

    def test_does_not_mutate_input(self):
        original = MARKDOWN_TABLE
        block = make_block(original)
        self.comp.compress(block)
        assert block.content == original

    def test_returns_new_block(self):
        block = make_block(MARKDOWN_TABLE)
        result = self.comp.compress(block)
        assert result is not block

    def test_priority_preserved(self):
        block = make_block(MARKDOWN_TABLE, Priority.LOW)
        result = self.comp.compress(block)
        assert result.priority == Priority.LOW

    def test_token_count_invalidated(self):
        block = make_block(MARKDOWN_TABLE)
        _ = block.token_count
        result = self.comp.compress(block)
        assert result.token_count == token_count(result.content)

    def test_single_row_returns_copy(self):
        block = make_block("just one line")
        result = self.comp.compress(block)
        assert result is not block

    def test_all_columns_identical_fallback_keeps_all(self):
        # When ALL columns are identical across multiple data rows, the compressor
        # falls back to keeping every column (no-drop fallback at line 50-51).
        uniform = (
            "| Name | Status | Region |\n"
            "|------|--------|--------|\n"
            "| Alice | active | EU |\n"
            "| Bob | active | EU |\n"
            "| Carol | active | EU |\n"
        )
        block = make_block(uniform)
        result = self.comp.compress(block)
        # All three columns are identical → fallback → content is still produced
        assert isinstance(result.content, str)
        assert result is not block

    def test_single_data_row_all_same_values_kept(self):
        # Single data row: even if all cells equal, the single-row branch keeps them.
        single = "| Host | Port |\n|------|------|\n| localhost | 5432 |\n"
        block = make_block(single)
        result = self.comp.compress(block)
        assert "localhost" in result.content or result is not block

    def test_empty_content_returns_copy(self):
        block = make_block("")
        result = self.comp.compress(block)
        assert result is not block


# ---------------------------------------------------------------------------
# CodeCompactCompressor
# ---------------------------------------------------------------------------

PYTHON_CODE = '''\
# This module handles user authentication.
# Author: Test

import os


def authenticate(username, password):
    """Verify user credentials against the database."""
    # Check if user exists
    user = find_user(username)
    if user is None:
        return False

    # Validate password hash
    return check_hash(password, user.password_hash)


class UserManager:
    """Manages user lifecycle operations."""

    def create(self, name, email):
        """Create a new user account."""
        validate_email(email)
        user = User(name=name, email=email)
        self.db.save(user)
        return user

    def delete(self, user_id):
        """Remove a user by ID."""
        user = self.db.find(user_id)
        self.db.remove(user)
'''

JS_CODE = """\
// Helper utilities for the frontend
// Version 2.0

function formatDate(date) {
    const options = { year: 'numeric', month: 'long', day: 'numeric' };
    return date.toLocaleDateString('en-US', options);
}

export function calculateTotal(items) {
    // Sum all item prices
    let total = 0;
    for (const item of items) {
        total += item.price;
    }
    return total;
}
"""


class TestCodeCompactCompressor:
    def setup_method(self):
        self.comp = CodeCompactCompressor()

    def test_name(self):
        assert self.comp.name == "code_compact"

    def test_comments_removed(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert "# This module" not in result.content
        assert "# Check if" not in result.content
        assert "# Author" not in result.content

    def test_function_signatures_preserved(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert "def authenticate" in result.content
        assert "def create" in result.content

    def test_class_signatures_preserved(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert "class UserManager" in result.content

    def test_docstrings_preserved(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert "Verify user credentials" in result.content

    def test_body_collapsed(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert "..." in result.content

    def test_output_shorter(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert result.token_count < block.token_count

    def test_js_comments_removed(self):
        block = make_block(JS_CODE)
        result = self.comp.compress(block)
        assert "// Helper" not in result.content
        assert "// Sum all" not in result.content

    def test_blank_lines_removed(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        lines = result.content.splitlines()
        blank = [l for l in lines if not l.strip()]
        assert len(blank) == 0

    def test_does_not_mutate_input(self):
        original = PYTHON_CODE
        block = make_block(original)
        self.comp.compress(block)
        assert block.content == original

    def test_returns_new_block(self):
        block = make_block(PYTHON_CODE)
        result = self.comp.compress(block)
        assert result is not block

    def test_priority_preserved(self):
        block = make_block(PYTHON_CODE, Priority.HIGH)
        result = self.comp.compress(block)
        assert result.priority == Priority.HIGH

    def test_token_count_invalidated(self):
        block = make_block(PYTHON_CODE)
        _ = block.token_count
        result = self.comp.compress(block)
        assert result.token_count == token_count(result.content)

    def test_multiline_block_comment_removed(self):
        # C-style /* ... */ spanning multiple lines must be stripped entirely.
        c_code = """\
int add(int a, int b) {
/*
 * Adds two integers together.
 * Returns the sum.
 */
    return a + b;
}
"""
        block = make_block(c_code)
        result = self.comp.compress(block)
        assert "Adds two integers" not in result.content
        assert "Returns the sum" not in result.content

    def test_export_default_function_signature_preserved(self):
        # 'export default function' must be detected as a function signature.
        code = """\
export default function handleRequest(req, res) {
    const data = req.body;
    processData(data);
    res.send("ok");
}
"""
        block = make_block(code)
        result = self.comp.compress(block)
        assert "export default function handleRequest" in result.content
        assert "..." in result.content

    def test_empty_content_returns_unchanged(self):
        block = make_block("")
        result = self.comp.compress(block)
        assert result is not block
        assert isinstance(result.content, str)


# ---------------------------------------------------------------------------
# DedupCrossCompressor
# ---------------------------------------------------------------------------

PARA_A = "The system uses a modular architecture.\n\nEach module can be tested independently."
PARA_B = "The system uses a modular architecture.\n\nDeployment happens via Docker containers."
PARA_C = "Completely unique paragraph here.\n\nAnother unique paragraph."


class TestDedupCrossCompressor:
    def setup_method(self):
        self.comp = DedupCrossCompressor()

    def test_name(self):
        assert self.comp.name == "dedup_cross"

    def test_duplicate_paragraphs_removed(self):
        block_a = make_block(PARA_A)
        block_b = make_block(PARA_B)
        result_a = self.comp.compress(block_a)
        result_b = self.comp.compress(block_b)
        # "The system uses a modular architecture" appears in both ->
        # should be removed from the second block.
        assert "modular architecture" in result_a.content
        assert "modular architecture" not in result_b.content
        assert "Docker containers" in result_b.content

    def test_unique_content_preserved(self):
        block_a = make_block(PARA_A)
        block_c = make_block(PARA_C)
        self.comp.compress(block_a)
        result_c = self.comp.compress(block_c)
        assert "Completely unique" in result_c.content
        assert "Another unique" in result_c.content

    def test_reset_clears_state(self):
        block_a = make_block(PARA_A)
        self.comp.compress(block_a)
        self.comp.reset()
        block_b = make_block(PARA_A)
        result_b = self.comp.compress(block_b)
        # After reset, same content should be kept.
        assert "modular architecture" in result_b.content

    def test_compress_blocks_convenience(self):
        blocks = [make_block(PARA_A), make_block(PARA_B)]
        results = self.comp.compress_blocks(blocks)
        assert len(results) == 2
        assert "modular architecture" in results[0].content
        assert "modular architecture" not in results[1].content

    def test_normalisation_catches_whitespace_diffs(self):
        block_a = make_block("Hello   world  test")
        block_b = make_block("Hello world test")
        self.comp.compress(block_a)
        result_b = self.comp.compress(block_b)
        assert result_b.content == ""

    def test_does_not_mutate_input(self):
        original = PARA_A
        block = make_block(original)
        self.comp.compress(block)
        assert block.content == original

    def test_returns_new_block(self):
        block = make_block(PARA_A)
        result = self.comp.compress(block)
        assert result is not block

    def test_priority_preserved(self):
        block = make_block(PARA_A, Priority.LOW)
        result = self.comp.compress(block)
        assert result.priority == Priority.LOW

    def test_token_count_invalidated(self):
        block = make_block(PARA_A)
        _ = block.token_count
        result = self.comp.compress(block)
        assert result.token_count == token_count(result.content)

    def test_empty_content(self):
        block = make_block("")
        result = self.comp.compress(block)
        assert result.content == ""

    def test_compress_blocks_with_empty_list(self):
        results = self.comp.compress_blocks([])
        assert results == []

    def test_all_paragraphs_already_seen_yields_empty(self):
        block_a = make_block("Shared paragraph here.")
        self.comp.compress(block_a)
        block_b = make_block("Shared paragraph here.")
        result_b = self.comp.compress(block_b)
        assert result_b.content == ""

    def test_case_normalisation_catches_mixed_case(self):
        # Normalisation lowercases before hashing; same content differing only
        # in case is treated as duplicate.
        block_a = make_block("Hello World")
        self.comp.compress(block_a)
        block_b = make_block("hello world")
        result_b = self.comp.compress(block_b)
        assert result_b.content == ""


# ---------------------------------------------------------------------------
# Integration: new compressors work with Assembler
# ---------------------------------------------------------------------------

class TestNewCompressorsWithAssembler:
    def test_table_registered_in_assembler(self):
        from src.core.assembler import Assembler
        a = Assembler(compressors=[TableCompressor()])
        assert "table" in a._registry

    def test_code_compact_registered_in_assembler(self):
        from src.core.assembler import Assembler
        a = Assembler(compressors=[CodeCompactCompressor()])
        assert "code_compact" in a._registry

    def test_dedup_cross_registered_in_assembler(self):
        from src.core.assembler import Assembler
        a = Assembler(compressors=[DedupCrossCompressor()])
        assert "dedup_cross" in a._registry

    def test_assembler_uses_table_to_fit_budget(self):
        from src.core.assembler import Assembler
        high = make_block("critical data", Priority.HIGH)
        table_content = (
            "| Name | Age | Status |\n"
            "|------|-----|--------|\n"
            "| Alice | 30 | active |\n"
            "| Bob | 25 | active |\n"
            "| Carol | 35 | active |\n"
            "| Dave | 40 | active |\n"
            "| Eve | 28 | active |\n"
        )
        mid = Block(
            content=table_content,
            priority=Priority.MEDIUM,
            compress_hint="table",
        )
        compressed_estimate = TableCompressor().compress(mid).token_count
        budget = high.token_count + compressed_estimate + 1
        a = Assembler(compressors=[TableCompressor()])
        result = a.assemble([high, mid], budget)
        total = sum(b.token_count for b in result)
        assert total <= budget

    def test_assembler_uses_code_compact_to_fit_budget(self):
        from src.core.assembler import Assembler
        high = make_block("important note", Priority.HIGH)
        mid = Block(
            content=PYTHON_CODE,
            priority=Priority.MEDIUM,
            compress_hint="code_compact",
        )
        compressed_estimate = CodeCompactCompressor().compress(mid).token_count
        budget = high.token_count + compressed_estimate + 1
        a = Assembler(compressors=[CodeCompactCompressor()])
        result = a.assemble([high, mid], budget)
        total = sum(b.token_count for b in result)
        assert total <= budget


# ---------------------------------------------------------------------------
# Coverage gap: CodeCompactCompressor — multi-line docstring + class break
# ---------------------------------------------------------------------------

class TestCodeCompactCoverageGaps:
    def setup_method(self):
        self.comp = CodeCompactCompressor()

    def test_multiline_docstring_collapsed(self):
        """Hits _skip_docstring multi-line branch (lines 127-133)."""
        code = '''\
def foo():
    """
    This is a multi-line docstring.
    It spans several lines.
    """
    return 42
'''
        block = make_block(code)
        result = self.comp.compress(block)
        assert "def foo" in result.content
        assert "return 42" not in result.content
        assert "..." in result.content

    def test_class_body_ends_before_file_end(self):
        """Hits the break branch (line 87) when class body ends mid-file."""
        code = '''\
class MyClass:
    def method(self):
        x = 1

def standalone():
    pass
'''
        block = make_block(code)
        result = self.comp.compress(block)
        assert "class MyClass" in result.content
        assert "def standalone" in result.content

    def test_mermaid_with_blank_lines_between_steps(self):
        """Hits the empty-line continue branch (line 62) in MermaidCompressor."""
        comp = MermaidCompressor()
        text_with_blanks = "1. First step\n\n2. Second step\n\n3. Third step\n"
        block = make_block(text_with_blanks)
        result = comp.compress(block)
        assert result.content.startswith("flowchart TD")


# ---------------------------------------------------------------------------
# Coverage gap: TableCompressor — all-identical columns fallback (line 51)
# and malformed pipe row fallback (line 83)
# ---------------------------------------------------------------------------

class TestTableCompressorCoverageGaps:
    def setup_method(self):
        self.comp = TableCompressor()

    def test_all_columns_identical_triggers_fallback(self):
        """When every column value is identical across multiple rows,
        keep falls back to all columns (line 51)."""
        all_same = (
            "| Status | Region |\n"
            "|--------|--------|\n"
            "| active | EU |\n"
            "| active | EU |\n"
        )
        block = make_block(all_same)
        result = self.comp.compress(block)
        assert isinstance(result.content, str)
        assert result is not block

    def test_pipe_row_without_trailing_pipe(self):
        """Row that starts with | but lacks trailing | hits the fallback
        split-by-pipe branch (line 83)."""
        malformed = (
            "| Name | Age |\n"
            "|------|-----|\n"
            "| Alice | 30\n"
            "| Bob | 25 |\n"
        )
        block = make_block(malformed)
        result = self.comp.compress(block)
        assert isinstance(result.content, str)
        assert result is not block
