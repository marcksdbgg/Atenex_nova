"""Import session router."""

from fastapi import APIRouter, Depends, HTTPException

from atenex_nova.application.services.import_session_service import ImportSessionService
from atenex_nova.dependencies import get_import_session_service
from atenex_nova.infrastructure.db.repositories.sql_import_session_repo import ImportSessionRecord
from atenex_nova.presentation.api.dto.schemas import (
    ImportSessionItemResponse,
    ImportSessionResponse,
)

router = APIRouter(prefix="/import-sessions", tags=["import-sessions"])


def _import_session_response(session: ImportSessionRecord) -> ImportSessionResponse:
    return ImportSessionResponse(
        id=session.id,
        collection_id=session.collection_id,
        source_kind=session.source_kind,
        source_root=session.source_root,
        collection_path=session.collection_path,
        status=session.status,
        discovered_count=session.discovered_count,
        attempted_count=session.attempted_count,
        created_count=session.created_count,
        deduplicated_count=session.deduplicated_count,
        skipped_count=session.skipped_count,
        failed_count=session.failed_count,
        queued_jobs_count=session.queued_jobs_count,
        started_at=session.started_at,
        completed_at=session.completed_at,
        error=session.error,
    )


@router.get("/{session_id}", response_model=ImportSessionResponse)
async def get_import_session(
    session_id: str,
    service: ImportSessionService = Depends(get_import_session_service),
) -> ImportSessionResponse:
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    return _import_session_response(session)


@router.get("/{session_id}/items", response_model=list[ImportSessionItemResponse])
async def list_import_session_items(
    session_id: str,
    offset: int = 0,
    limit: int = 100,
    status: str | None = None,
    service: ImportSessionService = Depends(get_import_session_service),
) -> list[ImportSessionItemResponse]:
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    items = await service.list_items(session_id, offset=offset, limit=limit, status=status)
    return [
        ImportSessionItemResponse(
            id=item.id,
            session_id=item.session_id,
            relative_path=item.relative_path,
            source_path=item.source_path,
            checksum=item.checksum,
            mime_type=item.mime_type,
            status=item.status,
            document_id=item.document_id,
            job_id=item.job_id,
            error=item.error,
            created_at=item.created_at,
        )
        for item in items
    ]


@router.post("/{session_id}/finalize", response_model=ImportSessionResponse)
async def finalize_import_session(
    session_id: str,
    service: ImportSessionService = Depends(get_import_session_service),
) -> ImportSessionResponse:
    session = await service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    finalized = await service.finalize_session(session_id)
    if finalized is None:
        raise HTTPException(status_code=404, detail="Import session not found")
    return _import_session_response(finalized)
