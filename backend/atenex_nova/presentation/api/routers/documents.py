"""Documents router."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.presentation.api.dto.schemas import DocumentResponse

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
        id=doc.id, collection_id=doc.collection_id, title=doc.title,
        mime_type=doc.mime_type, status=doc.status.value,
        language=doc.language, version=doc.version,
        error_message=doc.error_message,
        created_at=doc.created_at, updated_at=doc.updated_at,
    )
