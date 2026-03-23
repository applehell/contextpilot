"""Clustering — groups blocks by token-level similarity into Context Pilot Classes."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .block import Block
from .token_budget import TokenBudget


@dataclass
class BlockCluster:
    """A cluster of semantically related blocks (a Context Pilot Class)."""
    cluster_id: int
    label: str
    blocks: List[Block] = field(default_factory=list)
    block_indices: List[int] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(b.token_count for b in self.blocks)

    @property
    def size(self) -> int:
        return len(self.blocks)


@dataclass
class ClusteringResult:
    """Result of clustering a set of blocks."""
    clusters: List[BlockCluster] = field(default_factory=list)
    similarity_matrix: Optional[List[List[float]]] = None

    @property
    def cluster_count(self) -> int:
        return len(self.clusters)

    def get_cluster_for_block(self, block_index: int) -> Optional[BlockCluster]:
        for c in self.clusters:
            if block_index in c.block_indices:
                return c
        return None

    def token_distribution(self) -> Dict[str, int]:
        return {c.label: c.total_tokens for c in self.clusters}


def _tokenize_to_set(text: str) -> Set[int]:
    """Convert text to a set of token IDs for Jaccard similarity."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")
    return set(enc.encode(text))


def jaccard_similarity(a: Set[int], b: Set[int]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compute_similarity_matrix(blocks: List[Block]) -> List[List[float]]:
    token_sets = [_tokenize_to_set(b.content) for b in blocks]
    n = len(blocks)
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        matrix[i][i] = 1.0
        for j in range(i + 1, n):
            sim = jaccard_similarity(token_sets[i], token_sets[j])
            matrix[i][j] = sim
            matrix[j][i] = sim
    return matrix


def _find_closest_pair(matrix: List[List[float]], active: Set[int]) -> Tuple[int, int, float]:
    best_sim = -1.0
    best_i, best_j = -1, -1
    active_list = sorted(active)
    for idx_a in range(len(active_list)):
        for idx_b in range(idx_a + 1, len(active_list)):
            i, j = active_list[idx_a], active_list[idx_b]
            if matrix[i][j] > best_sim:
                best_sim = matrix[i][j]
                best_i, best_j = i, j
    return best_i, best_j, best_sim


class BlockClusterer:
    """Agglomerative clustering of blocks by token-level Jaccard similarity."""

    def __init__(self, similarity_threshold: float = 0.15) -> None:
        self.similarity_threshold = similarity_threshold

    def cluster(self, blocks: List[Block]) -> ClusteringResult:
        if not blocks:
            return ClusteringResult()

        n = len(blocks)
        if n == 1:
            c = BlockCluster(cluster_id=0, label=self._make_label(blocks, [0]), blocks=[blocks[0]], block_indices=[0])
            return ClusteringResult(clusters=[c], similarity_matrix=[[1.0]])

        sim_matrix = compute_similarity_matrix(blocks)

        # Each block starts as its own cluster
        clusters: Dict[int, List[int]] = {i: [i] for i in range(n)}
        active = set(range(n))

        # Agglomerative merge using average-linkage
        while len(active) > 1:
            best_i, best_j, best_sim = _find_closest_pair(sim_matrix, active)
            if best_sim < self.similarity_threshold:
                break

            # Merge j into i (average linkage update)
            size_i = len(clusters[best_i])
            size_j = len(clusters[best_j])
            for k in active:
                if k == best_i or k == best_j:
                    continue
                sim_matrix[best_i][k] = (
                    sim_matrix[best_i][k] * size_i + sim_matrix[best_j][k] * size_j
                ) / (size_i + size_j)
                sim_matrix[k][best_i] = sim_matrix[best_i][k]

            clusters[best_i].extend(clusters[best_j])
            del clusters[best_j]
            active.discard(best_j)

        result_clusters = []
        for cid, (rep, indices) in enumerate(sorted(clusters.items())):
            cluster_blocks = [blocks[i] for i in indices]
            label = self._make_label(blocks, indices)
            result_clusters.append(BlockCluster(
                cluster_id=cid,
                label=label,
                blocks=cluster_blocks,
                block_indices=indices,
            ))

        return ClusteringResult(clusters=result_clusters, similarity_matrix=sim_matrix)

    def _make_label(self, blocks: List[Block], indices: List[int]) -> str:
        first = blocks[indices[0]]
        preview = first.content[:50].replace("\n", " ").strip()
        if len(indices) == 1:
            return preview
        return f"{preview} (+{len(indices) - 1})"
