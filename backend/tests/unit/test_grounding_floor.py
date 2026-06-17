"""Unit tests for configurable grounding floor (H-13)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from atenex_nova.application.orchestrators.answer_orchestrator import AnswerOrchestrator
from atenex_nova.application.orchestrators.retrieval_orchestrator import SearchResult
from atenex_nova.application.policies.context_packing_policy import EvidencePack
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.entities.query import Query
from atenex_nova.domain.value_objects.identifiers import AnswerVerdict
from atenex_nova.shared.config.settings import Settings


def _citation() -> Citation:
    return Citation(
        id="cit-1",
        answer_id="ans-1",
        document_id="doc-1",
        page_number=1,
        page_asset_path="/tmp/page.png",
        snippet="evidence snippet",
    )


@pytest.mark.asyncio
async def test_grounding_score_respects_zero_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(grounding_floor=0.0, min_grounding_score=0.35)
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.answer_orchestrator.get_settings",
        lambda: settings,
    )

    orchestrator = AnswerOrchestrator()
    orchestrator._verify_with_llm = AsyncMock(return_value=None)  # type: ignore[method-assign]

    search_result = SearchResult(
        query=Query(id="q1", collection_id="c1", text="test", normalized_text="test"),
        hits=[],
        evidence_pack=EvidencePack(query_id="q1", route_mode="test", items=[], contradictions=[]),
        route_reason="test",
    )

    result = await orchestrator._verify(
        search_result,
        answer_text="word",
        plan_type="direct",
        citations=[_citation()],
    )

    assert result.grounding_score < settings.min_grounding_score
    assert result.verdict == AnswerVerdict.UNVERIFIED


@pytest.mark.asyncio
async def test_grounding_floor_adds_offset_without_inflating_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(grounding_floor=0.1, min_grounding_score=0.2)
    monkeypatch.setattr(
        "atenex_nova.application.orchestrators.answer_orchestrator.get_settings",
        lambda: settings,
    )

    orchestrator = AnswerOrchestrator()
    orchestrator._verify_with_llm = AsyncMock(return_value=None)  # type: ignore[method-assign]

    evidence = EvidenceItem(
        id="e1",
        query_id="q1",
        source_type="chunk",
        source_id="c1",
        document_id="d1",
        title="t",
        snippet="matching token here",
        score=1.0,
        rank=1,
    )
    search_result = SearchResult(
        query=Query(id="q1", collection_id="c1", text="test", normalized_text="test"),
        hits=[],
        evidence_pack=EvidencePack(query_id="q1", route_mode="test", items=[evidence], contradictions=[]),
        route_reason="test",
    )

    result = await orchestrator._verify(
        search_result,
        answer_text="matching token here",
        plan_type="direct",
        citations=[_citation()],
    )

    assert result.grounding_score >= settings.grounding_floor
    assert result.grounding_score <= 1.0
