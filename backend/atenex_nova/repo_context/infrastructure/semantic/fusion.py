"""Deterministic result fusion for optional hybrid retrieval."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Sequence
from typing import TypeVar

Key = TypeVar("Key", bound=Hashable)


def reciprocal_rank_fusion(  # noqa: UP047 - Python 3.11 remains supported.
    ranked_lists: Sequence[Sequence[Key]],
    *,
    rank_constant: int = 60,
    weights: Sequence[float] | None = None,
) -> list[tuple[Key, float]]:
    """Fuse complementary rankings with stable tie-breaking."""

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    effective_weights = tuple(weights or (1.0,) * len(ranked_lists))
    if len(effective_weights) != len(ranked_lists):
        raise ValueError("weights must match ranked_lists")

    scores: dict[Key, float] = defaultdict(float)
    first_seen: dict[Key, tuple[int, int]] = {}
    for list_index, (ranking, weight) in enumerate(
        zip(ranked_lists, effective_weights, strict=True)
    ):
        for rank, key in enumerate(ranking, start=1):
            scores[key] += float(weight) / (rank_constant + rank)
            first_seen.setdefault(key, (list_index, rank))

    return sorted(
        scores.items(),
        key=lambda item: (-item[1], first_seen[item[0]], str(item[0])),
    )
