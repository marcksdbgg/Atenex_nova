"""Atenex Nova — Dependency injection container."""

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.answer_service import AnswerService
from atenex_nova.application.services.collection_service import CollectionService
from atenex_nova.application.services.document_read_service import DocumentReadService
from atenex_nova.application.services.document_service import DocumentService
from atenex_nova.application.services.evaluation_service import EvaluationService
from atenex_nova.application.services.import_session_service import ImportSessionService
from atenex_nova.application.services.job_service import JobService
from atenex_nova.application.services.query_service import QueryService
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_document_repo import SqlDocumentRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.infrastructure.files.blob_store import BlobStore
from atenex_nova.shared.config.settings import get_settings


def get_blob_store() -> BlobStore:
    settings = get_settings()
    return BlobStore(settings.blob_store_path)


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


async def get_import_session_service(
    session: AsyncSession = Depends(get_session),
    doc_service: DocumentService = Depends(get_document_service),
) -> ImportSessionService:
    return ImportSessionService(session, doc_service)


async def get_document_read_service(
    session: AsyncSession = Depends(get_session),
) -> DocumentReadService:
    return DocumentReadService(session)


async def get_job_service(
    session: AsyncSession = Depends(get_session),
) -> JobService:
    return JobService(SqlJobRepository(session))


async def get_query_service(
    session: AsyncSession = Depends(get_session),
) -> QueryService:
    return QueryService(session)


async def get_answer_service(
    session: AsyncSession = Depends(get_session),
) -> AnswerService:
    return AnswerService(session)


async def get_evaluation_service(
    session: AsyncSession = Depends(get_session),
) -> EvaluationService:
    return EvaluationService(session)
