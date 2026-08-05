"""Bounded deterministic query variants for multi-facet retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass

from atenex_nova.application.policies.conversation_retrieval_policy import (
    CONVERSATION_CONTEXT_MARKER,
)

_TOKEN_RE = re.compile(r"[\w\-]+", re.UNICODE)
_STRONG_BOUNDARY_RE = re.compile(r"\s*(?:;|\n+|(?<=[.!?])\s+)\s*")
_CLAUSE_CONNECTOR_RE = re.compile(
    r"\s+(?:y|e|pero|mientras|además|and|but|while|whereas)\s+",
    re.IGNORECASE,
)
_NORMALIZE_RE = re.compile(r"[^\w\-]+", re.UNICODE)
_CONSERVATIVE_CORRECTIONS = (
    (re.compile(r"\beutanacia\b", re.IGNORECASE), "eutanasia"),
)
_STOPWORDS = {
    "a",
    "al",
    "and",
    "como",
    "con",
    "de",
    "del",
    "el",
    "en",
    "es",
    "how",
    "la",
    "las",
    "lo",
    "los",
    "of",
    "on",
    "para",
    "por",
    "que",
    "qué",
    "the",
    "to",
    "un",
    "una",
    "what",
    "y",
}


@dataclass(frozen=True, slots=True)
class RetrievalQueryVariant:
    """One transient retrieval representation; never a persisted Query entity."""

    index: int
    kind: str
    text: str
    audit_text: str

    def audit_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "kind": self.kind,
            "text": self.audit_text,
        }


@dataclass(frozen=True, slots=True)
class MultiQueryPlan:
    variants: tuple[RetrievalQueryVariant, ...]
    reason: str

    @property
    def expanded(self) -> bool:
        return len(self.variants) > 1


class MultiQueryRetrievalPolicy:
    """Extract useful clauses without generative rewriting or mutable state."""

    expandable_modes = frozenset({"multi_hop", "argumentative", "global"})
    max_facet_variants = 3
    min_tokens = 4
    min_content_tokens = 2
    max_audit_chars = 240

    def build(
        self,
        *,
        original_text: str,
        retrieval_text: str,
        route_mode: str,
    ) -> MultiQueryPlan:
        execution_text = retrieval_text.strip() or original_text.strip()
        original = RetrievalQueryVariant(
            index=0,
            kind="original",
            text=execution_text,
            audit_text=self._bounded_audit_text(original_text),
        )
        if route_mode not in self.expandable_modes:
            return MultiQueryPlan(variants=(original,), reason="route_not_expandable")

        current_text, context_suffix = self._split_conversation_context(execution_text)
        seen = {self._normalize(current_text), self._normalize(execution_text)}
        facets: list[str] = []
        for candidate in self._candidate_facets(current_text, route_mode):
            cleaned = self._clean(candidate)
            normalized = self._normalize(cleaned)
            if not normalized or normalized in seen or not self._is_useful(cleaned):
                continue
            seen.add(normalized)
            facets.append(cleaned)
            if len(facets) >= self.max_facet_variants:
                break

        variants = [original]
        for index, facet in enumerate(facets, start=1):
            variants.append(
                RetrievalQueryVariant(
                    index=index,
                    kind="facet",
                    text=f"{facet}{context_suffix}",
                    audit_text=self._bounded_audit_text(facet),
                )
            )
        reason = "expanded_facets" if facets else "no_useful_facets"
        return MultiQueryPlan(variants=tuple(variants), reason=reason)

    def _candidate_facets(self, text: str, route_mode: str) -> list[str]:
        candidates: list[str] = []
        corrected_text = self._correct_common_domain_typos(text)
        if corrected_text != text:
            candidates.append(corrected_text)
        strong_clauses = [part for part in _STRONG_BOUNDARY_RE.split(text) if part.strip()]
        clauses = strong_clauses or [text]
        polarity_clauses: set[int] = set()
        if route_mode == "argumentative":
            for index, clause in enumerate(clauses):
                polarity_facets = self._polarity_facets(clause)
                if polarity_facets:
                    polarity_clauses.add(index)
                    candidates.extend(polarity_facets)

        if len(strong_clauses) > 1:
            candidates.extend(strong_clauses)

        for index, clause in enumerate(clauses):
            # Do not split the fixed contrast phrase ``a favor y en contra`` (or
            # ``for and against``) at its conjunction after producing both sides.
            if index in polarity_clauses:
                continue
            connector_clauses = [
                part for part in _CLAUSE_CONNECTOR_RE.split(clause) if part.strip()
            ]
            if len(connector_clauses) > 1:
                candidates.extend(connector_clauses)

        if "," in text:
            candidates.extend(part for part in text.split(",") if part.strip())
        return candidates

    @staticmethod
    def _correct_common_domain_typos(text: str) -> str:
        """Correct only benchmarked high-confidence terms; never generatively rewrite."""
        corrected = text
        for pattern, replacement in _CONSERVATIVE_CORRECTIONS:
            corrected = pattern.sub(replacement, corrected)
        return corrected

    @staticmethod
    def _polarity_facets(text: str) -> list[str]:
        patterns = (
            re.compile(
                r"\ba favor\s+y\s+en contra\s+de\s+(?P<topic>.+)",
                re.IGNORECASE,
            ),
            re.compile(
                r"\bfor\s+and\s+against\s+(?P<topic>.+)",
                re.IGNORECASE,
            ),
        )
        for pattern in patterns:
            match = pattern.search(text)
            if match is None:
                continue
            prefix = text[: match.start()].rstrip()
            topic = match.group("topic").strip()
            if "a favor" in match.group(0).casefold():
                return [
                    f"{prefix} a favor de {topic}",
                    f"{prefix} en contra de {topic}",
                ]
            return [
                f"{prefix} for {topic}",
                f"{prefix} against {topic}",
            ]
        return []

    @classmethod
    def _is_useful(cls, text: str) -> bool:
        tokens = [token.casefold() for token in _TOKEN_RE.findall(text)]
        content_tokens = [token for token in tokens if token not in _STOPWORDS]
        return len(tokens) >= cls.min_tokens and len(set(content_tokens)) >= cls.min_content_tokens

    @staticmethod
    def _split_conversation_context(text: str) -> tuple[str, str]:
        marker = f"\n\n{CONVERSATION_CONTEXT_MARKER}\n"
        current_text, separator, history = text.partition(marker)
        if not separator:
            return text, ""
        return current_text, f"{marker}{history}"

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.strip(" \t\r\n¿?.,;:!").split())

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(_NORMALIZE_RE.sub(" ", text.casefold()).split())

    @classmethod
    def _bounded_audit_text(cls, text: str) -> str:
        cleaned = " ".join(text.split())
        if len(cleaned) <= cls.max_audit_chars:
            return cleaned
        return cleaned[: cls.max_audit_chars].rsplit(" ", 1)[0]
