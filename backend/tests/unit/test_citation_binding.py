"""Unit tests for strict citation binding and unresolved citation handling."""

from __future__ import annotations

import pytest

from atenex_nova.application.orchestrators.answer_orchestrator import (
    AnswerOrchestrator,
    VerificationResult,
)
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.value_objects.identifiers import AnswerVerdict
from atenex_nova.shared.config.settings import Settings
from atenex_nova.shared.exceptions.base import StrictModeViolationError


def test_citation_is_resolved() -> None:
    # Cita con ancla de texto resuelta
    c1 = Citation(
        id="cit-1",
        answer_id="ans-1",
        document_id="doc-1",
        page_number=1,
        char_start=10,
        char_end=20,
        snippet="lorem ipsum",
    )
    assert AnswerOrchestrator._citation_is_resolved(c1) is True

    # Cita con ancla visual resuelta
    c2 = Citation(
        id="cit-2",
        answer_id="ans-1",
        document_id="doc-1",
        page_number=1,
        page_asset_path="/path/to/image.png",
    )
    assert AnswerOrchestrator._citation_is_resolved(c2) is True

    # Cita sin ancla (no resuelta)
    c3 = Citation(
        id="cit-3",
        answer_id="ans-1",
        document_id="doc-1",
        page_number=1,
    )
    assert AnswerOrchestrator._citation_is_resolved(c3) is False

    # Cita sin document_id (no resuelta)
    c4 = Citation(
        id="cit-4",
        answer_id="ans-1",
        document_id="",
        char_start=10,
        char_end=20,
    )
    assert AnswerOrchestrator._citation_is_resolved(c4) is False


def test_graph_edge_marker_is_traced_but_not_bound_as_document_citation() -> None:
    orchestrator = AnswerOrchestrator()
    evidence = EvidenceItem(
        id="edge-1",
        query_id="query-1",
        source_type="graph_edge",
        source_id="edge-1",
        document_id="document-1",
        score=1.0,
        rank=1,
        snippet="Relación: una afirmación aparece en el documento.",
    )

    citations = orchestrator._bind_citations([evidence], "La relación aparece en el documento [1].")
    audit = orchestrator._build_citation_audit([evidence], "La relación aparece [1].", citations)

    assert citations == []
    assert audit["uncitable_evidence_indices"] == [1]


def test_grouped_citation_markers_are_audited_individually() -> None:
    assert AnswerOrchestrator._extract_citation_indices("Afirmación [1, 4] y otra [9].") == [1, 4, 9]


def test_finalize_never_invents_markers_after_binding() -> None:
    orchestrator = AnswerOrchestrator()
    citation = Citation(
        id="citation-1",
        answer_id="answer-1",
        document_id="document-1",
        char_start=0,
        char_end=10,
        snippet="evidencia",
    )

    text = orchestrator._finalize_text(
        "Respuesta sin marcador.",
        [citation],
        "factual_local",
        "direct_answer",
        "es",
    )

    assert text == "Respuesta sin marcador."


def test_enforce_strict_answer_rules() -> None:
    # Configuración de Settings simulando modo strict habilitado
    settings = Settings(strict_mode=True, min_grounding_score=0.35)
    orchestrator = AnswerOrchestrator()
    orchestrator._settings = settings

    c_resolved = Citation(
        id="cit-1",
        answer_id="",
        document_id="doc-1",
        page_number=1,
        char_start=10,
        char_end=20,
        snippet="lorem ipsum",
    )
    c_unresolved = Citation(
        id="cit-2",
        answer_id="",
        document_id="doc-1",
        page_number=1,
    )
    verification_ok = VerificationResult(
        verdict=AnswerVerdict.VERIFIED,
        grounding_score=0.8,
        issues=[],
    )

    # 1. Pasa bien cuando hay texto y cita resuelta
    orchestrator._enforce_strict_answer("This is a valid answer.", [c_resolved], verification_ok, "hybrid")

    # 2. Falla si el texto está vacío
    with pytest.raises(StrictModeViolationError, match="strict mode requires non-empty answer text") as exc_info:
        orchestrator._enforce_strict_answer("  ", [c_resolved], verification_ok, "hybrid")
    assert exc_info.value.code == "EMPTY_ANSWER"

    # 3. Falla si no hay citas
    with pytest.raises(StrictModeViolationError, match="strict mode requires at least one citation") as exc_info:
        orchestrator._enforce_strict_answer("This is a valid answer.", [], verification_ok, "hybrid")
    assert exc_info.value.code == "MISSING_CITATIONS"

    # 4. Falla si hay una cita no resuelta
    with pytest.raises(StrictModeViolationError, match="strict mode requires citations to resolve") as exc_info:
        orchestrator._enforce_strict_answer("This is a valid answer.", [c_unresolved], verification_ok, "hybrid")
    assert exc_info.value.code == "UNRESOLVED_CITATION_BINDING"

    # 5. Falla si el score es bajo
    verification_low = VerificationResult(
        verdict=AnswerVerdict.UNVERIFIED,
        grounding_score=0.2,
        issues=["low_grounding"],
    )
    with pytest.raises(StrictModeViolationError, match="strict mode requires grounding_score") as exc_info:
        orchestrator._enforce_strict_answer("This is a valid answer.", [c_resolved], verification_low, "hybrid")
    assert exc_info.value.code == "LOW_GROUNDING_SCORE"


def test_visual_strict_mode() -> None:
    settings = Settings(strict_mode=True, require_visual=True)
    orchestrator = AnswerOrchestrator()
    orchestrator._settings = settings

    c_text = Citation(
        id="cit-1",
        answer_id="",
        document_id="doc-1",
        page_number=1,
        char_start=10,
        char_end=20,
        snippet="lorem ipsum",
    )
    c_visual = Citation(
        id="cit-2",
        answer_id="",
        document_id="doc-1",
        page_number=1,
        page_asset_path="/path/to/image.png",
    )
    verification_ok = VerificationResult(
        verdict=AnswerVerdict.VERIFIED,
        grounding_score=0.8,
        issues=[],
    )

    # Debería fallar si route_mode es visual y solo hay citas de texto
    with pytest.raises(StrictModeViolationError, match="strict visual mode requires at least one resolved visual citation") as exc_info:
        orchestrator._enforce_strict_answer("This is a valid answer.", [c_text], verification_ok, "visual")
    assert exc_info.value.code == "MISSING_VISUAL_CITATION"

    # Debería pasar si route_mode es visual y hay al menos una cita visual
    orchestrator._enforce_strict_answer("This is a valid answer.", [c_visual], verification_ok, "visual")

    # Debería pasar si route_mode es hybrid incluso sin citas visuales
    orchestrator._enforce_strict_answer("This is a valid answer.", [c_text], verification_ok, "hybrid")

