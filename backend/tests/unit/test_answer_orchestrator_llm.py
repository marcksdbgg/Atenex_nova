"""Unit tests for LLM-specific behavior in answer orchestration."""

from __future__ import annotations

import pytest

from atenex_nova.application.orchestrators.answer_orchestrator import AnswerOrchestrator
from atenex_nova.application.orchestrators.retrieval_orchestrator import SearchResult
from atenex_nova.application.policies.context_packing_policy import ContextPackingPolicy
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.entities.query import Query
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.shared.exceptions.base import ServiceUnavailableError


class _BlankGateway:
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        return "   "


class _TextGateway:
    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        return "  respuesta valida  "


class _EchoGateway:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        if "VERDICT:" in prompt and "GROUNDING_SCORE:" in prompt:
            return "VERDICT: verified\nGROUNDING_SCORE: 0.88\nISSUES: none"
        return "EmbeddingGemma supports 384d embeddings [1] [2]"


class _RepairGateway:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.answer_calls = 0
        self.verification_calls = 0

    async def generate(
        self,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.3,
        stop: list[str] | None = None,
    ) -> str:
        self.prompts.append(prompt)
        if "VERDICT:" in prompt and "GROUNDING_SCORE:" in prompt:
            self.verification_calls += 1
            if self.verification_calls == 1:
                return "VERDICT: unverified\nGROUNDING_SCORE: 0.1\nISSUES: missing_citations"
            return "VERDICT: verified\nGROUNDING_SCORE: 0.92\nISSUES: none"

        self.answer_calls += 1
        if "Verification Repair" in prompt:
            return "EmbeddingGemma supports 384d embeddings [1]"
        return "Ungrounded response without citation"


@pytest.mark.asyncio
async def test_generate_raises_service_unavailable_when_llm_returns_empty() -> None:
    orchestrator = AnswerOrchestrator(generator=_BlankGateway())

    with pytest.raises(ServiceUnavailableError) as exc:
        await orchestrator._generate("prompt", "direct_answer")

    assert exc.value.code == "SERVICE_UNAVAILABLE"
    assert "non-LLM fallback answers are disabled" in str(exc.value)


@pytest.mark.asyncio
async def test_generate_accepts_non_empty_llm_output() -> None:
    orchestrator = AnswerOrchestrator(generator=_TextGateway())

    text = await orchestrator._generate("prompt", "direct_answer")

    assert text.text.strip() == "respuesta valida"


@pytest.mark.asyncio
async def test_compose_includes_all_selected_evidence_in_prompt() -> None:
    generator = _EchoGateway()
    orchestrator = AnswerOrchestrator(generator=generator)
    policy = ContextPackingPolicy()
    query = Query(
        id=new_id(),
        collection_id="collection-1",
        text="What does EmbeddingGemma support?",
        normalized_text="What does EmbeddingGemma support?",
        language="en",
        intent="exact",
        route_mode="factual_local",
    )
    items = [
        EvidenceItem(
            id=new_id(),
            query_id=query.id,
            source_type="chunk",
            source_id=f"chunk-{index}",
            score=1.0 - (index * 0.01),
            rank=index + 1,
            document_id="doc-1",
            title=f"Evidence {index}",
            snippet=f"Evidence snippet {index} with unique marker {index}.",
        )
        for index in range(15)
    ]
    evidence_pack = policy.build(query.id, query.route_mode, items, token_budget=600)
    search_result = SearchResult(query=query, hits=[], evidence_pack=evidence_pack, route_reason="lexical fallback")

    bundle = await orchestrator.compose(search_result)

    assert len(bundle.evidence_items) == len(evidence_pack.items)
    assert "Evidence snippet 0" in bundle.prompt
    assert "Evidence snippet 1" in bundle.prompt
    assert "Evidence snippet 2" in bundle.prompt
    assert bundle.citations
    assert len(generator.prompts) == 2
    assert "VERDICT:" in generator.prompts[1]


@pytest.mark.asyncio
async def test_compose_retries_once_when_verification_is_weak() -> None:
    generator = _RepairGateway()
    orchestrator = AnswerOrchestrator(generator=generator)
    query = Query(
        id=new_id(),
        collection_id="collection-1",
        text="What does EmbeddingGemma support?",
        normalized_text="What does EmbeddingGemma support?",
        language="en",
        intent="exact",
        route_mode="factual_local",
    )
    evidence_pack = ContextPackingPolicy().build(
        query.id,
        query.route_mode,
        [
            EvidenceItem(
                id=new_id(),
                query_id=query.id,
                source_type="chunk",
                source_id="chunk-1",
                score=0.99,
                rank=1,
                document_id="doc-1",
                title="EmbeddingGemma",
                snippet="EmbeddingGemma supports 384d embeddings for the standard profile.",
            ),
        ],
        token_budget=300,
    )
    search_result = SearchResult(query=query, hits=[], evidence_pack=evidence_pack, route_reason="exact: literal cues")

    bundle = await orchestrator.compose(search_result)

    assert bundle.answer.text.startswith("EmbeddingGemma supports")
    assert bundle.answer.evidence_trace["generation_attempts"] == 2
    assert "regenerated_after_failed_verification" in bundle.answer.verification_issues
