"""Query intelligence router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.answer_service import AnswerService
from atenex_nova.application.services.query_service import QueryService
from atenex_nova.dependencies import get_answer_service, get_query_service
from atenex_nova.infrastructure.db.repositories.sql_answer_repo import SqlAnswerRepository
from atenex_nova.infrastructure.db.repositories.sql_citation_repo import SqlCitationRepository
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_query_repo import SqlQueryRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.presentation.api.dto.schemas import (
    AnswerResponse,
    AskRequest,
    CitationResponse,
    QueryHistoryResponse,
    QueryHitResponse,
    QuerySearchResponse,
    SearchRequest,
)
from atenex_nova.shared.exceptions.base import ServiceUnavailableError, StrictModeViolationError

router = APIRouter(prefix="/queries", tags=["queries"])


@router.get("/history", response_model=list[QueryHistoryResponse])
async def query_history(
    collection_id: str,
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
) -> list[QueryHistoryResponse]:
    query_repo = SqlQueryRepository(session)
    answer_repo = SqlAnswerRepository(session)
    citation_repo = SqlCitationRepository(session)
    queries = await query_repo.list_by_collection(collection_id=collection_id, limit=limit)
    history: list[QueryHistoryResponse] = []
    for query in queries:
        answer = await answer_repo.get_by_query_id(query.id)
        citations_count = 0
        answer_text = None
        verdict = None
        grounding_score = None
        answer_id = None
        if answer is not None:
            answer_id = answer.id
            answer_text = answer.text
            verdict = answer.verdict
            grounding_score = answer.grounding_score
            citations_count = len(await citation_repo.list_by_answer(answer.id))
        history.append(
            QueryHistoryResponse(
                query_id=query.id,
                answer_id=answer_id,
                collection_id=query.collection_id,
                query=query.text,
                answer=answer_text,
                route_mode=query.route_mode,
                intent=query.intent,
                language=query.language,
                verdict=verdict,
                grounding_score=grounding_score,
                created_at=query.created_at,

                citations_count=citations_count,
            )
        )
    return history


@router.post("/search", response_model=QuerySearchResponse)
async def search_queries(
    body: SearchRequest,
    session: AsyncSession = Depends(get_session),
    query_service: QueryService = Depends(get_query_service),
) -> QuerySearchResponse:
    collection_repo = SqlCollectionRepository(session)
    collection = await collection_repo.get_by_id(body.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        result = await query_service.search_only(
            collection_id=body.collection_id,
            query=body.query,
            mode=body.mode,
        )
    except StrictModeViolationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    return QuerySearchResponse(
        query_id=result.query.id,
        collection_id=result.query.collection_id,
        query=result.query.text,
        normalized_query=result.query.normalized_text,
        language=result.query.language,
        intent=result.query.intent,
        route_mode=result.query.route_mode,
        route_reason=result.route_reason,
        total_hits=len(result.hits),
        hits=[
            QueryHitResponse(
                id=hit.id,
                source_type=hit.source_type,
                source_id=hit.source_id,
                document_id=hit.document_id,
                title=hit.title,
                snippet=hit.snippet,
                score=hit.score,
                rank=hit.rank,
                page_number=hit.page_number,
                metadata=hit.metadata,
            )
            for hit in result.hits
        ],
    )


@router.post("/answer", response_model=AnswerResponse)
async def answer_query(
    body: AskRequest,
    session: AsyncSession = Depends(get_session),
    answer_service: AnswerService = Depends(get_answer_service),
) -> AnswerResponse:
    collection_repo = SqlCollectionRepository(session)
    collection = await collection_repo.get_by_id(body.collection_id)
    if collection is None:
        raise HTTPException(status_code=404, detail="Collection not found")

    try:
        result = await answer_service.answer(
            collection_id=body.collection_id,
            query=body.query,
            mode=body.mode,
            generation_profile=body.generation_profile,
            chat_id=body.chat_id,
        )
    except StrictModeViolationError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    except ServiceUnavailableError as exc:
        raise HTTPException(status_code=503, detail={"code": exc.code, "message": exc.message}) from exc
    return AnswerResponse(
        answer_id=result.answer.id,
        query_id=result.query_id,
        collection_id=result.collection_id,
        query=result.query_text,
        normalized_query=result.normalized_query,
        language=result.query_language,
        intent=result.query_intent,
        route_mode=result.route_mode,
        route_reason=result.route_reason,
        plan_type=result.plan_type,
        answer=result.answer.text,
        verdict=result.answer.verdict,
        grounding_score=result.answer.grounding_score,
        prompt_version=result.answer.prompt_version,
        verification_issues=result.answer.verification_issues,
        evidence_trace=result.answer.evidence_trace,
        full_prompt=result.answer.full_prompt,
        input_token_count=result.answer.input_token_count,
        output_token_count=result.answer.output_token_count,
        chat_history_used=result.answer.chat_history_used,
        chat_history_json=result.answer.chat_history_json,
        citations=[
            CitationResponse(
                id=citation.id,
                answer_id=citation.answer_id,
                document_id=citation.document_id,
                page_number=citation.page_number,
                node_id=citation.node_id,
                char_start=citation.char_start,
                char_end=citation.char_end,
                snippet=citation.snippet,
                bbox=citation.bbox,
                heading_path=citation.heading_path,
                page_asset_path=citation.page_asset_path,
            )
            for citation in result.citations
        ],
        evidence=[
            QueryHitResponse(
                id=item.id,
                source_type=item.source_type,
                source_id=item.source_id,
                document_id=item.document_id,
                title=item.title,
                snippet=item.snippet,
                score=item.score,
                rank=item.rank,
                page_number=item.page_number,
                metadata=item.metadata,
            )
            for item in result.evidence_items
        ],
    )
