"""SQL repository: Job."""

import json

from sqlalchemy import func, select
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
        r = await self._session.execute(
            select(JobModel)
            .where(JobModel.status == "pending")
            .order_by(JobModel.created_at.asc())
            .limit(1)
        )
        model = r.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def count_by_status(self) -> dict[JobStatus, int]:
        r = await self._session.execute(
            select(JobModel.status, func.count()).group_by(JobModel.status)
        )
        return {JobStatus(row[0]): row[1] for row in r.all()}

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
