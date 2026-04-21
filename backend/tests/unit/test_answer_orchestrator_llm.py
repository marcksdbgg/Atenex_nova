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
        return "EmbeddingGemma supports 384d embeddings [1] [2]"


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

    assert text == "respuesta valida"


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
    search_result = SearchResult(query=query, hits=[], evidence_pack=evidence_pack)

    bundle = await orchestrator.compose(search_result)

    assert len(bundle.evidence_items) == 15
    assert "Evidence snippet 0" in bundle.prompt
    assert "Evidence snippet 14" in bundle.prompt
    assert bundle.citations
    assert len(generator.prompts) == 1
