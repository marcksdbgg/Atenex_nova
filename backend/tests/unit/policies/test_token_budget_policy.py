"""Unit tests for TokenBudgetPolicy."""

from itertools import pairwise

import pytest

from atenex_nova.application.policies.token_budget_policy import (
    DefaultTokenEstimator,
    TokenBudgetPolicy,
)


def test_default_estimator():
    estimator = DefaultTokenEstimator()
    # 20 chars // 4 = 5
    assert estimator.estimate("12345678901234567890") == 5
    # Small string should be at least 1
    assert estimator.estimate("12") == 1
    # Empty string should technically be 1 based on the max(1, ...), but policy handles empty string first
    assert estimator.estimate("") == 1


def test_token_budget_policy_estimation():
    policy = TokenBudgetPolicy()
    assert policy.estimate_tokens("") == 0
    assert policy.estimate_tokens("12345678901234567890") == 5


def test_should_split_max_tokens():
    policy = TokenBudgetPolicy()
    # If adding the new node pushes us over max_tokens, and we have some tokens, split.
    assert policy.should_split(current_tokens=750, next_node_tokens=100, node_type="paragraph", max_tokens=800) is True
    # An oversized first node must be subdivided rather than violating the hard cap.
    assert policy.should_split(current_tokens=0, next_node_tokens=1000, node_type="paragraph", max_tokens=800) is True


def test_should_split_structural_boundary():
    policy = TokenBudgetPolicy()
    # Boundary type, but under minimum tokens, should NOT split
    assert policy.should_split(current_tokens=100, next_node_tokens=50, node_type="heading", min_tokens=400) is False
    # Boundary type, and over minimum tokens, SHOULD split
    assert policy.should_split(current_tokens=450, next_node_tokens=50, node_type="heading", min_tokens=400) is True

    # Non-boundary type, over min but under max, should NOT split
    assert policy.should_split(current_tokens=450, next_node_tokens=50, node_type="paragraph", min_tokens=400, max_tokens=800) is False


def test_complex_boundary_types():
    policy = TokenBudgetPolicy()
    for b_type in ["heading", "table", "caption", "image", "formula", "page_break"]:
        assert policy.should_split(current_tokens=500, next_node_tokens=10, node_type=b_type, min_tokens=400) is True

    for nb_type in ["paragraph", "list_item", "list"]:
        assert policy.should_split(current_tokens=500, next_node_tokens=10, node_type=nb_type, min_tokens=400, max_tokens=800) is False


def test_transformers_token_estimator():
    from atenex_nova.application.policies.token_budget_policy import TransformersTokenEstimator
    # If the tokenizer is not available, it uses the fallback.
    # Otherwise, it uses the fast tokenizer.
    estimator = TransformersTokenEstimator("embeddinggemma")
    tokens = estimator.estimate("12345678901234567890")
    assert tokens > 0


def test_split_text_enforces_hard_cap_and_preserves_ordered_spans() -> None:
    policy = TokenBudgetPolicy()
    text = " ".join(
        f"Sentence {index} contains enough words for a stable semantic boundary."
        for index in range(20)
    )

    segments = policy.split_text(text, max_tokens=40, overlap_tokens=6)

    assert len(segments) > 1
    assert segments[0].char_start == 0
    assert segments[-1].char_end == len(text)
    assert all(segment.text == text[segment.char_start : segment.char_end] for segment in segments)
    assert all(segment.token_count <= 40 for segment in segments)
    for previous, current in pairwise(segments):
        assert previous.char_start < current.char_start
        assert current.char_start <= previous.char_end
        assert current.char_start < previous.char_end  # bounded overlap


def test_split_text_handles_a_single_unbroken_oversized_node() -> None:
    policy = TokenBudgetPolicy()
    text = "x" * 1000

    segments = policy.split_text(text, max_tokens=25, overlap_tokens=5)

    assert len(segments) > 1
    assert all(segment.token_count <= 25 for segment in segments)
    assert all(segment.text == text[segment.char_start : segment.char_end] for segment in segments)
    assert segments[-1].char_end == len(text)


def test_split_text_rejects_overlap_that_cannot_make_progress() -> None:
    policy = TokenBudgetPolicy()

    with pytest.raises(ValueError, match="smaller than max_tokens"):
        policy.split_text("oversized text", max_tokens=10, overlap_tokens=10)
