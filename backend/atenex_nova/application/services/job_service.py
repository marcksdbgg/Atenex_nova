"""Application service: Job management."""

from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.repositories.job_repository import JobRepository
from atenex_nova.domain.value_objects.identifiers import JobStatus, JobType
from atenex_nova.shared.exceptions.base import EntityNotFoundError


class JobService:
    def __init__(self, repo: JobRepository) -> None:
        self._repo = repo

    async def get(self, job_id: str) -> Job:
        job = await self._repo.get_by_id(job_id)
        if not job:
            raise EntityNotFoundError("Job", job_id)
        return job

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        status: JobStatus | None = None,
        job_type: JobType | None = None,
    ) -> list[Job]:
        return await self._repo.list_all(offset, limit, status, job_type)

    async def get_stats(self) -> dict[JobStatus, int]:
        return await self._repo.count_by_status()

    async def cancel(self, job_id: str) -> Job:
        job = await self.get(job_id)
        job.cancel()
        await self._repo.update(job)
        return job
