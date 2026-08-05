"""Deterministic, claim-oriented answer quality metrics."""

from __future__ import annotations

import re
import unicodedata

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)
_CITATION_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=(?:[A-ZÁÉÍÓÚÑ¿¡]|\d))")
_STOPWORDS = {
    "and", "are", "como", "con", "de", "del", "el", "en", "es", "for",
    "from", "in", "is", "la", "las", "los", "of", "para", "por", "que",
    "se", "the", "to", "una", "uno", "with", "y",
}


class AnswerScorer:
    """Score coverage and grounding without treating citation count as support."""

    def score(
        self,
        answer_text: str,
        expected_answer: str,
        citations_count: int,
        evidence_texts: list[str] | None = None,
        *,
        required_claims: list[list[str]] | None = None,
        forbidden_phrases: list[str] | None = None,
        min_citations: int = 1,
    ) -> dict[str, float]:
        answer_lower = self._normalize(answer_text).strip()
        if not answer_lower:
            return {
                "relevance": 0.0,
                "claim_coverage": 0.0,
                "support_coverage": 0.0,
                "citation_coverage": 0.0,
                "grounding": 0.0,
                "unsupported_claim_rate": 1.0,
                "forbidden_phrase_rate": 0.0,
                "overall": 0.0,
            }

        expected_tokens = self._tokens(expected_answer)
        answer_tokens = self._tokens(answer_text)
        lexical_relevance = len(expected_tokens & answer_tokens) / max(len(expected_tokens), 1)

        claim_groups = required_claims or []
        claim_group_scores = [
            len(self._tokens(" ".join(group)) & answer_tokens)
            / max(len(self._tokens(" ".join(group))), 1)
            for group in claim_groups
            if group
        ]
        claim_coverage = (
            sum(claim_group_scores) / len(claim_group_scores)
            if claim_group_scores
            else lexical_relevance
        )
        relevance = (
            (claim_coverage * 0.7) + (lexical_relevance * 0.3)
            if claim_group_scores
            else lexical_relevance
        )

        evidence_token_sets = [self._tokens(text) for text in evidence_texts or []]
        material_claims = self._claims(answer_text)
        supported_claims = 0
        cited_claims = 0
        referenced_indices: set[int] = set()
        for claim in material_claims:
            claim_tokens = self._tokens(_CITATION_RE.sub(" ", claim))
            support = max(
                (
                    len(claim_tokens & evidence_tokens) / max(len(claim_tokens), 1)
                    for evidence_tokens in evidence_token_sets
                ),
                default=0.0,
            )
            if support >= 0.18:
                supported_claims += 1
            markers = _CITATION_RE.findall(claim)
            if markers:
                cited_claims += 1
                referenced_indices.update(
                    int(value.strip())
                    for marker in markers
                    for value in marker.split(",")
                )

        material_count = len(material_claims)
        support_coverage = supported_claims / max(material_count, 1)
        marker_binding = min(1.0, citations_count / max(len(referenced_indices), 1))
        citation_coverage = (cited_claims / max(material_count, 1)) * marker_binding
        if citations_count < max(0, min_citations):
            citation_coverage = 0.0

        forbidden = [self._normalize(phrase) for phrase in forbidden_phrases or [] if phrase.strip()]
        forbidden_hits = sum(phrase in answer_lower for phrase in forbidden)
        forbidden_rate = forbidden_hits / max(len(forbidden), 1) if forbidden else 0.0
        unsupported_rate = 1.0 - support_coverage

        grounding = max(
            0.0,
            min(
                1.0,
                (support_coverage * 0.45)
                + (citation_coverage * 0.30)
                + (relevance * 0.25)
                - (forbidden_rate * 0.35),
            ),
        )
        overall = max(
            0.0,
            min(
                1.0,
                (relevance * 0.35)
                + (support_coverage * 0.35)
                + (citation_coverage * 0.20)
                + ((1.0 - forbidden_rate) * 0.10),
            ),
        )
        return {
            "relevance": round(relevance, 3),
            "claim_coverage": round(claim_coverage, 3),
            "support_coverage": round(support_coverage, 3),
            "citation_coverage": round(citation_coverage, 3),
            "grounding": round(grounding, 3),
            "unsupported_claim_rate": round(unsupported_rate, 3),
            "forbidden_phrase_rate": round(forbidden_rate, 3),
            "overall": round(overall, 3),
        }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {
            token
            for token in _TOKEN_RE.findall(AnswerScorer._normalize(text))
            if len(token) > 2 and token not in _STOPWORDS and not token.isdigit()
        }

    @staticmethod
    def _normalize(text: str) -> str:
        decomposed = unicodedata.normalize("NFKD", text.casefold())
        return "".join(char for char in decomposed if not unicodedata.combining(char))

    @classmethod
    def _claims(cls, text: str) -> list[str]:
        claims: list[str] = []
        for raw_line in text.splitlines():
            line = re.sub(r"^\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", raw_line).strip()
            if not line:
                continue
            for segment in _SENTENCE_RE.split(line):
                if len(cls._tokens(_CITATION_RE.sub(" ", segment))) >= 3:
                    claims.append(segment.strip())
        return claims
