"""Pipeline observability helpers for audit events and metrics."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atenex_nova.infrastructure.db.repositories.sql_pipeline_audit_repo import SqlPipelineAuditRepository
from atenex_nova.domain.value_objects.identifiers import new_id

logger = logging.getLogger("atenex_nova.pipeline.audit")


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@dataclass(slots=True)
class PipelineAuditEvent:
    id: str
    run_id: str
    entity_type: str
    entity_id: str
    pipeline: str
    stage: str
    status: str
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: float | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


class PipelineStageRecorder:
    def __init__(
        self,
        service: "PipelineAuditService",
        *,
        run_id: str,
        entity_type: str,
        entity_id: str,
        pipeline: str,
        stage: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        self._service = service
        self._event = PipelineAuditEvent(
            id=new_id(),
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            pipeline=pipeline,
            stage=stage,
            status="started",
            context=context or {},
        )
        self._started = perf_counter()

    def metric(self, name: str, value: Any) -> None:
        self._event.metrics[name] = _json_safe(value)

    def metrics(self, **values: Any) -> None:
        for name, value in values.items():
            self.metric(name, value)

    async def __aenter__(self) -> "PipelineStageRecorder":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._event.completed_at = datetime.now(UTC)
        self._event.duration_ms = round((perf_counter() - self._started) * 1000, 2)
        if exc is None:
            self._event.status = "succeeded"
        else:
            self._event.status = "failed"
            self._event.metrics["error"] = _json_safe(str(exc))
        await self._service.record(self._event)
        return False


class PipelineAuditService:
    def __init__(
        self,
        session: AsyncSession | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session = session
        self._session_factory = session_factory

    def step(
        self,
        *,
        run_id: str,
        entity_type: str,
        entity_id: str,
        pipeline: str,
        stage: str,
        context: dict[str, Any] | None = None,
    ) -> PipelineStageRecorder:
        return PipelineStageRecorder(
            self,
            run_id=run_id,
            entity_type=entity_type,
            entity_id=entity_id,
            pipeline=pipeline,
            stage=stage,
            context=context,
        )

    async def record(self, event: PipelineAuditEvent) -> None:
        payload = {
            "id": event.id,
            "run_id": event.run_id,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "pipeline": event.pipeline,
            "stage": event.stage,
            "status": event.status,
            "started_at": event.started_at,
            "completed_at": event.completed_at,
            "duration_ms": event.duration_ms,
            "metrics_json": json.dumps(_json_safe(event.metrics), ensure_ascii=False),
            "context_json": json.dumps(_json_safe(event.context), ensure_ascii=False),
        }
        logger.info(
            "audit pipeline=%s stage=%s status=%s entity=%s/%s duration_ms=%s metrics=%s",
            event.pipeline,
            event.stage,
            event.status,
            event.entity_type,
            event.entity_id,
            event.duration_ms,
            payload["metrics_json"],
        )
        if self._session_factory is not None:
            async with self._session_factory() as session:
                repo = SqlPipelineAuditRepository(session)
                await repo.create(**payload)
                await session.commit()
            return

        if self._session is None:
            raise RuntimeError("PipelineAuditService requires a session or session_factory")

        repo = SqlPipelineAuditRepository(self._session)
        await repo.create(**payload)
