"""Atenex Nova — Domain entity: Job."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from atenex_nova.domain.value_objects.identifiers import JobStatus, JobType


@dataclass
class Job:
    """Background processing job.

    Jobs orchestrate async processing steps like parsing, embedding, indexing.
    Each job tracks its type, target entity, status, and result/error.
    """

    id: str
    job_type: JobType
    target_id: str
    status: JobStatus = JobStatus.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def start(self) -> None:
        """Mark job as running."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def succeed(self, result: dict[str, Any] | None = None) -> None:
        """Mark job as succeeded."""
        self.status = JobStatus.SUCCEEDED
        self.result = result
        self.completed_at = datetime.now(UTC)

    def fail(self, error: str) -> None:
        """Mark job as failed."""
        self.retries += 1
        if self.retries >= self.max_retries:
            self.status = JobStatus.FAILED
        else:
            self.status = JobStatus.PENDING  # will be retried
        self.error = error
        self.completed_at = datetime.now(UTC)

    def cancel(self) -> None:
        """Cancel the job."""
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.now(UTC)

    @property
    def is_terminal(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}

    @property
    def can_retry(self) -> bool:
        """Check if job can be retried."""
        return self.retries < self.max_retries
