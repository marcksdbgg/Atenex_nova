"""Explicit scheduling boundary for collection-level memory synthesis."""

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.value_objects.identifiers import JobType
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository


class CollectionMemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._collection_repo = SqlCollectionRepository(session)
        self._job_repo = SqlJobRepository(session)

    async def enqueue(self, collection_id: str, *, batch_size: int = 32) -> tuple[str, bool]:
        if batch_size < 2 or batch_size > 128:
            raise ValueError("batch_size must be between 2 and 128")
        if await self._collection_repo.get_by_id(collection_id) is None:
            raise ValueError("Collection not found")
        job, created = await self._job_repo.ensure_pending(
            job_type=JobType.BUILD_COLLECTION_MEMORY,
            target_id=collection_id,
            payload={"batch_size": batch_size},
        )
        return job.id, created
