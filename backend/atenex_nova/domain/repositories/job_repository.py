"""Atenex Nova — Domain repository interface: JobRepository."""

from typing import Protocol

from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobStatus, JobType


class JobRepository(Protocol):
    """Interface for job persistence operations."""

    async def create(self, job: Job) -> Job:
        """Persist a new job."""
        ...

    async def get_by_id(self, job_id: str) -> Job | None:
        """Get a job by its ID."""
        ...

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        status: JobStatus | None = None,
        job_type: JobType | None = None,
    ) -> list[Job]:
        """List jobs with optional filters."""
        ...

    async def update(self, job: Job) -> Job:
        """Update an existing job."""
        ...

    async def get_next_pending(self) -> Job | None:
        """Get the next pending job for processing (FIFO)."""
        ...

    async def count_by_status(self) -> dict[JobStatus, int]:
        """Get job counts grouped by status."""
        ...
