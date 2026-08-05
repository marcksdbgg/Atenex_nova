"""Policies for query routing and classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

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
    has_argumentative_terms: bool
    asks_author_stance: bool
    has_global_terms: bool
    has_visual_terms: bool
    multi_clause: bool


class QueryRoutingPolicy:
    """Heuristic router that selects the best retrieval mode."""

    exact_markers: ClassVar[set[str]] = {"id", "uuid", "code", "codigo", "fecha", "date", "reference"}
    comparison_markers: ClassVar[set[str]] = {
        "vs",
        "versus",
        "compare",
        "comparison",
        "difference",
        "diferencia",
        "mejor",
    }
    contradiction_markers: ClassVar[set[str]] = {
        "but",
        "however",
        "although",
        "sin embargo",
        "contradict",
        "contradicts",
        "contradicted",
        "contradiction",
        "contradictions",
        "contradictory",
        "contradice",
        "contradiccion",
        "contradicción",
        "contradicciones",
        "contra",
        "conflict",
    }
    argumentative_markers: ClassVar[set[str]] = {
        "analiza",
        "analice",
        "argumento",
        "argumentos",
        "conclusion",
        "conclusión",
        "critica",
        "critique",
        "evalua",
        "evalúa",
        "evaluate",
        "implica",
        "infiere",
        "infer",
        "objecion",
        "objeción",
        "premisa",
        "por eso",
        "por lo tanto",
        "razona",
        "tiene razon",
        "tiene razón",
    }
    author_stance_markers: ClassVar[set[str]] = {
        "afirma",
        "argumenta",
        "considera",
        "defiende",
        "dice que",
        "dicen que",
        "opinion",
        "opinión",
        "plantea",
        "postura",
        "que decia",
        "que dice",
        "qué decía",
        "qué dice",
        "segun",
        "según",
        "sostiene",
        "tesis",
    }
    global_markers: ClassVar[set[str]] = {
        "overall",
        "summary",
        "resumen",
        "global",
        "general",
        "corpus",
        "vision",
        "panorama",
    }
    visual_markers: ClassVar[set[str]] = {
        "table",
        "tabla",
        "figure",
        "figura",
        "chart",
        "layout",
        "page",
        "pagina",
        "diagram",
        "scan",
    }

    def extract_features(self, text: str) -> QueryFeatures:
        normalized = self.normalize(text)
        tokens = set(TOKEN_RE.findall(normalized))
        has_exact_tokens = any(
            len(token) >= 8 and any(char.isdigit() for char in token) for token in tokens
        ) or any(marker in tokens for marker in self.exact_markers)
        has_comparison = self._contains_marker(normalized, tokens, self.comparison_markers)
        has_contradiction = self._contains_marker(normalized, tokens, self.contradiction_markers)
        has_argumentative_terms = self._contains_marker(
            normalized,
            tokens,
            self.argumentative_markers,
        )
        asks_author_stance = self._contains_marker(
            normalized,
            tokens,
            self.author_stance_markers,
        )
        has_global_terms = self._contains_marker(normalized, tokens, self.global_markers)
        has_visual_terms = self._contains_marker(normalized, tokens, self.visual_markers)
        multi_clause = (
            normalized.count(" and ")
            + normalized.count(" y ")
            + normalized.count(",")
            + normalized.count(";")
            >= 1
        )
        return QueryFeatures(
            text=text,
            normalized_text=normalized,
            language=self.detect_language(text),
            has_exact_tokens=has_exact_tokens,
            has_comparison=has_comparison,
            has_contradiction=has_contradiction,
            has_argumentative_terms=has_argumentative_terms,
            asks_author_stance=asks_author_stance,
            has_global_terms=has_global_terms,
            has_visual_terms=has_visual_terms,
            multi_clause=multi_clause,
        )

    def choose_mode(self, features: QueryFeatures) -> QueryMode:
        if features.has_visual_terms:
            return QueryMode.VISUAL
        if features.has_global_terms:
            return QueryMode.GLOBAL
        if features.has_contradiction or features.has_argumentative_terms:
            return QueryMode.ARGUMENTATIVE
        if features.asks_author_stance:
            return QueryMode.MULTI_HOP
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
        if (
            features.has_contradiction
            or features.has_argumentative_terms
            or features.asks_author_stance
        ):
            return QueryIntent.ARGUMENTATIVE
        if features.has_comparison:
            return QueryIntent.COMPARATIVE
        if features.has_exact_tokens:
            return QueryIntent.EXACT
        return QueryIntent.FACTUAL

    def explain_route(self, features: QueryFeatures, mode: str) -> str:
        reasons: list[str] = []
        if features.has_exact_tokens:
            reasons.append("exact identifiers or literal lookup cues detected")
        if features.has_comparison:
            reasons.append("comparison cues detected")
        if features.has_contradiction:
            reasons.append("contradiction or debate cues detected")
        if features.has_argumentative_terms:
            reasons.append("argument analysis cues detected")
        if features.asks_author_stance:
            reasons.append("author-stance cues detected")
        if features.has_global_terms:
            reasons.append("global summary cues detected")
        if features.has_visual_terms:
            reasons.append("visual or layout-heavy cues detected")
        if features.multi_clause:
            reasons.append("multi-clause query detected")

        if not reasons:
            reasons.append("default factual local retrieval path")

        return f"{mode}: " + "; ".join(reasons)

    @staticmethod
    def normalize(text: str) -> str:
        return " ".join(text.strip().lower().split())

    @staticmethod
    def _contains_marker(normalized: str, tokens: set[str], markers: set[str]) -> bool:
        """Match routing cues as words or phrases, never as arbitrary substrings."""
        return any(
            marker in tokens
            if " " not in marker
            else re.search(rf"(?<!\w){re.escape(marker)}(?!\w)", normalized) is not None
            for marker in markers
        )

    @staticmethod
    def detect_language(text: str) -> str:
        lower = text.lower().strip()
        if not lower:
            return "es"

        if any(char in lower for char in "aeioun¿¡"):
            accent_hits = sum(char in lower for char in ("á", "é", "í", "ó", "ú", "ñ", "¿", "¡"))
            if accent_hits:
                return "es"

        tokens = TOKEN_RE.findall(lower)
        spanish_markers = {
            "a",
            "al",
            "de",
            "del",
            "el",
            "ella",
            "en",
            "es",
            "esta",
            "este",
            "la",
            "las",
            "lo",
            "los",
            "para",
            "por",
            "se",
            "sin",
            "son",
            "un",
            "una",
            "y",
            "que",
            "como",
            "cual",
            "donde",
            "explica",
            "resume",
            "analiza",
            "compara",
            "porque",
            "cita",
            "citas",
            "documento",
            "documentos",
            "respuesta",
            "evidencia",
            "evidencias",
            "idioma",
            "pagina",
        }
        english_markers = {
            "a",
            "an",
            "are",
            "for",
            "in",
            "is",
            "of",
            "the",
            "to",
            "with",
            "without",
            "what",
            "why",
            "how",
            "which",
            "where",
            "explain",
            "summarize",
            "summarise",
            "analyze",
            "analyse",
            "compare",
            "because",
            "citation",
            "citations",
            "document",
            "documents",
            "answer",
            "evidence",
            "language",
            "page",
        }

        spanish_score = sum(1 for token in tokens if token in spanish_markers)
        english_score = sum(1 for token in tokens if token in english_markers)

        if re.search(r"\b(?:cion|ciones|mente|idad|ario|aria)\b", lower):
            spanish_score += 1

        if spanish_score == english_score == 0:
            return "es"
        return "es" if spanish_score >= english_score else "en"

    @staticmethod
    def resolve_language(detected_language: str, collection_language_profile: str) -> str:
        """Honor an explicit corpus language; use detection only for auto profiles."""
        profile = collection_language_profile.strip().lower()
        if profile and profile != "auto":
            return profile.split("-", 1)[0]
        return detected_language
