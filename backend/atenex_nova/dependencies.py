"""Atenex Nova — Dependency injection container."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.collection_service import CollectionService
from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.application.services.job_service import JobService
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.files.blob_store import BlobStore


def get_blob_store() -> BlobStore:
    return BlobStore()


async def get_collection_service(
    session: AsyncSession = Depends(get_session),
) -> CollectionService:
    return CollectionService(SqlCollectionRepository(session))


async def get_document_service(
    session: AsyncSession = Depends(get_session),
) -> DocumentService:
    return DocumentService(
        doc_repo=SqlDocumentRepository(session),
        job_repo=SqlJobRepository(session),
    )


async def get_job_service(
    session: AsyncSession = Depends(get_session),
) -> JobService:
    return JobService(SqlJobRepository(session))
