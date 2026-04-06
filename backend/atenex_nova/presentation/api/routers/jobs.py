"""Jobs router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.infrastructure.db.repositories.sql_job_repo import SqlJobRepository
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.presentation.api.dto.schemas import JobResponse

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    offset: int = 0,
    limit: int = 50,
    session: AsyncSession = Depends(get_session),
) -> list[JobResponse]:
    repo = SqlJobRepository(session)
    jobs = await repo.list_all(offset=offset, limit=limit)
    return [
        JobResponse(
            id=j.id,
            job_type=j.job_type.value,
            target_id=j.target_id,
            status=j.status.value,
            error=j.error,
            retries=j.retries,
            created_at=j.created_at,
            started_at=j.started_at,
            completed_at=j.completed_at,
        )
        for j in jobs
    ]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(
    job_id: str,
    session: AsyncSession = Depends(get_session),
) -> JobResponse:
    repo = SqlJobRepository(session)
    job = await repo.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobResponse(
        id=job.id,
        job_type=job.job_type.value,
        target_id=job.target_id,
        status=job.status.value,
        error=job.error,
        retries=job.retries,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )
