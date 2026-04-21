"""Documents router."""

import json

from fastapi import APIRouter, Depends, HTTPException

from atenex_nova.application.services.document_read_service import DocumentReadService
from atenex_nova.dependencies import get_document_read_service
from atenex_nova.presentation.api.dto.schemas import (
    ChunkResponse,
    DocumentNodeResponse,
    DocumentPageResponse,
    DocumentResponse,
    PropositionResponse,
)
from atenex_nova.shared.exceptions.base import EntityNotFoundError

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    service: DocumentReadService = Depends(get_document_read_service),
) -> DocumentResponse:
    try:
        doc = await service.get_document(document_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentResponse(
        id=doc.id,
        collection_id=doc.collection_id,
        title=doc.title,
        mime_type=doc.mime_type,
        source_path=doc.source_path,
        collection_path=doc.collection_path,
        status=doc.status.value,
        language=doc.language,
        version=doc.version,
        error_message=doc.error_message,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("/{document_id}/nodes", response_model=list[DocumentNodeResponse])
async def get_document_nodes(
    document_id: str,
    service: DocumentReadService = Depends(get_document_read_service),
) -> list[DocumentNodeResponse]:
    try:
        nodes = await service.get_structure(document_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        DocumentNodeResponse(
            id=n.id,
            document_id=n.document_id,
            node_type=n.node_type.value,
            raw_text=n.raw_text,
            normalized_text=n.normalized_text,
            parent_id=n.parent_id,
            page_number=n.page_number,
            order_index=n.order_index,
            metadata_json=json.dumps(n.metadata) if n.metadata else None,
            bbox=n.bbox,
        )
        for n in nodes
    ]


@router.get("/{document_id}/structure", response_model=list[DocumentNodeResponse])
async def get_document_structure(
    document_id: str,
    service: DocumentReadService = Depends(get_document_read_service),
) -> list[DocumentNodeResponse]:
    return await get_document_nodes(document_id=document_id, service=service)


@router.get("/{document_id}/chunks", response_model=list[ChunkResponse])
async def get_document_chunks(
    document_id: str,
    service: DocumentReadService = Depends(get_document_read_service),
) -> list[ChunkResponse]:
    try:
        chunks = await service.get_chunks(document_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        ChunkResponse(
            id=chunk.id,
            document_id=chunk.document_id,
            text=chunk.text,
            summary=chunk.summary,
            token_count=chunk.token_count,
            node_ids=chunk.node_ids,
            embedding_ref=chunk.embedding_ref,
            sparse_ref=chunk.sparse_ref,
            metadata=chunk.metadata,
        )
        for chunk in chunks
    ]


@router.get("/{document_id}/propositions", response_model=list[PropositionResponse])
async def get_document_propositions(
    document_id: str,
    service: DocumentReadService = Depends(get_document_read_service),
) -> list[PropositionResponse]:
    try:
        propositions = await service.get_propositions(document_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return [
        PropositionResponse(
            id=prop.id,
            document_id=prop.document_id,
            source_chunk_id=prop.source_chunk_id,
            text=prop.text,
            kind=prop.kind,
            embedding_ref=prop.embedding_ref,
        )
        for prop in propositions
    ]


@router.get("/{document_id}/pages/{page_number}", response_model=DocumentPageResponse)
async def get_document_page(
    document_id: str,
    page_number: int,
    service: DocumentReadService = Depends(get_document_read_service),
) -> DocumentPageResponse:
    try:
        page = await service.get_page(document_id, page_number)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return DocumentPageResponse(**page)
