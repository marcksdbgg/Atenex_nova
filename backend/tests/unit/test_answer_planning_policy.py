"""Unit tests for route-aware answer planning."""

from atenex_nova.application.policies.answer_planning_policy import AnswerPlanningPolicy
from atenex_nova.application.policies.context_packing_policy import EvidencePack
from atenex_nova.domain.entities.evidence_item import EvidenceItem


def _summary() -> EvidenceItem:
    return EvidenceItem(
        id="summary-1",
        query_id="query-1",
        source_type="summary",
        source_id="summary-1",
        score=1.0,
        rank=1,
        snippet="Resumen general de la colección.",
    )


def test_local_question_stays_direct_even_when_a_summary_is_retrieved() -> None:
    pack = EvidencePack(
        query_id="query-1",
        route_mode="factual_local",
        items=[_summary()],
        summaries=[_summary()],
    )

    assert AnswerPlanningPolicy().choose_plan(pack) == "direct_answer"


def test_global_question_uses_global_synthesis_when_summaries_are_available() -> None:
    summary = _summary()
    pack = EvidencePack(
        query_id="query-1",
        route_mode="global",
        items=[summary],
        summaries=[summary],
    )

    assert AnswerPlanningPolicy().choose_plan(pack) == "global_synthesis"


def test_global_question_does_not_require_a_pseudo_summary() -> None:
    pack = EvidencePack(
        query_id="query-1",
        route_mode="global",
        items=[],
        summaries=[],
    )

    assert AnswerPlanningPolicy().choose_plan(pack) == "global_synthesis"


def test_multi_hop_across_documents_uses_hierarchical_synthesis() -> None:
    first = _summary()
    first.document_id = "document-1"
    second = _summary()
    second.id = "summary-2"
    second.source_id = "summary-2"
    second.document_id = "document-2"
    pack = EvidencePack(
        query_id="query-1",
        route_mode="multi_hop",
        items=[first, second],
    )

    assert AnswerPlanningPolicy().choose_plan(pack) == "hierarchical_synthesis"
