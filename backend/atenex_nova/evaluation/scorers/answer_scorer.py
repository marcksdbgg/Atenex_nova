"""Answer quality metrics."""

from __future__ import annotations


class AnswerScorer:
    def score(
        self,
        answer_text: str,
        expected_answer: str,
        citations_count: int,
        evidence_texts: list[str] | None = None,
    ) -> dict[str, float]:
        answer_lower = answer_text.lower()
        expected_lower = expected_answer.lower()
        if not answer_lower.strip():
            return {"relevance": 0.0, "support_coverage": 0.0, "citation_coverage": 0.0, "grounding": 0.0, "overall": 0.0}

        expected_tokens = [token for token in expected_lower.split() if token]
        matches = sum(1 for token in expected_tokens if token in answer_lower)
        relevance = matches / max(len(expected_tokens), 1)
        answer_tokens = [token for token in answer_lower.split() if token]
        evidence_lower = " ".join(evidence_texts or ()).lower()
        support_matches = sum(1 for token in answer_tokens if token in evidence_lower)
        support_coverage = support_matches / max(len(answer_tokens), 1)
        evidence_count = len(evidence_texts or ())
        citation_coverage = min(1.0, citations_count / max(evidence_count, 1)) if evidence_count else min(1.0, citations_count / 5)
        grounding = min(1.0, 0.2 + (support_coverage * 0.4) + (relevance * 0.25) + (citation_coverage * 0.15))
        overall = round((relevance * 0.45) + (support_coverage * 0.35) + (citation_coverage * 0.2), 3)
        return {
            "relevance": round(relevance, 3),
            "support_coverage": round(support_coverage, 3),
            "citation_coverage": round(citation_coverage, 3),
            "grounding": round(grounding, 3),
            "overall": overall,
        }
