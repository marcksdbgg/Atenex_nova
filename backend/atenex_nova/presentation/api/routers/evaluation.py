"""Evaluation API router."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.evaluation_service import EvaluationService
from atenex_nova.infrastructure.db.session import get_session
from atenex_nova.presentation.api.dto.schemas import (
    EvaluationCaseResponse,
    EvaluationReportResponse,
    EvaluationRunRequest,
    EvaluationRunResponse,
)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/datasets", response_model=list[str])
async def list_datasets(session: AsyncSession = Depends(get_session)) -> list[str]:
    return EvaluationService(session).list_datasets()


@router.post("/runs", response_model=EvaluationReportResponse)
async def run_evaluation(
    body: EvaluationRunRequest,
    session: AsyncSession = Depends(get_session),
) -> EvaluationReportResponse:
    service = EvaluationService(session)
    try:
        report = await service.run(collection_id=body.collection_id, dataset_name=body.dataset_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EvaluationReportResponse.from_report(report)


@router.get("/runs", response_model=list[EvaluationRunResponse])
async def list_runs(session: AsyncSession = Depends(get_session)) -> list[EvaluationRunResponse]:
    service = EvaluationService(session)
    return [EvaluationRunResponse.from_run(run) for run in await service.list_runs()]


@router.get("/runs/{run_id}", response_model=EvaluationReportResponse)
async def get_run(run_id: str, session: AsyncSession = Depends(get_session)) -> EvaluationReportResponse:
    service = EvaluationService(session)
    report = await service.get_run(run_id)
    if report is None:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return EvaluationReportResponse.from_report(report)


@router.get("/reports/{run_id}", response_model=EvaluationReportResponse)
async def get_report(run_id: str, session: AsyncSession = Depends(get_session)) -> EvaluationReportResponse:
    return await get_run(run_id, session)