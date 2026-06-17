"""SQL repository: Job."""

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.job import Job
from atenex_nova.domain.value_objects.identifiers import JobStatus, JobType
from atenex_nova.infrastructure.db.models.tables import JobModel


class SqlJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, job: Job) -> Job:
        m = JobModel(
            id=job.id,
            job_type=job.job_type.value,
            target_id=job.target_id,
            status=job.status.value,
            payload_json=json.dumps(job.payload),
            retries=job.retries,
            max_retries=job.max_retries,
            created_at=job.created_at,
        )
        self._session.add(m)
        await self._session.flush()
        return job

    async def get_by_id(self, job_id: str) -> Job | None:
        r = await self._session.execute(select(JobModel).where(JobModel.id == job_id))
        model = r.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_all(
        self,
        offset: int = 0,
        limit: int = 50,
        status: JobStatus | None = None,
        job_type: JobType | None = None,
    ) -> list[Job]:
        stmt = select(JobModel)
        if status:
            stmt = stmt.where(JobModel.status == status.value)
        if job_type:
            stmt = stmt.where(JobModel.job_type == job_type.value)
        stmt = stmt.offset(offset).limit(limit).order_by(JobModel.created_at.desc())
        r = await self._session.execute(stmt)
        return [self._to_entity(m) for m in r.scalars().all()]

    async def list_by_target(self, target_id: str, limit: int = 50) -> list[Job]:
        r = await self._session.execute(
            select(JobModel)
            .where(JobModel.target_id == target_id)
            .order_by(JobModel.created_at.desc())
            .limit(limit)
        )
        return [self._to_entity(m) for m in r.scalars().all()]

    async def delete_pending_by_targets(self, target_ids: list[str], exclude_job_id: str | None = None) -> int:
        if not target_ids:
            return 0

        stmt = delete(JobModel).where(JobModel.status == JobStatus.PENDING.value, JobModel.target_id.in_(target_ids))
        if exclude_job_id is not None:
            stmt = stmt.where(JobModel.id != exclude_job_id)
        result = await self._session.execute(stmt)
        return int(result.rowcount or 0)

    async def update(self, job: Job) -> Job:
        r = await self._session.execute(select(JobModel).where(JobModel.id == job.id))
        model = r.scalar_one_or_none()
        if model:
            model.status = job.status.value
            model.result_json = json.dumps(job.result) if job.result else None
            model.error = job.error
            model.retries = job.retries
            model.started_at = job.started_at
            model.completed_at = job.completed_at
            await self._session.flush()
        return job

    async def get_next_pending(self) -> Job | None:
        return await self.claim_next_pending()

    async def claim_next_pending(self) -> Job | None:
        """Atomically claim the oldest pending job."""
        pick = await self._session.execute(
            select(JobModel.id)
            .where(JobModel.status == JobStatus.PENDING.value)
            .order_by(JobModel.created_at.asc())
            .limit(1)
        )
        job_id = pick.scalar_one_or_none()
        if job_id is None:
            return None

        now = datetime.now(UTC)
        claim = await self._session.execute(
            update(JobModel)
            .where(
                JobModel.id == job_id,
                JobModel.status == JobStatus.PENDING.value,
            )
            .values(status=JobStatus.RUNNING.value, started_at=now, error=None)
        )
        if int(claim.rowcount or 0) == 0:
            return None
        await self._session.flush()
        return await self.get_by_id(job_id)

    async def requeue_stale_running(self, stale_after_minutes: int = 10) -> int:
        cutoff = datetime.now(UTC) - timedelta(minutes=max(1, stale_after_minutes))
        result = await self._session.execute(
            select(JobModel).where(
                JobModel.status == JobStatus.RUNNING.value,
                JobModel.started_at.is_not(None),
                JobModel.started_at < cutoff,
            )
        )
        stale_jobs = result.scalars().all()
        for model in stale_jobs:
            model.status = JobStatus.PENDING.value
            model.error = "Recovered stale running job"
            model.started_at = None
            model.completed_at = None
        await self._session.flush()
        return len(stale_jobs)

    async def count_by_status(self) -> dict[JobStatus, int]:
        r = await self._session.execute(
            select(JobModel.status, func.count()).group_by(JobModel.status)
        )
        return {JobStatus(row[0]): row[1] for row in r.all()}

    async def count_by_status_for_targets(self, target_ids: list[str]) -> dict[str, int]:
        if not target_ids:
            return {}
        r = await self._session.execute(
            select(JobModel.status, func.count())
            .where(JobModel.target_id.in_(target_ids))
            .group_by(JobModel.status)
        )
        return {str(row[0]): int(row[1]) for row in r.all()}

    async def count_by_type_and_status_for_targets(
        self,
        target_ids: list[str],
    ) -> dict[str, dict[str, int]]:
        if not target_ids:
            return {}
        r = await self._session.execute(
            select(JobModel.job_type, JobModel.status, func.count())
            .where(JobModel.target_id.in_(target_ids))
            .group_by(JobModel.job_type, JobModel.status)
        )
        result: dict[str, dict[str, int]] = {}
        for job_type, status, count in r.all():
            bucket = result.setdefault(str(job_type), {})
            bucket[str(status)] = int(count)
        return result

    @staticmethod
    def _to_entity(m: JobModel) -> Job:
        return Job(
            id=m.id,
            job_type=JobType(m.job_type),
            target_id=m.target_id,
            status=JobStatus(m.status),
            payload=json.loads(m.payload_json) if m.payload_json else {},
            result=json.loads(m.result_json) if m.result_json else None,
            error=m.error,
            retries=m.retries,
            max_retries=m.max_retries,
            created_at=m.created_at,
            started_at=m.started_at,
            completed_at=m.completed_at,
        )
