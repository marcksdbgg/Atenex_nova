"""Unit tests for LLM-specific behavior in answer orchestration."""

from __future__ import annotations

import pytest

from atenex_nova.application.orchestrators.answer_orchestrator import AnswerOrchestrator
from atenex_nova.application.orchestrators.retrieval_orchestrator import SearchResult
from atenex_nova.application.policies.context_packing_policy import (
    ContextPackingPolicy,
    EvidencePack,
)
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.domain.entities.evidence_item import EvidenceItem
from atenex_nova.domain.entities.query import Query
from atenex_nova.domain.value_objects.identifiers import AnswerVerdict, new_id
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


class _MapReduceGateway:
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
        if "Return exactly these lines" in prompt:
            return "VERDICT: verified\nGROUNDING_SCORE: 0.82\nISSUES: none"
        if "Analytical memos produced from separate evidence groups" in prompt:
            return (
                "Cervantes presenta el amor como una experiencia que exige libertad [1]. "
                "También muestra que el engaño destruye esa relación [2]."
            )
        if "Evidence group:" in prompt:
            return "El grupo identifica una tesis explícita y su consecuencia [1]."
        raise AssertionError(f"Unexpected prompt: {prompt[:120]}")


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
    assert len(generator.prompts) == 4
    assert bundle.answer.evidence_trace["generation_attempts"] == 2
    assert "VERDICT:" in generator.prompts[-1]


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
    repair_stage = bundle.answer.evidence_trace["synthesis_stages"][-1]
    assert repair_stage["stage"] == "verification_repair"
    assert repair_stage["selected"] is True
    assert bundle.answer.input_token_count > repair_stage["prompt_tokens"]


@pytest.mark.asyncio
async def test_multi_document_plan_executes_real_map_reduce() -> None:
    generator = _MapReduceGateway()
    orchestrator = AnswerOrchestrator(generator=generator)
    query = Query(
        id="query-map-reduce",
        collection_id="collection-1",
        text="¿Qué tesis desarrolla Cervantes sobre el amor y el engaño?",
        normalized_text="qué tesis desarrolla cervantes sobre el amor y el engaño",
        language="es",
        intent="argumentative",
        route_mode="multi_hop",
    )
    evidence_pack = ContextPackingPolicy().build(
        query.id,
        query.route_mode,
        [
            EvidenceItem(
                id="evidence-1",
                query_id=query.id,
                source_type="chunk",
                source_id="chunk-1",
                score=0.98,
                rank=1,
                document_id="document-1",
                title="Amor y libertad",
                snippet="Cervantes presenta el amor como una experiencia que exige libertad.",
            ),
            EvidenceItem(
                id="evidence-2",
                query_id=query.id,
                source_type="chunk",
                source_id="chunk-2",
                score=0.96,
                rank=2,
                document_id="document-2",
                title="Engaño y destrucción",
                snippet="Cervantes muestra que el engaño destruye esa relación amorosa.",
            ),
        ],
        token_budget=500,
    )
    result = SearchResult(
        query=query,
        hits=[],
        evidence_pack=evidence_pack,
        route_reason="multi_hop: two documentary facets",
    )

    bundle = await orchestrator.compose(result)

    assert bundle.plan_type == "hierarchical_synthesis"
    stages = bundle.answer.evidence_trace["synthesis_stages"]
    assert [stage["stage"] for stage in stages] == ["map", "map", "reduce"]
    assert "Analytical memos produced from separate evidence groups" in bundle.prompt
    assert "[1]" in bundle.answer.text and "[2]" in bundle.answer.text
    assert bundle.answer.full_prompt is None
    assert len(generator.prompts) == 4


def test_spanish_prompt_uses_corpus_language_without_translation_step() -> None:
    orchestrator = AnswerOrchestrator(generator=_EchoGateway())
    query = Query(
        id="query-es",
        collection_id="collection-es",
        text="el dinero es enemigo del amor?",
        normalized_text="el dinero es enemigo del amor?",
        language="es",
        route_mode="factual_local",
    )
    result = SearchResult(
        query=query,
        hits=[],
        evidence_pack=EvidencePack(query_id=query.id, route_mode=query.route_mode),
        route_reason="factual_local: default factual local retrieval path",
    )

    prompt = orchestrator._build_prompt(result, "direct_answer", "standard")

    assert "Language: español" in prompt
    assert "Escribe toda la respuesta exclusivamente en español" in prompt
    assert "no redactes primero en inglés ni entregues traducciones" in prompt


@pytest.mark.asyncio
async def test_llm_verifier_cannot_inflate_deterministic_grounding() -> None:
    orchestrator = AnswerOrchestrator(generator=_EchoGateway())
    query = Query(
        id="query-1",
        collection_id="collection-1",
        text="What does EmbeddingGemma support?",
        normalized_text="what does embeddinggemma support?",
        language="en",
        route_mode="factual_local",
    )
    evidence = EvidenceItem(
        id="evidence-1",
        query_id=query.id,
        source_type="chunk",
        source_id="chunk-1",
        document_id="document-1",
        score=1.0,
        rank=1,
        snippet="EmbeddingGemma supports 384d embeddings.",
        metadata={"source_text": "EmbeddingGemma supports 384d embeddings."},
    )
    result = SearchResult(
        query=query,
        hits=[],
        evidence_pack=EvidencePack(
            query_id=query.id,
            route_mode=query.route_mode,
            items=[evidence],
        ),
        route_reason="test",
    )
    citation = Citation(
        id="citation-1",
        answer_id="answer-1",
        document_id="document-1",
        char_start=0,
        char_end=40,
        snippet=evidence.snippet,
    )

    verification = await orchestrator._verify(
        result,
        "EmbeddingGemma supports 384d embeddings [1]",
        "direct_answer",
        [citation],
    )

    assert verification.grounding_score <= 0.88
    assert verification.verdict == AnswerVerdict.VERIFIED


@pytest.mark.asyncio
async def test_claim_verification_does_not_let_one_citation_cover_another_claim() -> None:
    orchestrator = AnswerOrchestrator(generator=_EchoGateway())
    query = Query(
        id="query-claims",
        collection_id="collection-1",
        text="What does EmbeddingGemma support?",
        normalized_text="what does embeddinggemma support",
        language="en",
        route_mode="factual_local",
    )
    evidence = EvidenceItem(
        id="evidence-1",
        query_id=query.id,
        source_type="chunk",
        source_id="chunk-1",
        document_id="document-1",
        score=1.0,
        rank=1,
        snippet="EmbeddingGemma supports 384d embeddings.",
    )
    result = SearchResult(
        query=query,
        hits=[],
        evidence_pack=EvidencePack(query_id=query.id, route_mode=query.route_mode, items=[evidence]),
        route_reason="test",
    )
    citation = Citation(
        id="citation-1",
        answer_id="answer-1",
        document_id="document-1",
        char_start=0,
        char_end=40,
        snippet=evidence.snippet,
    )

    verification = await orchestrator._verify(
        result,
        "EmbeddingGemma supports 384d embeddings [1]. It also proves that every retrieval answer is correct.",
        "direct_answer",
        [citation],
    )

    assert verification.verdict != AnswerVerdict.VERIFIED
    assert "uncited_claims" in verification.issues


@pytest.mark.asyncio
async def test_spanish_query_rejects_english_answer_language() -> None:
    orchestrator = AnswerOrchestrator(generator=_EchoGateway())
    query = Query(
        id="query-es",
        collection_id="collection-es",
        text="el dinero es enemigo del amor?",
        normalized_text="el dinero es enemigo del amor?",
        language="es",
        route_mode="factual_local",
    )
    evidence = EvidenceItem(
        id="evidence-1",
        query_id=query.id,
        source_type="chunk",
        source_id="chunk-1",
        document_id="document-1",
        score=1.0,
        rank=1,
        snippet="El dinero no aparece descrito como enemigo del amor.",
        metadata={"source_text": "El dinero no aparece descrito como enemigo del amor."},
    )
    result = SearchResult(
        query=query,
        hits=[],
        evidence_pack=EvidencePack(query_id=query.id, route_mode=query.route_mode, items=[evidence]),
        route_reason="test",
    )
    citation = Citation(
        id="citation-1",
        answer_id="answer-1",
        document_id="document-1",
        char_start=0,
        char_end=55,
        snippet=evidence.snippet,
    )

    verification = await orchestrator._verify(
        result,
        "Based on the provided evidence, money is not described as an enemy of love [1].",
        "direct_answer",
        [citation],
    )

    assert verification.verdict == AnswerVerdict.UNVERIFIED
    assert "wrong_output_language" in verification.issues
