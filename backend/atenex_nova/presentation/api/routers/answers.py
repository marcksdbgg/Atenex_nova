"""Answer retrieval router."""


from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from atenex_nova.application.services.answer_service import AnswerService
from atenex_nova.dependencies import get_answer_service
from atenex_nova.presentation.api.dto.schemas import (
    AnswerResponse,
    CitationResponse,
    QueryHitResponse,
)

router = APIRouter(prefix="/answers", tags=["answers"])


@router.get("/{answer_id}", response_model=AnswerResponse)
async def get_answer(answer_id: str, service: AnswerService = Depends(get_answer_service)) -> AnswerResponse:
    detail = await service.get_answer(answer_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    return AnswerResponse(
        answer_id=detail.answer.id,
        query_id=detail.answer.query_id,
        collection_id=detail.collection_id,
        query=detail.query_text,
        normalized_query=detail.normalized_query,
        language=detail.language,
        intent=detail.intent,
        route_mode=detail.route_mode,
        route_reason=detail.route_reason,
        plan_type=detail.answer.plan_type,
        answer=detail.answer.text,
        verdict=detail.answer.verdict,
        grounding_score=detail.answer.grounding_score,
        prompt_version=detail.answer.prompt_version,
        verification_issues=detail.answer.verification_issues,
        evidence_trace=detail.answer.evidence_trace,
        full_prompt=detail.answer.full_prompt,
        input_token_count=detail.answer.input_token_count,
        output_token_count=detail.answer.output_token_count,
        chat_history_used=detail.answer.chat_history_used,
        chat_history_json=detail.answer.chat_history_json,
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
            for citation in detail.citations
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
            for item in detail.evidence_items
        ],
    )


@router.get("/{answer_id}/export/markdown")
async def export_answer_markdown(
    answer_id: str,
    service: AnswerService = Depends(get_answer_service),
) -> Response:
    detail = await service.get_answer(answer_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    content = service.export_markdown(detail)
    return Response(content=content, media_type="text/markdown; charset=utf-8")


@router.get("/{answer_id}/export/pdf")
async def export_answer_pdf(
    answer_id: str,
    service: AnswerService = Depends(get_answer_service),
) -> Response:
    detail = await service.get_answer(answer_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Answer not found")
    pdf_bytes = service.export_pdf(detail)
    return Response(content=pdf_bytes, media_type="application/pdf")
