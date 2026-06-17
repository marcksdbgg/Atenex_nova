"""SQL repository: import sessions and items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.infrastructure.db.models.tables import ImportSessionItemModel, ImportSessionModel


@dataclass
class ImportSessionRecord:
    id: str
    collection_id: str
    source_kind: str
    source_root: str
    collection_path: str
    status: str
    discovered_count: int
    attempted_count: int
    created_count: int
    deduplicated_count: int
    skipped_count: int
    failed_count: int
    queued_jobs_count: int
    started_at: datetime
    completed_at: datetime | None
    error: str | None


@dataclass
class ImportSessionItemRecord:
    id: str
    session_id: str
    relative_path: str
    source_path: str
    checksum: str | None
    mime_type: str | None
    status: str
    document_id: str | None
    job_id: str | None
    error: str | None
    created_at: datetime


class SqlImportSessionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_session(
        self,
        collection_id: str,
        source_kind: str,
        source_root: str = "",
        collection_path: str = "",
        discovered_count: int = 0,
    ) -> ImportSessionRecord:
        model = ImportSessionModel(
            id=new_id(),
            collection_id=collection_id,
            source_kind=source_kind,
            source_root=source_root,
            collection_path=collection_path,
            status="running",
            discovered_count=discovered_count,
        )
        self._session.add(model)
        await self._session.flush()
        return self._session_to_record(model)

    async def get_session(self, session_id: str) -> ImportSessionRecord | None:
        result = await self._session.execute(
            select(ImportSessionModel).where(ImportSessionModel.id == session_id)
        )
        model = result.scalar_one_or_none()
        return self._session_to_record(model) if model else None

    async def list_by_collection(
        self,
        collection_id: str,
        offset: int = 0,
        limit: int = 20,
    ) -> list[ImportSessionRecord]:
        result = await self._session.execute(
            select(ImportSessionModel)
            .where(ImportSessionModel.collection_id == collection_id)
            .order_by(ImportSessionModel.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return [self._session_to_record(model) for model in result.scalars().all()]

    async def add_item(
        self,
        session_id: str,
        *,
        relative_path: str,
        source_path: str,
        status: str,
        checksum: str | None = None,
        mime_type: str | None = None,
        document_id: str | None = None,
        job_id: str | None = None,
        error: str | None = None,
    ) -> ImportSessionItemRecord:
        model = ImportSessionItemModel(
            id=new_id(),
            session_id=session_id,
            relative_path=relative_path,
            source_path=source_path,
            checksum=checksum,
            mime_type=mime_type,
            status=status,
            document_id=document_id,
            job_id=job_id,
            error=error,
        )
        self._session.add(model)
        await self._session.flush()
        return self._item_to_record(model)

    async def list_items(
        self,
        session_id: str,
        offset: int = 0,
        limit: int = 100,
        status: str | None = None,
    ) -> list[ImportSessionItemRecord]:
        stmt = select(ImportSessionItemModel).where(ImportSessionItemModel.session_id == session_id)
        if status:
            stmt = stmt.where(ImportSessionItemModel.status == status)
        stmt = stmt.order_by(ImportSessionItemModel.created_at.asc()).offset(offset).limit(limit)
        result = await self._session.execute(stmt)
        return [self._item_to_record(model) for model in result.scalars().all()]

    async def increment_counters(
        self,
        session_id: str,
        *,
        attempted: int = 0,
        created: int = 0,
        deduplicated: int = 0,
        skipped: int = 0,
        failed: int = 0,
        queued_jobs: int = 0,
    ) -> None:
        result = await self._session.execute(
            select(ImportSessionModel).where(ImportSessionModel.id == session_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.attempted_count += attempted
        model.created_count += created
        model.deduplicated_count += deduplicated
        model.skipped_count += skipped
        model.failed_count += failed
        model.queued_jobs_count += queued_jobs
        await self._session.flush()

    async def finalize_session(self, session_id: str, error: str | None = None) -> ImportSessionRecord | None:
        result = await self._session.execute(
            select(ImportSessionModel).where(ImportSessionModel.id == session_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return None
        if error:
            model.status = "failed"
            model.error = error
        elif model.failed_count > 0:
            model.status = "completed_with_errors"
        else:
            model.status = "completed"
        model.completed_at = datetime.now(UTC)
        await self._session.flush()
        return self._session_to_record(model)

    async def delete_by_collection(self, collection_id: str) -> int:
        session_ids_result = await self._session.execute(
            select(ImportSessionModel.id).where(ImportSessionModel.collection_id == collection_id)
        )
        session_ids = [str(row[0]) for row in session_ids_result.all()]
        if not session_ids:
            return 0
        await self._session.execute(
            delete(ImportSessionItemModel).where(ImportSessionItemModel.session_id.in_(session_ids))
        )
        result = await self._session.execute(
            delete(ImportSessionModel).where(ImportSessionModel.id.in_(session_ids))
        )
        return int(result.rowcount or 0)

    async def count_items(self, session_id: str) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(ImportSessionItemModel)
            .where(ImportSessionItemModel.session_id == session_id)
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    def _session_to_record(model: ImportSessionModel) -> ImportSessionRecord:
        return ImportSessionRecord(
            id=model.id,
            collection_id=model.collection_id,
            source_kind=model.source_kind,
            source_root=model.source_root,
            collection_path=model.collection_path,
            status=model.status,
            discovered_count=model.discovered_count,
            attempted_count=model.attempted_count,
            created_count=model.created_count,
            deduplicated_count=model.deduplicated_count,
            skipped_count=model.skipped_count,
            failed_count=model.failed_count,
            queued_jobs_count=model.queued_jobs_count,
            started_at=model.started_at,
            completed_at=model.completed_at,
            error=model.error,
        )

    @staticmethod
    def _item_to_record(model: ImportSessionItemModel) -> ImportSessionItemRecord:
        return ImportSessionItemRecord(
            id=model.id,
            session_id=model.session_id,
            relative_path=model.relative_path,
            source_path=model.source_path,
            checksum=model.checksum,
            mime_type=model.mime_type,
            status=model.status,
            document_id=model.document_id,
            job_id=model.job_id,
            error=model.error,
            created_at=model.created_at,
        )
