"""Retrieval evaluation metrics."""

from __future__ import annotations

import unicodedata
from math import log2
from typing import Any


class RetrievalScorer:
    def score(
        self,
        hits: list[dict[str, Any]],
        expected_keywords: list[str],
        top_k: int = 20,
        *,
        expected_source_patterns: list[str] | None = None,
        min_distinct_documents: int = 1,
    ) -> dict[str, float]:
        if not expected_keywords:
            return {
                "recall_at_k": 0.0,
                "mrr": 0.0,
                "ndcg": 0.0,
                "source_recall": 0.0,
                "document_diversity": 0.0,
            }

        top_hits = hits[:top_k]
        text_blobs = [self._normalize(f"{hit.get('title', '')} {hit.get('snippet', '')}") for hit in top_hits]
        matched_keywords = 0
        reciprocal_rank = 0.0
        gains: list[float] = []

        for keyword in expected_keywords:
            keyword_lower = self._normalize(keyword)
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
        source_patterns = [self._normalize(value) for value in expected_source_patterns or []]
        titles = [self._normalize(str(hit.get("title", ""))) for hit in top_hits]
        matched_sources = sum(
            any(pattern in title for title in titles)
            for pattern in source_patterns
        )
        source_recall = (
            matched_sources / len(source_patterns)
            if source_patterns
            else 1.0
        )
        distinct_documents = {
            str(hit.get("document_id"))
            for hit in top_hits
            if hit.get("document_id")
        }
        diversity = min(1.0, len(distinct_documents) / max(1, min_distinct_documents))
        return {
            "recall_at_k": matched_keywords / len(expected_keywords),
            "mrr": reciprocal_rank,
            "ndcg": min(1.0, ndcg),
            "source_recall": round(source_recall, 3),
            "document_diversity": round(diversity, 3),
        }

    @staticmethod
    def _normalize(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.casefold())
        return "".join(char for char in decomposed if not unicodedata.combining(char))
