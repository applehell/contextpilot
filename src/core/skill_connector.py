"""Skill Connector — abstract interface for external skills that inject blocks into context."""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .block import Block, Priority

if TYPE_CHECKING:
    from ..storage.usage import SkillProfile, UsageStore


@dataclass
class SkillConfig:
    skill_name: str
    enabled: bool = True
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"skill_name": self.skill_name, "enabled": self.enabled, "params": self.params}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> SkillConfig:
        return cls(
            skill_name=d["skill_name"],
            enabled=d.get("enabled", True),
            params=d.get("params", {}),
        )


class BaseSkill(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill identifier."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this skill provides."""
        ...

    @property
    def context_hints(self) -> List[str]:
        """Keywords/tags describing what context this skill needs.

        The SkillAssembler uses these to score block relevance.
        Return empty list for 'accepts everything' (neutral scoring).
        """
        return []

    @abstractmethod
    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        """Produce blocks to inject into the context. Must not raise on failure — return empty list instead."""
        ...

    def receive_context(self, blocks: List[Block]) -> None:
        """Called by SkillAssembler to inject skill-specific context before generate_blocks.

        Override this to use the injected context for smarter block generation.
        Default: no-op.
        """
        pass

    def propose_memory_changes(self, config: SkillConfig) -> List[Dict[str, Any]]:
        """Propose memory changes after block generation.

        Return a list of dicts with keys: key, value, tags.
        The GUI will show these as diffs for user approval.
        Default: no changes proposed.
        """
        return []


class SkillConnector:
    """Registry and executor for skills. Manages per-project skill configurations."""

    def __init__(self, skills: Optional[List[BaseSkill]] = None) -> None:
        self._registry: Dict[str, BaseSkill] = {}
        for s in skills or []:
            self._registry[s.name] = s

    def register(self, skill: BaseSkill) -> None:
        self._registry[skill.name] = skill

    def unregister(self, name: str) -> None:
        self._registry.pop(name, None)

    @property
    def available_skills(self) -> List[BaseSkill]:
        return list(self._registry.values())

    def get_skill(self, name: str) -> Optional[BaseSkill]:
        return self._registry.get(name)

    def collect_blocks(self, configs: List[SkillConfig]) -> List[Block]:
        """Run all enabled skills and collect their blocks."""
        blocks: List[Block] = []
        for cfg in configs:
            if not cfg.enabled:
                continue
            skill = self._registry.get(cfg.skill_name)
            if skill is None:
                continue
            blocks.extend(skill.generate_blocks(cfg))
        return blocks

    def collect_blocks_adapted(
        self,
        configs: List[SkillConfig],
        model_id: str,
        usage_store: UsageStore,
    ) -> List[Block]:
        """Run skills with priority adaptation based on historical skill profiles."""
        blocks: List[Block] = []
        for cfg in configs:
            if not cfg.enabled:
                continue
            skill = self._registry.get(cfg.skill_name)
            if skill is None:
                continue

            generated = skill.generate_blocks(cfg)

            profile = usage_store.get_skill_profile(cfg.skill_name, model_id)
            if profile is not None:
                try:
                    adapted_priority = Priority(profile.preferred_priority)
                except ValueError:
                    adapted_priority = None

                for b in generated:
                    if adapted_priority and b.priority == Priority.MEDIUM:
                        b.priority = adapted_priority

            blocks.extend(generated)
        return blocks


class GitStatusSkill(BaseSkill):
    """Example skill: injects the current git status as a LOW-priority block."""

    @property
    def name(self) -> str:
        return "git_status"

    @property
    def description(self) -> str:
        return "Injects current git status (modified/untracked files) as a context block."

    @property
    def context_hints(self) -> List[str]:
        return ["git", "version control", "modified files", "untracked", "commit", "branch"]

    def generate_blocks(self, config: SkillConfig) -> List[Block]:
        cwd = config.params.get("cwd")
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=5,
                cwd=cwd,
            )
            output = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return []

        if not output:
            return []

        priority_str = config.params.get("priority", "low")
        try:
            priority = Priority(priority_str)
        except ValueError:
            priority = Priority.LOW

        return [Block(
            content=f"## Git Status\n\n```\n{output}\n```",
            priority=priority,
            compress_hint=config.params.get("compress_hint"),
        )]
