"""Skill Connectivity Graph — maps which skills produce which blocks and their dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .block import Block
from .skill_connector import BaseSkill, SkillConfig, SkillConnector


@dataclass
class SkillNode:
    """A skill in the connectivity graph."""
    skill_name: str
    description: str
    block_count: int = 0
    total_tokens: int = 0
    block_hashes: List[str] = field(default_factory=list)


@dataclass
class BlockNode:
    """A block in the connectivity graph."""
    block_hash: str
    content_preview: str
    token_count: int
    priority: str
    source_skill: Optional[str] = None


@dataclass
class Edge:
    """A directed edge from skill to block."""
    source_skill: str
    target_block_hash: str


@dataclass
class SkillGraph:
    """Dependency graph of skills and the blocks they produce."""
    skill_nodes: Dict[str, SkillNode] = field(default_factory=dict)
    block_nodes: Dict[str, BlockNode] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)

    @property
    def skill_count(self) -> int:
        return len(self.skill_nodes)

    @property
    def block_count(self) -> int:
        return len(self.block_nodes)

    def blocks_for_skill(self, skill_name: str) -> List[BlockNode]:
        return [
            self.block_nodes[e.target_block_hash]
            for e in self.edges
            if e.source_skill == skill_name and e.target_block_hash in self.block_nodes
        ]

    def skill_for_block(self, block_hash: str) -> Optional[str]:
        for e in self.edges:
            if e.target_block_hash == block_hash:
                return e.source_skill
        return None

    def token_budget_by_skill(self) -> Dict[str, int]:
        return {name: node.total_tokens for name, node in self.skill_nodes.items()}

    def skill_overlap(self) -> Dict[str, Set[str]]:
        """Find skills that produce blocks with overlapping token content."""
        from .clustering import _tokenize_to_set, jaccard_similarity

        skill_tokens: Dict[str, Set[int]] = {}
        for name, node in self.skill_nodes.items():
            combined: Set[int] = set()
            for bh in node.block_hashes:
                bn = self.block_nodes.get(bh)
                if bn:
                    combined.update(_tokenize_to_set(bn.content_preview))
            skill_tokens[name] = combined

        overlaps: Dict[str, Set[str]] = {name: set() for name in self.skill_nodes}
        names = list(self.skill_nodes.keys())
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                sim = jaccard_similarity(skill_tokens[names[i]], skill_tokens[names[j]])
                if sim > 0.1:
                    overlaps[names[i]].add(names[j])
                    overlaps[names[j]].add(names[i])
        return overlaps


def build_skill_graph(
    connector: SkillConnector,
    configs: List[SkillConfig],
) -> SkillGraph:
    from ..storage.usage import block_hash

    graph = SkillGraph()

    for cfg in configs:
        if not cfg.enabled:
            continue
        skill = connector.get_skill(cfg.skill_name)
        if skill is None:
            continue

        blocks = skill.generate_blocks(cfg)

        sn = SkillNode(
            skill_name=skill.name,
            description=skill.description,
            block_count=len(blocks),
            total_tokens=sum(b.token_count for b in blocks),
        )

        for b in blocks:
            bh = block_hash(b.content)
            sn.block_hashes.append(bh)

            graph.block_nodes[bh] = BlockNode(
                block_hash=bh,
                content_preview=b.content[:200],
                token_count=b.token_count,
                priority=b.priority.value,
                source_skill=skill.name,
            )

            graph.edges.append(Edge(source_skill=skill.name, target_block_hash=bh))

        graph.skill_nodes[skill.name] = sn

    return graph
