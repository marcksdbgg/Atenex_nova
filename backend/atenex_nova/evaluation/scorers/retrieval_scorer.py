"""Retrieval evaluation metrics."""

from __future__ import annotations

from math import log2
from typing import Any


class RetrievalScorer:
    def score(self, hits: list[dict[str, Any]], expected_keywords: list[str], top_k: int = 5) -> dict[str, float]:
        if not expected_keywords:
            return {"recall_at_k": 0.0, "mrr": 0.0, "ndcg": 0.0}

        top_hits = hits[:top_k]
        text_blobs = [f"{hit.get('title', '')} {hit.get('snippet', '')}".lower() for hit in top_hits]
        matched_keywords = 0
        reciprocal_rank = 0.0
        gains: list[float] = []

        for keyword in expected_keywords:
            keyword_lower = keyword.lower()
            rank = next((index + 1 for index, blob in enumerate(text_blobs) if keyword_lower in blob), None)
            if rank is not None:
                matched_keywords += 1
                if reciprocal_rank == 0.0:
                    reciprocal_rank = 1.0 / rank
                gains.append(1.0 / log2(rank + 1))
            else:
                gains.append(0.0)

        ideal_gains = [1.0 / log2(index + 2) for index in range(len(expected_keywords))]
        ndcg = sum(gains) / max(sum(ideal_gains), 1e-9)
        return {
            "recall_at_k": matched_keywords / len(expected_keywords),
            "mrr": reciprocal_rank,
            "ndcg": min(1.0, ndcg),
        }
