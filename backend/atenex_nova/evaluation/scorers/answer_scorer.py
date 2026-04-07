"""Answer quality metrics."""

from __future__ import annotations


class AnswerScorer:
    def score(self, answer_text: str, expected_answer: str, citations_count: int) -> dict[str, float]:
        answer_lower = answer_text.lower()
        expected_lower = expected_answer.lower()
        if not answer_lower.strip():
            return {"relevance": 0.0, "grounding": 0.0, "overall": 0.0}

        expected_tokens = [token for token in expected_lower.split() if token]
        matches = sum(1 for token in expected_tokens if token in answer_lower)
        relevance = matches / max(len(expected_tokens), 1)
        grounding = min(1.0, 0.35 + (min(citations_count, 5) * 0.13))
        overall = round((relevance * 0.6) + (grounding * 0.4), 3)
        return {"relevance": round(relevance, 3), "grounding": round(grounding, 3), "overall": overall}