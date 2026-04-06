"""Application service for answer generation and retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.orchestrators.answer_orchestrator import (
    AnswerBundle,
    AnswerOrchestrator,
    normalize_citation_answer_ids,
)
from atenex_nova.application.services.query_service import QueryService
from atenex_nova.domain.entities.answer import Answer
from atenex_nova.domain.entities.citation import Citation
from atenex_nova.infrastructure.db.repositories.sql_answer_repo import SqlAnswerRepository
from atenex_nova.infrastructure.db.repositories.sql_citation_repo import SqlCitationRepository
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository


@dataclass(slots=True)
class AnswerDetail:
    answer: Answer
    citations: list[Citation]
    evidence_items: list
    query_id: str
    collection_id: str
    query_text: str
    normalized_query: str
    language: str
    intent: str
    route_mode: str


class AnswerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._query_service = QueryService(session)
        self._answer_repo = SqlAnswerRepository(session)
        self._citation_repo = SqlCitationRepository(session)
        self._query_repo = SqlQueryRepository(session)
        self._orchestrator = AnswerOrchestrator()

    async def answer(self, collection_id: str, query: str, mode: str = "auto", generation_profile: str = "standard") -> AnswerBundle:
        search_result = await self._query_service.search_only(collection_id=collection_id, query=query, mode=mode)
        bundle = await self._orchestrator.compose(search_result, generation_profile=generation_profile)
        citations = normalize_citation_answer_ids(bundle.answer.id, bundle.citations)
        await self._answer_repo.create(bundle.answer)
        if citations:
            await self._citation_repo.create_many(citations)
        await self._session.commit()
        bundle.citations = citations
        return bundle

    async def get_answer(self, answer_id: str) -> AnswerDetail | None:
        answer = await self._answer_repo.get_by_id(answer_id)
        if answer is None:
            return None
        citations = await self._citation_repo.list_by_answer(answer_id)
        query = await self._query_repo.get_by_id(answer.query_id)
        if query is None:
            return AnswerDetail(
                answer=answer,
                citations=citations,
                evidence_items=[],
                query_id=answer.query_id,
                collection_id="",
                query_text="",
                normalized_query="",
                language="auto",
                intent="factual",
                route_mode="factual_local",
            )
        search_result = await self._query_service.search_only(collection_id=query.collection_id, query=query.text, mode=query.route_mode or "auto")
        return AnswerDetail(
            answer=answer,
            citations=citations,
            evidence_items=search_result.evidence_pack.items,
            query_id=query.id,
            collection_id=query.collection_id,
            query_text=query.text,
            normalized_query=query.normalized_text,
            language=query.language,
            intent=query.intent,
            route_mode=query.route_mode,
        )