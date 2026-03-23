"""Tests for the Clustering module."""
from __future__ import annotations

import pytest
from src.core.block import Block, Priority
from src.core.clustering import (
    BlockCluster,
    BlockClusterer,
    ClusteringResult,
    compute_similarity_matrix,
    jaccard_similarity,
)


class TestJaccardSimilarity:
    def test_identical_sets(self):
        assert jaccard_similarity({1, 2, 3}, {1, 2, 3}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard_similarity({1, 2}, {3, 4}) == 0.0

    def test_partial_overlap(self):
        sim = jaccard_similarity({1, 2, 3}, {2, 3, 4})
        assert sim == pytest.approx(0.5)

    def test_empty_sets(self):
        assert jaccard_similarity(set(), set()) == 1.0

    def test_one_empty(self):
        assert jaccard_similarity({1, 2}, set()) == 0.0
        assert jaccard_similarity(set(), {1, 2}) == 0.0


class TestSimilarityMatrix:
    def test_diagonal_is_one(self):
        blocks = [Block("hello world"), Block("goodbye moon")]
        matrix = compute_similarity_matrix(blocks)
        assert matrix[0][0] == 1.0
        assert matrix[1][1] == 1.0

    def test_symmetric(self):
        blocks = [Block("hello world"), Block("hello earth"), Block("goodbye moon")]
        matrix = compute_similarity_matrix(blocks)
        for i in range(3):
            for j in range(3):
                assert matrix[i][j] == pytest.approx(matrix[j][i])

    def test_similar_content_higher(self):
        blocks = [
            Block("Python is a programming language used for web development"),
            Block("Python is a programming language used for data science"),
            Block("The quick brown fox jumps over the lazy dog"),
        ]
        matrix = compute_similarity_matrix(blocks)
        assert matrix[0][1] > matrix[0][2]


class TestBlockCluster:
    def test_total_tokens(self):
        b1 = Block("hello")
        b2 = Block("world")
        c = BlockCluster(cluster_id=0, label="test", blocks=[b1, b2], block_indices=[0, 1])
        assert c.total_tokens == b1.token_count + b2.token_count

    def test_size(self):
        c = BlockCluster(cluster_id=0, label="test", blocks=[Block("a")], block_indices=[0])
        assert c.size == 1


class TestBlockClusterer:
    def test_empty_input(self):
        clusterer = BlockClusterer()
        result = clusterer.cluster([])
        assert result.cluster_count == 0

    def test_single_block(self):
        clusterer = BlockClusterer()
        result = clusterer.cluster([Block("hello world")])
        assert result.cluster_count == 1
        assert result.clusters[0].size == 1

    def test_identical_blocks_same_cluster(self):
        clusterer = BlockClusterer(similarity_threshold=0.1)
        blocks = [Block("hello world"), Block("hello world")]
        result = clusterer.cluster(blocks)
        assert result.cluster_count == 1
        assert result.clusters[0].size == 2

    def test_different_blocks_separate_clusters(self):
        clusterer = BlockClusterer(similarity_threshold=0.5)
        blocks = [
            Block("Python is a programming language for web development and data science"),
            Block("The Eiffel Tower is a wrought-iron lattice tower in Paris France"),
        ]
        result = clusterer.cluster(blocks)
        assert result.cluster_count == 2

    def test_similar_blocks_merge(self):
        clusterer = BlockClusterer(similarity_threshold=0.1)
        blocks = [
            Block("Python programming language syntax variables functions classes"),
            Block("Python programming language modules packages imports decorators"),
            Block("Cooking recipe for chocolate cake with flour sugar eggs butter"),
        ]
        result = clusterer.cluster(blocks)
        assert result.cluster_count <= 2

    def test_get_cluster_for_block(self):
        clusterer = BlockClusterer()
        blocks = [Block("hello"), Block("world")]
        result = clusterer.cluster(blocks)
        for i in range(len(blocks)):
            c = result.get_cluster_for_block(i)
            assert c is not None

    def test_get_cluster_for_nonexistent(self):
        result = ClusteringResult()
        assert result.get_cluster_for_block(99) is None

    def test_token_distribution(self):
        clusterer = BlockClusterer()
        blocks = [Block("hello world"), Block("foo bar")]
        result = clusterer.cluster(blocks)
        dist = result.token_distribution()
        assert sum(dist.values()) == sum(b.token_count for b in blocks)

    def test_high_threshold_no_merges(self):
        clusterer = BlockClusterer(similarity_threshold=0.99)
        blocks = [Block("aaa bbb ccc"), Block("ddd eee fff"), Block("ggg hhh iii")]
        result = clusterer.cluster(blocks)
        assert result.cluster_count == 3

    def test_similarity_matrix_returned(self):
        clusterer = BlockClusterer()
        blocks = [Block("hello"), Block("world")]
        result = clusterer.cluster(blocks)
        assert result.similarity_matrix is not None
        assert len(result.similarity_matrix) == 2
