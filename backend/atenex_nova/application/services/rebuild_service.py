"""Collection rebuild service."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobType, new_id
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository


class RebuildService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._collection_repo = SqlCollectionRepository(session)
        self._job_repo = SqlJobRepository(session)

    async def enqueue(self, collection_id: str) -> str:
        collection = await self._collection_repo.get_by_id(collection_id)
        if collection is None:
            raise ValueError("Collection not found")
        job_id = new_id()
        await self._job_repo.create(Job(id=job_id, job_type=JobType.REBUILD_COLLECTION, target_id=collection_id))
        return job_id