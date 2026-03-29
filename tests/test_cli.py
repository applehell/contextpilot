"""Tests for the CLI interface."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from src.interfaces.cli import cli


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def context_file(tmp_path):
    p = tmp_path / "ctx.json"
    blocks = [
        {"content": "High priority system instructions.", "priority": "high"},
        {"content": "Medium priority background info that can be compressed.", "priority": "medium", "compress_hint": "bullet_extract"},
        {"content": "Low priority noise.", "priority": "low"},
    ]
    p.write_text(json.dumps({"blocks": blocks}))
    return p


class TestAssemble:
    def test_text_output(self, runner, context_file):
        result = runner.invoke(cli, ["assemble", "--budget", "500", "--context", str(context_file)])
        assert result.exit_code == 0
        assert "Assembled" in result.output
        assert "tokens" in result.output

    def test_json_output(self, runner, context_file):
        result = runner.invoke(cli, ["assemble", "--budget", "500", "--context", str(context_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "budget" in data
        assert data["budget"] == 500
        assert "blocks" in data
        assert "used_tokens" in data

    def test_tight_budget_drops_low(self, runner, context_file):
        result = runner.invoke(cli, ["assemble", "--budget", "8", "--context", str(context_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        priorities = [b["priority"] for b in data["blocks"]]
        assert "low" not in priorities

    def test_missing_file(self, runner, tmp_path):
        result = runner.invoke(cli, ["assemble", "--budget", "500", "--context", str(tmp_path / "missing.json")])
        assert result.exit_code != 0

    def test_empty_context(self, runner, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"blocks": []}))
        result = runner.invoke(cli, ["assemble", "--budget", "500", "--context", str(p)])
        assert result.exit_code != 0


class TestBlocksList:
    def test_list_text(self, runner, context_file):
        result = runner.invoke(cli, ["blocks", "list", "--context", str(context_file)])
        assert result.exit_code == 0
        assert "[0]" in result.output
        assert "[1]" in result.output

    def test_list_json(self, runner, context_file):
        result = runner.invoke(cli, ["blocks", "list", "--context", str(context_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 3

    def test_list_empty(self, runner, tmp_path):
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"blocks": []}))
        result = runner.invoke(cli, ["blocks", "list", "--context", str(p)])
        assert result.exit_code == 0
        assert "No blocks" in result.output

    def test_list_missing_file(self, runner, tmp_path):
        p = tmp_path / "missing.json"
        result = runner.invoke(cli, ["blocks", "list", "--context", str(p)])
        assert result.exit_code == 0
        assert "No blocks" in result.output


class TestBlocksAdd:
    def test_add_basic(self, runner, tmp_path):
        p = tmp_path / "ctx.json"
        result = runner.invoke(cli, [
            "blocks", "add", "--context", str(p),
            "--content", "New block content",
            "--priority", "high",
        ])
        assert result.exit_code == 0
        data = json.loads(p.read_text())
        assert len(data["blocks"]) == 1
        assert data["blocks"][0]["content"] == "New block content"
        assert data["blocks"][0]["priority"] == "high"

    def test_add_with_compress_hint(self, runner, tmp_path):
        p = tmp_path / "ctx.json"
        runner.invoke(cli, [
            "blocks", "add", "--context", str(p),
            "--content", "Some text",
            "--compress-hint", "bullet_extract",
        ])
        data = json.loads(p.read_text())
        assert data["blocks"][0]["compress_hint"] == "bullet_extract"

    def test_add_multiple(self, runner, tmp_path):
        p = tmp_path / "ctx.json"
        for i in range(3):
            runner.invoke(cli, [
                "blocks", "add", "--context", str(p),
                "--content", f"Block {i}",
            ])
        data = json.loads(p.read_text())
        assert len(data["blocks"]) == 3


class TestBlocksRemove:
    def test_remove_by_index(self, runner, context_file):
        result = runner.invoke(cli, ["blocks", "remove", "--context", str(context_file), "--index", "0"])
        assert result.exit_code == 0
        data = json.loads(context_file.read_text())
        assert len(data["blocks"]) == 2
        assert data["blocks"][0]["priority"] == "medium"

    def test_remove_out_of_range(self, runner, context_file):
        result = runner.invoke(cli, ["blocks", "remove", "--context", str(context_file), "--index", "99"])
        assert result.exit_code != 0

    def test_remove_last_block(self, runner, tmp_path):
        p = tmp_path / "ctx.json"
        p.write_text(json.dumps({"blocks": [{"content": "only", "priority": "medium"}]}))
        result = runner.invoke(cli, ["blocks", "remove", "--context", str(p), "--index", "0"])
        assert result.exit_code == 0
        data = json.loads(p.read_text())
        assert data["blocks"] == []


# ---------------------------------------------------------------------------
# Helper fixture for DB-backed CLI tests
# ---------------------------------------------------------------------------

@pytest.fixture
def db_runner(tmp_path):
    """CliRunner plus a --db-path pointing to a temp SQLite file."""
    db_path = str(tmp_path / "test.db")
    runner = CliRunner()
    return runner, db_path


# ---------------------------------------------------------------------------
# projects CLI
# ---------------------------------------------------------------------------

class TestProjectsList:
    def test_list_empty(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "list"])
        assert result.exit_code == 0
        assert "No projects" in result.output

    def test_list_json_empty(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "list", "--format", "json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_shows_created_projects(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "Alpha"])
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "Beta"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "list"])
        assert result.exit_code == 0
        assert "Alpha" in result.output
        assert "Beta" in result.output

    def test_list_json_shows_projects(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "MyProj", "--description", "desc"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "list", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["name"] == "MyProj"


class TestProjectsCreate:
    def test_create_basic(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "TestProject"])
        assert result.exit_code == 0
        assert "TestProject" in result.output

    def test_create_with_description(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "P1", "--description", "My description"])
        assert result.exit_code == 0

    def test_create_duplicate_fails(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "Dup"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "Dup"])
        assert result.exit_code != 0


class TestProjectsDelete:
    def test_delete_existing(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "ToDelete"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "delete", "--name", "ToDelete"])
        assert result.exit_code == 0
        assert "ToDelete" in result.output

    def test_delete_nonexistent_fails(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "delete", "--name", "Ghost"])
        assert result.exit_code != 0


class TestProjectsShow:
    def test_show_text(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "ShowMe", "--description", "Details here"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "show", "--name", "ShowMe"])
        assert result.exit_code == 0
        assert "ShowMe" in result.output
        assert "Details here" in result.output

    def test_show_json(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "ShowJSON"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "show", "--name", "ShowJSON", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["meta"]["name"] == "ShowJSON"
        assert "contexts" in data

    def test_show_nonexistent_fails(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "show", "--name", "NoSuch"])
        assert result.exit_code != 0


class TestProjectsAddContext:
    def test_add_context(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "ProjA"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "add-context", "--name", "ProjA", "--context-name", "ctx1"])
        assert result.exit_code == 0
        assert "ctx1" in result.output

    def test_add_context_to_nonexistent_project_fails(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "projects", "add-context", "--name", "NoProj", "--context-name", "ctx"])
        assert result.exit_code != 0

    def test_add_duplicate_context_fails(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "ProjB"])
        runner.invoke(cli, ["--db-path", db, "projects", "add-context", "--name", "ProjB", "--context-name", "same"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "add-context", "--name", "ProjB", "--context-name", "same"])
        assert result.exit_code != 0

    def test_show_reflects_added_context(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "projects", "create", "--name", "ProjC"])
        runner.invoke(cli, ["--db-path", db, "projects", "add-context", "--name", "ProjC", "--context-name", "myctx"])
        result = runner.invoke(cli, ["--db-path", db, "projects", "show", "--name", "ProjC"])
        assert "myctx" in result.output


# ---------------------------------------------------------------------------
# memories CLI
# ---------------------------------------------------------------------------

class TestMemoriesList:
    def test_list_empty(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "memories", "list"])
        assert result.exit_code == 0
        assert "No memories" in result.output

    def test_list_json_empty(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "memories", "list", "--format", "json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_shows_entries(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "k1", "--value", "v1"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "list"])
        assert result.exit_code == 0
        assert "k1" in result.output

    def test_list_with_tags(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "k2", "--value", "v2", "--tags", "foo,bar"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "list"])
        assert "foo" in result.output


class TestMemoriesGetSet:
    def test_set_and_get_text(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "mykey", "--value", "myvalue"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "mykey"])
        assert result.exit_code == 0
        assert "mykey" in result.output
        assert "myvalue" in result.output

    def test_set_and_get_json(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "jkey", "--value", "jval"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "jkey", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["key"] == "jkey"
        assert data["value"] == "jval"

    def test_get_nonexistent_fails(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "nope"])
        assert result.exit_code != 0

    def test_set_updates_existing(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "upd", "--value", "old"])
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "upd", "--value", "new"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "upd"])
        assert "new" in result.output

    def test_set_with_tags(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "tagged", "--value", "val", "--tags", "a,b,c"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "tagged", "--format", "json"])
        data = json.loads(result.output)
        assert sorted(data["tags"]) == ["a", "b", "c"]


class TestMemoriesDelete:
    def test_delete_existing(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "del_me", "--value", "x"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "delete", "--key", "del_me"])
        assert result.exit_code == 0
        assert "del_me" in result.output

    def test_delete_nonexistent_fails(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "memories", "delete", "--key", "ghost"])
        assert result.exit_code != 0


class TestMemoriesSearch:
    def test_search_by_query(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "proj", "--value", "context pilot project notes"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "search", "--query", "pilot"])
        assert result.exit_code == 0
        assert "proj" in result.output

    def test_search_no_results(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "memories", "search", "--query", "zzznomatch"])
        assert result.exit_code == 0
        assert "No results" in result.output

    def test_search_by_tag(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "t1", "--value", "val1", "--tags", "important"])
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "t2", "--value", "val2"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "search", "--tags", "important"])
        assert result.exit_code == 0
        assert "t1" in result.output
        assert "t2" not in result.output

    def test_search_json_output(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "s1", "--value", "searchable content"])
        result = runner.invoke(cli, ["--db-path", db, "memories", "search", "--query", "searchable", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) == 1
        assert data[0]["key"] == "s1"


class TestMemoriesExportImport:
    def test_export_creates_file(self, db_runner, tmp_path):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "e1", "--value", "exportval"])
        out_file = str(tmp_path / "export.json")
        result = runner.invoke(cli, ["--db-path", db, "memories", "export", "--output", out_file])
        assert result.exit_code == 0
        assert Path(out_file).exists()
        envelope = json.loads(Path(out_file).read_text())
        assert "memories" in envelope
        assert any(m["key"] == "e1" for m in envelope["memories"])

    def test_import_merge(self, db_runner, tmp_path):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "existing", "--value", "keep"])
        import_data = json.dumps({"memories": [{"key": "imported", "value": "from file", "tags": [], "metadata": {}}]})
        in_file = tmp_path / "import.json"
        in_file.write_text(import_data)
        result = runner.invoke(cli, ["--db-path", db, "memories", "import", "--input", str(in_file)])
        assert result.exit_code == 0
        assert "1" in result.output
        # existing key preserved after merge
        get = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "existing"])
        assert "keep" in get.output

    def test_import_replace(self, db_runner, tmp_path):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "memories", "set", "--key", "old", "--value", "gone"])
        import_data = json.dumps({"memories": [{"key": "fresh", "value": "new world", "tags": [], "metadata": {}}]})
        in_file = tmp_path / "replace.json"
        in_file.write_text(import_data)
        result = runner.invoke(cli, ["--db-path", db, "memories", "import", "--input", str(in_file), "--replace"])
        assert result.exit_code == 0
        get_old = runner.invoke(cli, ["--db-path", db, "memories", "get", "--key", "old"])
        assert get_old.exit_code != 0


# ---------------------------------------------------------------------------
# usage CLI
# ---------------------------------------------------------------------------

class TestUsageWeights:
    def test_weights_empty_text(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "usage", "weights"])
        assert result.exit_code == 0
        assert "No usage data" in result.output

    def test_weights_empty_json(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "usage", "weights", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data == []

    def test_weights_with_project_filter(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "usage", "weights", "--project", "myproj"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# feedback CLI
# ---------------------------------------------------------------------------

class TestFeedbackAdd:
    def test_add_helpful(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "feedback", "add",
                                     "--assembly-id", "asm-1",
                                     "--block-content", "test block",
                                     "--helpful"])
        assert result.exit_code == 0
        assert "helpful" in result.output

    def test_add_not_helpful(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "feedback", "add",
                                     "--assembly-id", "asm-2",
                                     "--block-content", "bad block",
                                     "--not-helpful"])
        assert result.exit_code == 0
        assert "not helpful" in result.output


class TestFeedbackShow:
    def test_show_empty(self, db_runner):
        runner, db = db_runner
        result = runner.invoke(cli, ["--db-path", db, "feedback", "show",
                                     "--assembly-id", "no-such-asm"])
        assert result.exit_code == 0
        assert "No feedback" in result.output

    def test_show_with_data(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "feedback", "add",
                            "--assembly-id", "asm-show",
                            "--block-content", "block1",
                            "--helpful"])
        result = runner.invoke(cli, ["--db-path", db, "feedback", "show",
                                     "--assembly-id", "asm-show"])
        assert result.exit_code == 0
        assert "helpful" in result.output

    def test_show_json(self, db_runner):
        runner, db = db_runner
        runner.invoke(cli, ["--db-path", db, "feedback", "add",
                            "--assembly-id", "asm-j",
                            "--block-content", "jblock",
                            "--helpful"])
        result = runner.invoke(cli, ["--db-path", db, "feedback", "show",
                                     "--assembly-id", "asm-j", "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data) >= 1
        assert data[0]["helpful"] is True
