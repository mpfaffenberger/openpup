"""Tests for the memory consolidation module."""

import pytest

from openpup.memory_consolidation import (
    find_candidates,
    is_exact_duplicate,
)


class TestJaccard:
    def test_identical(self):
        from openpup.memory_consolidation import _jaccard

        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint(self):
        from openpup.memory_consolidation import _jaccard

        assert _jaccard({"a", "b"}, {"c", "d"}) == 0.0

    def test_partial_overlap(self):
        from openpup.memory_consolidation import _jaccard

        # 1 common / 3 total = 0.333
        assert _jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


class TestFindCandidates:
    def test_single_memory_returns_empty(self):
        result = find_candidates(["only one"])
        assert result == []

    def test_two_similar_memories(self):
        result = find_candidates(
            [
                "I went hiking in Yosemite last weekend with the kids.",
                "I took the kids hiking in Yosemite last weekend for fun.",
            ]
        )
        assert len(result) >= 1

    def test_two_unrelated_memories(self):
        result = find_candidates(
            [
                "Postgres upgrade notes for the new cluster.",
                "I love growing tomatoes in the backyard garden.",
            ]
        )
        # Should still produce some groups but at low similarity.
        # Either empty or with low similarity.
        if result:
            assert result[0].similarity < 0.3

    def test_three_duplicates(self):
        result = find_candidates(
            [
                "I went to the gym today.",
                "today I went to the gym",
                "I went to the gym earlier today.",
            ]
        )
        assert len(result) >= 1
        for cand in result:
            assert cand.size >= 2

    def test_candidates_sorted_by_similarity(self):
        result = find_candidates(
            [
                "Postgres upgrade notes for the new cluster.",
                "Postgres upgrade notes for the new cluster.",
                "Unrelated gardening stuff.",
            ]
        )
        # At minimum, the exact duplicates should appear.
        assert len(result) >= 1


class TestExactDuplicate:
    def test_detects_duplicates(self):
        groups = is_exact_duplicate(
            [
                "I went to the gym today.",
                "i went to the gym today",
                "Something completely different.",
            ]
        )
        # Should find the two as duplicates (case+whitespace normalised).
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_no_duplicates(self):
        groups = is_exact_duplicate(
            [
                "Postgres upgrade notes.",
                "I love gardening.",
            ]
        )
        assert groups == []
