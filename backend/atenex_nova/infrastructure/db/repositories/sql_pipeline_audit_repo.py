"""SQL repository for pipeline audit events."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.infrastructure.db.models.tables import PipelineAuditModel


class SqlPipelineAuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        id: str,
        run_id: str,
        entity_type: str,
        entity_id: str,
        pipeline: str,
        stage: str,
        status: str,
        started_at,
        completed_at,
        duration_ms,
        metrics_json: str,
        context_json: str,
    ) -> None:
        model = PipelineAuditModel(
            id=id,
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            pipeline=pipeline,
            stage=stage,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            metrics_json=metrics_json,
            context_json=context_json,
        )
        self._session.add(model)
        await self._session.flush()

    async def list_by_entity(self, entity_type: str, entity_id: str, limit: int = 50) -> list[dict]:
        result = await self._session.execute(
            select(PipelineAuditModel)
            .where(PipelineAuditModel.entity_type == entity_type)
            .where(PipelineAuditModel.entity_id == entity_id)
            .order_by(PipelineAuditModel.started_at.desc())
            .limit(limit)
        )
        return [self._to_dict(model) for model in result.scalars().all()]

    async def list_by_run(self, run_id: str, limit: int = 50) -> list[dict]:
        result = await self._session.execute(
            select(PipelineAuditModel)
            .where(PipelineAuditModel.run_id == run_id)
            .order_by(PipelineAuditModel.started_at.asc())
            .limit(limit)
        )
        return [self._to_dict(model) for model in result.scalars().all()]

    async def list_recent(self, limit: int = 50) -> list[dict]:
        result = await self._session.execute(
            select(PipelineAuditModel).order_by(PipelineAuditModel.started_at.desc()).limit(limit)
        )
        return [self._to_dict(model) for model in result.scalars().all()]

    @staticmethod
    def _to_dict(model: PipelineAuditModel) -> dict:
        return {
            "id": model.id,
            "run_id": model.run_id,
            "entity_type": model.entity_type,
            "entity_id": model.entity_id,
            "pipeline": model.pipeline,
            "stage": model.stage,
            "status": model.status,
            "started_at": model.started_at,
            "completed_at": model.completed_at,
            "duration_ms": model.duration_ms,
            "metrics": json.loads(model.metrics_json or "{}"),
            "context": json.loads(model.context_json or "{}"),
        }
