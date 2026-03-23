"""Tests for src.core.skill_connector — SkillConnector, BaseSkill, and GitStatusSkill."""
from __future__ import annotations

import subprocess
from typing import List
from unittest.mock import patch, MagicMock

import pytest

from src.core.block import Block, Priority
from src.core.skill_connector import (
    BaseSkill,
    GitStatusSkill,
    SkillConfig,
    SkillConnector,
)
from src.storage.db import Database
from src.storage.usage import UsageStore, SkillProfile


class _DummySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A dummy skill for testing."

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        msg = config.params.get("message", "hello")
        return [Block(content=msg, priority=Priority.LOW)]


class _MediumSkill(BaseSkill):
    @property
    def name(self) -> str:
        return "medium_skill"

    @property
    def description(self) -> str:
        return "Returns a MEDIUM-priority block."

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        return [Block(content="medium content", priority=Priority.MEDIUM)]


class _EmptySkill(BaseSkill):
    @property
    def name(self) -> str:
        return "empty"

    @property
    def description(self) -> str:
        return "Returns nothing."

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        return []


class TestSkillConfig:
    def test_roundtrip(self) -> None:
        cfg = SkillConfig(skill_name="git_status", enabled=True, params={"cwd": "/tmp"})
        d = cfg.to_dict()
        cfg2 = SkillConfig.from_dict(d)
        assert cfg2.skill_name == "git_status"
        assert cfg2.enabled is True
        assert cfg2.params == {"cwd": "/tmp"}

    def test_defaults(self) -> None:
        cfg = SkillConfig.from_dict({"skill_name": "x"})
        assert cfg.enabled is True
        assert cfg.params == {}


class TestSkillConnector:
    def test_register_and_list(self) -> None:
        conn = SkillConnector()
        conn.register(_DummySkill())
        assert len(conn.available_skills) == 1
        assert conn.available_skills[0].name == "dummy"

    def test_unregister(self) -> None:
        conn = SkillConnector([_DummySkill()])
        conn.unregister("dummy")
        assert len(conn.available_skills) == 0

    def test_get_skill(self) -> None:
        conn = SkillConnector([_DummySkill()])
        assert conn.get_skill("dummy") is not None
        assert conn.get_skill("missing") is None

    def test_collect_blocks_enabled(self) -> None:
        conn = SkillConnector([_DummySkill()])
        configs = [SkillConfig(skill_name="dummy", params={"message": "test"})]
        blocks = conn.collect_blocks(configs)
        assert len(blocks) == 1
        assert blocks[0].content == "test"

    def test_collect_blocks_disabled(self) -> None:
        conn = SkillConnector([_DummySkill()])
        configs = [SkillConfig(skill_name="dummy", enabled=False)]
        blocks = conn.collect_blocks(configs)
        assert blocks == []

    def test_collect_blocks_missing_skill(self) -> None:
        conn = SkillConnector()
        configs = [SkillConfig(skill_name="nonexistent")]
        blocks = conn.collect_blocks(configs)
        assert blocks == []

    def test_collect_multiple_skills(self) -> None:
        conn = SkillConnector([_DummySkill(), _EmptySkill()])
        configs = [
            SkillConfig(skill_name="dummy"),
            SkillConfig(skill_name="empty"),
        ]
        blocks = conn.collect_blocks(configs)
        assert len(blocks) == 1

    def test_init_with_skills(self) -> None:
        conn = SkillConnector([_DummySkill(), _EmptySkill()])
        assert len(conn.available_skills) == 2


class TestGitStatusSkill:
    def test_name_and_description(self) -> None:
        skill = GitStatusSkill()
        assert skill.name == "git_status"
        assert len(skill.description) > 0

    @patch("src.core.skill_connector.subprocess.run")
    def test_generates_block_from_git_output(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=" M file.py\n?? new.txt\n")
        skill = GitStatusSkill()
        cfg = SkillConfig(skill_name="git_status")
        blocks = skill.generate_blocks(cfg)
        assert len(blocks) == 1
        assert "file.py" in blocks[0].content
        assert blocks[0].priority == Priority.LOW

    @patch("src.core.skill_connector.subprocess.run")
    def test_empty_status_returns_no_blocks(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="")
        skill = GitStatusSkill()
        blocks = skill.generate_blocks(SkillConfig(skill_name="git_status"))
        assert blocks == []

    @patch("src.core.skill_connector.subprocess.run")
    def test_custom_priority(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=" M x.py\n")
        skill = GitStatusSkill()
        cfg = SkillConfig(skill_name="git_status", params={"priority": "high"})
        blocks = skill.generate_blocks(cfg)
        assert blocks[0].priority == Priority.HIGH

    @patch("src.core.skill_connector.subprocess.run")
    def test_invalid_priority_defaults_low(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=" M x.py\n")
        skill = GitStatusSkill()
        cfg = SkillConfig(skill_name="git_status", params={"priority": "invalid"})
        blocks = skill.generate_blocks(cfg)
        assert blocks[0].priority == Priority.LOW

    @patch("src.core.skill_connector.subprocess.run", side_effect=FileNotFoundError)
    def test_git_not_found_returns_empty(self, mock_run: MagicMock) -> None:
        skill = GitStatusSkill()
        blocks = skill.generate_blocks(SkillConfig(skill_name="git_status"))
        assert blocks == []

    @patch("src.core.skill_connector.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5))
    def test_timeout_returns_empty(self, mock_run: MagicMock) -> None:
        skill = GitStatusSkill()
        blocks = skill.generate_blocks(SkillConfig(skill_name="git_status"))
        assert blocks == []

    @patch("src.core.skill_connector.subprocess.run")
    def test_passes_cwd(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=" M f.py\n")
        skill = GitStatusSkill()
        cfg = SkillConfig(skill_name="git_status", params={"cwd": "/my/repo"})
        skill.generate_blocks(cfg)
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["cwd"] == "/my/repo"


class TestCollectBlocksAdapted:
    @pytest.fixture()
    def usage_store(self) -> UsageStore:
        db = Database(None)
        return UsageStore(db)

    def test_adapts_medium_to_high(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_profile(SkillProfile(
            skill_name="medium_skill", model_id="gpt-4",
            preferred_priority="high",
        ))
        conn = SkillConnector([_MediumSkill()])
        configs = [SkillConfig(skill_name="medium_skill")]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert len(blocks) == 1
        assert blocks[0].priority == Priority.HIGH

    def test_adapts_medium_to_low(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_profile(SkillProfile(
            skill_name="medium_skill", model_id="gpt-4",
            preferred_priority="low",
        ))
        conn = SkillConnector([_MediumSkill()])
        configs = [SkillConfig(skill_name="medium_skill")]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert blocks[0].priority == Priority.LOW

    def test_no_profile_keeps_original(self, usage_store: UsageStore) -> None:
        conn = SkillConnector([_MediumSkill()])
        configs = [SkillConfig(skill_name="medium_skill")]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert blocks[0].priority == Priority.MEDIUM

    def test_invalid_profile_priority_keeps_original(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_profile(SkillProfile(
            skill_name="medium_skill", model_id="gpt-4",
            preferred_priority="invalid_value",
        ))
        conn = SkillConnector([_MediumSkill()])
        configs = [SkillConfig(skill_name="medium_skill")]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert blocks[0].priority == Priority.MEDIUM

    def test_non_medium_blocks_not_adapted(self, usage_store: UsageStore) -> None:
        usage_store.save_skill_profile(SkillProfile(
            skill_name="dummy", model_id="gpt-4",
            preferred_priority="high",
        ))
        conn = SkillConnector([_DummySkill()])
        configs = [SkillConfig(skill_name="dummy")]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert blocks[0].priority == Priority.LOW  # stays LOW, not adapted

    def test_disabled_skill_skipped(self, usage_store: UsageStore) -> None:
        conn = SkillConnector([_MediumSkill()])
        configs = [SkillConfig(skill_name="medium_skill", enabled=False)]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert blocks == []

    def test_missing_skill_skipped(self, usage_store: UsageStore) -> None:
        conn = SkillConnector()
        configs = [SkillConfig(skill_name="nonexistent")]
        blocks = conn.collect_blocks_adapted(configs, "gpt-4", usage_store)
        assert blocks == []
