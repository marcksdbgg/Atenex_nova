"""Collections router."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.application.services.rebuild_service import RebuildService
from atenex_nova.dependencies import get_blob_store, get_document_service
from atenex_nova.domain.entities.collection import Collection
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.files.blob_store import BlobStore
from atenex_nova.shared.observability.pipeline_audit import PipelineAuditService
from atenex_nova.presentation.api.dto.schemas import (
    CollectionResponse,
    CreateCollectionRequest,
    DocumentResponse,
    ImportLocalDocumentRequest,
    UpdateCollectionRequest,
)

router = APIRouter(prefix="/collections", tags=["collections"])


@router.post("", response_model=CollectionResponse, status_code=201)
async def create_collection(
    body: CreateCollectionRequest,
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    repo = SqlCollectionRepository(session)
    entity = Collection(
        id=new_id(),
        name=body.name,
        description=body.description,
        language_profile=body.language_profile,
    )
    await repo.create(entity)
    return CollectionResponse(**entity.__dict__)


@router.get("", response_model=list[CollectionResponse])
async def list_collections(
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[CollectionResponse]:
    repo = SqlCollectionRepository(session)
    items = await repo.list_all(offset=offset, limit=limit)
    return [CollectionResponse(**c.__dict__) for c in items]


@router.get("/{collection_id}", response_model=CollectionResponse)
async def get_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    repo = SqlCollectionRepository(session)
    entity = await repo.get_by_id(collection_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Collection not found")
    return CollectionResponse(**entity.__dict__)


@router.patch("/{collection_id}", response_model=CollectionResponse)
async def update_collection(
    collection_id: str,
    body: UpdateCollectionRequest,
    session: AsyncSession = Depends(get_session),
) -> CollectionResponse:
    repo = SqlCollectionRepository(session)
    entity = await repo.get_by_id(collection_id)
    if not entity:
        raise HTTPException(status_code=404, detail="Collection not found")
    if body.name is not None:
        entity.rename(body.name)
    if body.description is not None:
        entity.description = body.description
    entity.update_profiles(body.generation_profile, body.retrieval_profile)
    await repo.update(entity)
    return CollectionResponse(**entity.__dict__)


@router.delete("/{collection_id}", status_code=204)
async def delete_collection(
    collection_id: str,
    session: AsyncSession = Depends(get_session),
) -> None:
    repo = SqlCollectionRepository(session)
    deleted = await repo.delete(collection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Collection not found")


@router.get("/{collection_id}/documents", response_model=list[DocumentResponse])
async def list_collection_documents(
    collection_id: str,
    doc_service: DocumentService = Depends(get_document_service),
) -> list[DocumentResponse]:
    items = await doc_service.list_by_collection(collection_id)
    return [
        DocumentResponse(
            id=item.id,
            collection_id=item.collection_id,
            title=item.title,
            mime_type=item.mime_type,
            source_path=item.source_path,
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
    session: AsyncSession = Depends(get_session),
    doc_service: DocumentService = Depends(get_document_service),
    blob_store: BlobStore = Depends(get_blob_store),
) -> DocumentResponse:
    audit = PipelineAuditService(session=session)
    async with audit.step(
        run_id=new_id(),
        entity_type="collection",
        entity_id=collection_id,
        pipeline="ingestion",
        stage="register_upload",
        context={"filename": file.filename, "mime_type": file.content_type},
    ) as step:
        data = await file.read()
        checksum = BlobStore.compute_checksum(data)
        doc_id = new_id()
        path = blob_store.store(collection_id, doc_id, file.filename or "unknown", data)
        doc = await doc_service.register(
            collection_id=collection_id,
            title=file.filename or "unknown",
            source_path=str(path),
            mime_type=file.content_type or "application/octet-stream",
            checksum=checksum,
            doc_id=doc_id,
        )
        step.metrics(bytes=len(data), checksum=checksum, source_path=str(path), document_id=doc.id)

        return DocumentResponse(
            id=doc.id,
            collection_id=doc.collection_id,
            title=doc.title,
            mime_type=doc.mime_type,
            source_path=doc.source_path,
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
        )
        step.metrics(source_path=doc.source_path, checksum=doc.checksum, document_id=doc.id)
        return DocumentResponse(
            id=doc.id,
            collection_id=doc.collection_id,
            title=doc.title,
            mime_type=doc.mime_type,
            source_path=doc.source_path,
            status=doc.status.value,
            language=doc.language,
            version=doc.version,
            error_message=doc.error_message,
            created_at=doc.created_at,
            updated_at=doc.updated_at,
        )
