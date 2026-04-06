"""Policies for query routing and classification."""

from __future__ import annotations

from dataclasses import dataclass
import re

from atenex_nova.domain.value_objects.identifiers import QueryIntent, QueryMode


TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)


@dataclass(frozen=True)
class QueryFeatures:
    text: str
    normalized_text: str
    language: str
    has_exact_tokens: bool
    has_comparison: bool
    has_contradiction: bool
    has_global_terms: bool
    has_visual_terms: bool
    multi_clause: bool


class QueryRoutingPolicy:
    """Heuristic router that selects the best retrieval mode."""

    exact_markers = {"id", "uuid", "code", "código", "fecha", "date", "reference"}
    comparison_markers = {"vs", "versus", "compare", "comparison", "difference", "diferencia", "mejor"}
    contradiction_markers = {"but", "however", "although", "sin embargo", "contradict", "contra"}
    global_markers = {"overall", "summary", "resumen", "global", "general", "corpus", "visión"}
    visual_markers = {"table", "tabla", "figure", "figura", "chart", "layout", "page", "página"}

    def extract_features(self, text: str) -> QueryFeatures:
        normalized = self.normalize(text)
        tokens = set(TOKEN_RE.findall(normalized))
        has_exact_tokens = any(len(token) >= 8 and any(char.isdigit() for char in token) for token in tokens)
        has_comparison = any(marker in normalized for marker in self.comparison_markers)
        has_contradiction = any(marker in normalized for marker in self.contradiction_markers)
        has_global_terms = any(marker in normalized for marker in self.global_markers)
        has_visual_terms = any(marker in normalized for marker in self.visual_markers)
        multi_clause = normalized.count(" and ") + normalized.count(",") >= 1 or normalized.count("?") > 0
        return QueryFeatures(
            text=text,
            normalized_text=normalized,
            language=self.detect_language(text),
            has_exact_tokens=has_exact_tokens,
            has_comparison=has_comparison,
            has_contradiction=has_contradiction,
            has_global_terms=has_global_terms,
            has_visual_terms=has_visual_terms,
            multi_clause=multi_clause,
        )

    def choose_mode(self, features: QueryFeatures) -> QueryMode:
        if features.has_visual_terms:
            return QueryMode.VISUAL
        if features.has_global_terms:
            return QueryMode.GLOBAL
        if features.has_contradiction:
            return QueryMode.ARGUMENTATIVE
        if features.has_exact_tokens:
            return QueryMode.EXACT
        if features.has_comparison or features.multi_clause:
            return QueryMode.MULTI_HOP
        return QueryMode.FACTUAL_LOCAL

    def classify_intent(self, features: QueryFeatures) -> QueryIntent:
        if features.has_visual_terms:
            return QueryIntent.VISUAL
        if features.has_global_terms:
            return QueryIntent.GLOBAL
        if features.has_contradiction:
            return QueryIntent.ARGUMENTATIVE
        if features.has_comparison:
            return QueryIntent.COMPARATIVE
        if features.has_exact_tokens:
            return QueryIntent.EXACT
        return QueryIntent.FACTUAL

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(text.strip().lower().split())

    @staticmethod
    def detect_language(text: str) -> str:
        lower = text.lower()
        spanish_markers = {"qué", "como", "cuál", "dónde", "resumen", "pregunta", "tabla", "documento"}
        if any(marker in lower for marker in spanish_markers):
            return "es"
        return "en"