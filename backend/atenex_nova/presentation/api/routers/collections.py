"""Collections router."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.collection_cleanup_service import CollectionCleanupService
from atenex_nova.application.services.collection_service import CollectionService
from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.application.services.import_session_service import ImportSessionService
from atenex_nova.application.services.rebuild_service import RebuildService
from atenex_nova.dependencies import (
    get_blob_store,
    get_collection_service,
    get_document_service,
    get_import_session_service,
)
from atenex_nova.domain.value_objects.identifiers import DocumentStatus, JobStatus, new_id
from atenex_nova.infrastructure.db.models.tables import DocumentModel, JobModel
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_import_session_repo import ImportSessionRecord
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.files.blob_store import BlobStore
from atenex_nova.presentation.api.dto.schemas import (
    CollectionPipelineStatusResponse,
    CollectionResponse,
    CreateCollectionRequest,
    DocumentResponse,
    ImportLocalDocumentRequest,
    ImportLocalFolderRequest,
    ImportLocalFolderResponse,
    ImportSessionResponse,
    StartImportSessionRequest,
    UpdateCollectionRequest,
)
from atenex_nova.shared.config.settings import get_settings
from atenex_nova.shared.exceptions.base import EntityNotFoundError
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService

router = APIRouter(prefix="/collections", tags=["collections"])


def _normalize_collection_path(raw_path: str | None) -> str:
    if not raw_path:
        return ""
    normalized = raw_path.replace("\\", "/").strip().strip("/")
    parts = [part.strip() for part in normalized.split("/") if part.strip() and part not in {".", ".."}]
    return "/".join(parts)


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


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    body: CreateCollectionRequest,
    service: CollectionService = Depends(get_collection_service),
) -> CollectionResponse:
    entity = await service.create(
        name=body.name,
        description=body.description or "",
        language_profile=body.language_profile or "auto",
    )
    return CollectionResponse(**entity.__dict__)


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    offset: int = 0,
    limit: int = 50,
    service: CollectionService = Depends(get_collection_service),
) -> list[CollectionResponse]:
    items = await service.list_all(offset=offset, limit=limit)
    return [CollectionResponse(**c.__dict__) for c in items]


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    service: CollectionService = Depends(get_collection_service),
) -> CollectionResponse:
    try:
        entity = await service.get(collection_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionResponse(**entity.__dict__)


@router.get("/{collection_id}/pipeline-status", response_model=CollectionPipelineStatusResponse)
async def get_collection_pipeline_status(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
    service: CollectionService = Depends(get_collection_service),
) -> CollectionPipelineStatusResponse:
    try:
        await service.get(collection_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    doc_rows = await session.execute(
        select(DocumentModel.status, func.count())
        .where(DocumentModel.collection_id == collection_id)
        .group_by(DocumentModel.status)
    )
    documents_by_status = {str(row[0]): int(row[1]) for row in doc_rows.all()}

    doc_ids_result = await session.execute(
        select(DocumentModel.id).where(DocumentModel.collection_id == collection_id)
    )
    document_ids = [str(row[0]) for row in doc_ids_result.all()]

    job_repo = SqlJobRepository(session)
    jobs_by_status = await job_repo.count_by_status_for_targets(document_ids)
    jobs_by_type = await job_repo.count_by_type_and_status_for_targets(document_ids)

    cutoff = datetime.now(UTC) - timedelta(minutes=10)
    stale_result = await session.execute(
        select(func.count())
        .select_from(JobModel)
        .where(
            JobModel.target_id.in_(document_ids),
            JobModel.status == JobStatus.RUNNING.value,
            JobModel.started_at.is_not(None),
            JobModel.started_at < cutoff,
        )
    )
    stale_running_jobs = int(stale_result.scalar_one() or 0)

    import_service = ImportSessionService(
        session,
        DocumentService(doc_repo=SqlDocumentRepository(session), job_repo=job_repo),
    )
    recent_sessions = await import_service.list_by_collection(collection_id, limit=5)

    settings = get_settings()
    return CollectionPipelineStatusResponse(
        collection_id=collection_id,
        documents_by_status=documents_by_status,
        jobs_by_status=jobs_by_status,
        jobs_by_type=jobs_by_type,
        stale_running_jobs=stale_running_jobs,
        candidate_backend_default=settings.candidate_backend,
        recent_import_sessions=[_import_session_response(item) for item in recent_sessions],
    )


@router.get("/{collection_id}/import-sessions", response_model=list[ImportSessionResponse])
async def list_collection_import_sessions(
    collection_id: str,
    offset: int = 0,
    limit: int = 20,
    service: CollectionService = Depends(get_collection_service),
    import_service: ImportSessionService = Depends(get_import_session_service),
) -> list[ImportSessionResponse]:
    try:
        await service.get(collection_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sessions = await import_service.list_by_collection(collection_id, offset=offset, limit=limit)
    return [_import_session_response(item) for item in sessions]


@router.post("/{collection_id}/import-sessions", response_model=ImportSessionResponse, status_code=201)
async def start_import_session(
    collection_id: str,
    body: StartImportSessionRequest,
    service: CollectionService = Depends(get_collection_service),
    import_service: ImportSessionService = Depends(get_import_session_service),
) -> ImportSessionResponse:
    try:
        await service.get(collection_id)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    session = await import_service.start_session(
        collection_id=collection_id,
        source_kind=body.source_kind,
        source_root=body.source_root,
        collection_path=_normalize_collection_path(body.collection_path),
        discovered_count=body.discovered_count,
    )
    return _import_session_response(session)


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: str,
    body: UpdateCollectionRequest,
    service: CollectionService = Depends(get_collection_service),
) -> CollectionResponse:
    try:
        entity = await service.update(
            collection_id=collection_id,
            name=body.name,
            description=body.description,
            generation_profile=body.generation_profile,
            retrieval_profile=body.retrieval_profile,
        )
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CollectionResponse(**entity.__dict__)


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    service = CollectionCleanupService(session)
    deleted = await service.delete_collection(collection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")


@router.get("/{collection_id}/documents", response_model=list[DocumentResponse])
async def list_collection_documents(
    collection_id: str,
    offset: int = 0,
    limit: int = 50,
    status: DocumentStatus | None = None,
    doc_service: DocumentService = Depends(get_document_service),
) -> list[DocumentResponse]:
    items = await doc_service.list_by_collection(collection_id, offset=offset, limit=limit, status=status)
    return [
        DocumentResponse(
            id=item.id,
            collection_id=item.collection_id,
            title=item.title,
            mime_type=item.mime_type,
            source_path=item.source_path,
            collection_path=item.collection_path,
            status=item.status.value,
            language=item.language,
            version=item.version,
            error_message=item.error_message,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]


@router.post("/{collection_id}/rebuild")
async def rebuild_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = RebuildService(session)
    try:
        job_id = await service.enqueue(collection_id)
        await session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"job_id": job_id, "status": "queued"}


@router.post("/{collection_id}/documents", response_model=DocumentResponse, status_code=201)
async def upload_document(
    collection_id: str,
    file: UploadFile = File(...),
    collection_path: str | None = Form(default=None),
    display_title: str | None = Form(default=None),
    import_session_id: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
    doc_service: DocumentService = Depends(get_document_service),
    import_service: ImportSessionService = Depends(get_import_session_service),
    blob_store: BlobStore = Depends(get_blob_store),
) -> DocumentResponse:
    normalized_collection_path = _normalize_collection_path(collection_path) or _normalize_collection_path(file.filename or "unknown")
    resolved_title = (display_title or "").strip() or normalized_collection_path or file.filename or "unknown"

    audit = PipelineAuditService(session=session)
    async with audit.step(
        run_id=new_id(),
        entity_type="collection",
        entity_id=collection_id,
        pipeline="ingestion",
        stage="register_upload",
        context={"filename": file.filename, "mime_type": file.content_type, "collection_path": normalized_collection_path},
    ) as step:
        data = await file.read()
        checksum = BlobStore.compute_checksum(data)
        deduplicated = False
        existing = await doc_service.find_by_collection_checksum(collection_id, checksum)
        if existing is not None:
            doc = existing
            deduplicated = True
        else:
            provisional_doc_id = new_id()
            path = blob_store.store(
                collection_id,
                provisional_doc_id,
                file.filename or "unknown",
                data,
                relative_path=normalized_collection_path,
            )
            doc = await doc_service.register(
                collection_id=collection_id,
                title=resolved_title,
                source_path=str(path),
                mime_type=file.content_type or "application/octet-stream",
                checksum=checksum,
                doc_id=provisional_doc_id,
                collection_path=normalized_collection_path,
            )
            deduplicated = doc.id != provisional_doc_id
            if deduplicated:
                blob_store.delete(collection_id, provisional_doc_id)

        step.metrics(
            bytes=len(data),
            checksum=checksum,
            source_path=doc.source_path,
            collection_path=normalized_collection_path,
            document_id=doc.id,
            deduplicated=deduplicated,
        )

        if import_session_id:
            await import_service.record_upload_item(
                import_session_id,
                relative_path=normalized_collection_path or (file.filename or "unknown"),
                source_path=doc.source_path,
                checksum=checksum,
                mime_type=file.content_type or "application/octet-stream",
                document=doc,
                deduplicated=deduplicated,
            )

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


@router.post("/{collection_id}/documents/import", response_model=DocumentResponse, status_code=201)
async def import_local_document(
    collection_id: str,
    body: ImportLocalDocumentRequest,
    session: AsyncSession = Depends(get_session),
    doc_service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    audit = PipelineAuditService(session=session)
    async with audit.step(
        run_id=new_id(),
        entity_type="collection",
        entity_id=collection_id,
        pipeline="ingestion",
        stage="register_local",
        context={"source_path": body.source_path, "title": body.title, "mime_type": body.mime_type},
    ) as step:
        doc = await doc_service.register_local(
            collection_id=collection_id,
            source_path=body.source_path,
            title=body.title,
            mime_type=body.mime_type,
            collection_path=body.collection_path,
        )
        step.metrics(
            source_path=doc.source_path,
            checksum=doc.checksum,
            collection_path=doc.collection_path,
            document_id=doc.id,
        )
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


@router.post("/{collection_id}/documents/import-folder", response_model=ImportLocalFolderResponse, status_code=201)
async def import_local_folder(
    collection_id: str,
    body: ImportLocalFolderRequest,
    session: AsyncSession = Depends(get_session),
    import_service: ImportSessionService = Depends(get_import_session_service),
) -> ImportLocalFolderResponse:
    normalized_collection_path = _normalize_collection_path(body.collection_path)

    audit = PipelineAuditService(session=session)
    async with audit.step(
        run_id=new_id(),
        entity_type="collection",
        entity_id=collection_id,
        pipeline="ingestion",
        stage="register_local_folder",
        context={
            "source_folder": body.source_folder,
            "collection_path": normalized_collection_path,
            "recursive": body.recursive,
        },
    ) as step:
        try:
            import_session, documents = await import_service.import_local_folder(
                collection_id=collection_id,
                source_folder=body.source_folder,
                collection_path=normalized_collection_path,
                recursive=body.recursive,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        step.metrics(
            source_folder=body.source_folder,
            collection_path=normalized_collection_path,
            imported=len(documents),
            import_session_id=import_session.id,
            discovered_count=import_session.discovered_count,
            created_count=import_session.created_count,
            deduplicated_count=import_session.deduplicated_count,
            failed_count=import_session.failed_count,
        )

        return ImportLocalFolderResponse(
            imported=len(documents),
            source_folder=body.source_folder,
            collection_path=normalized_collection_path,
            document_ids=[document.id for document in documents],
            import_session_id=import_session.id,
            discovered_count=import_session.discovered_count,
            created_count=import_session.created_count,
            deduplicated_count=import_session.deduplicated_count,
            failed_count=import_session.failed_count,
        )
