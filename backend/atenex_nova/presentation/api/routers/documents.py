"""Documents router."""

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_node_repo import SqlDocumentNodeRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.presentation.api.dto.schemas import DocumentResponse, DocumentNodeResponse

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> DocumentResponse:
    repo = SqlDocumentRepository(session)
    doc = await repo.get_by_id(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
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
    session: AsyncSession = Depends(get_session),
) -> list[DocumentNodeResponse]:
    repo = SqlDocumentNodeRepository(session)
    nodes = await repo.get_by_document(document_id)
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
        )
        for n in nodes
    ]
