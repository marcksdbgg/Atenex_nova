"""Pipeline observability endpoints."""

from fastapi import APIRouter, Depends
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.repositories.sql_pipeline_audit_repo import SqlPipelineAuditRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.presentation.api.dto.schemas import DocumentEvidenceResponse, DocumentResponse, JobResponse, PipelineAuditResponse

router = APIRouter(prefix="/observability", tags=["observability"])


@router.get("/audit", response_model=list[PipelineAuditResponse])
async def list_pipeline_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    run_id: str | None = None,
    limit: int = 100,
    session: AsyncSession = Depends(get_session),
) -> list[PipelineAuditResponse]:
    repo = SqlPipelineAuditRepository(session)
    if run_id:
        items = await repo.list_by_run(run_id, limit=limit)
    elif entity_type and entity_id:
        items = await repo.list_by_entity(entity_type, entity_id, limit=limit)
    else:
        items = await repo.list_recent(limit=limit)
    return [PipelineAuditResponse(**item) for item in items]


@router.get("/documents/{document_id}/evidence", response_model=DocumentEvidenceResponse)
async def get_document_evidence(
    document_id: str,
    session: AsyncSession = Depends(get_session),
) -> DocumentEvidenceResponse:
    document_repo = SqlDocumentRepository(session)
    job_repo = SqlJobRepository(session)
    audit_repo = SqlPipelineAuditRepository(session)

    document = await document_repo.get_by_id(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    jobs = await job_repo.list_by_target(document_id, limit=50)
    audit_events = await audit_repo.list_by_entity("document", document_id, limit=250)

    return DocumentEvidenceResponse(
        entity_id=document_id,
        document=DocumentResponse(
            id=document.id,
            collection_id=document.collection_id,
            title=document.title,
            mime_type=document.mime_type,
            source_path=document.source_path,
            status=document.status.value,
            language=document.language,
            version=document.version,
            error_message=document.error_message,
            created_at=document.created_at,
            updated_at=document.updated_at,
        ),
        jobs=[
            JobResponse(
                id=job.id,
                job_type=job.job_type.value,
                target_id=job.target_id,
                status=job.status.value,
                error=job.error,
                retries=job.retries,
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
            )
            for job in jobs
        ],
        audit_events=[PipelineAuditResponse(**item) for item in audit_events],
    )