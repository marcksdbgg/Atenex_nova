"""SQL repository: Answer."""

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.domain.entities.answer import Answer
from atenex_nova.infrastructure.db.models.tables import AnswerModel


class SqlAnswerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, answer: Answer) -> Answer:
        model = AnswerModel(
            id=answer.id,
            query_id=answer.query_id,
            plan_type=answer.plan_type,
            text=answer.text,
            grounding_score=answer.grounding_score,
            verdict=answer.verdict,
            prompt_version=answer.prompt_version,
            draft_text=answer.draft_text,
            verification_issues_json=json.dumps(answer.verification_issues),
            evidence_trace_json=json.dumps(answer.evidence_trace),
            created_at=answer.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return answer

    async def get_by_id(self, answer_id: str) -> Answer | None:
        result = await self._session.execute(select(AnswerModel).where(AnswerModel.id == answer_id))
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Answer(
            id=model.id,
            query_id=model.query_id,
            plan_type=model.plan_type,
            text=model.text,
            grounding_score=model.grounding_score,
            verdict=model.verdict,
            prompt_version=model.prompt_version,
            draft_text=model.draft_text,
            verification_issues=json.loads(model.verification_issues_json) if model.verification_issues_json else [],
            evidence_trace=json.loads(model.evidence_trace_json) if model.evidence_trace_json else {},
            created_at=model.created_at,
        )

    async def get_by_query_id(self, query_id: str) -> Answer | None:
        result = await self._session.execute(select(AnswerModel).where(AnswerModel.query_id == query_id))
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return Answer(
            id=model.id,
            query_id=model.query_id,
            plan_type=model.plan_type,
            text=model.text,
            grounding_score=model.grounding_score,
            verdict=model.verdict,
            prompt_version=model.prompt_version,
            draft_text=model.draft_text,
            verification_issues=json.loads(model.verification_issues_json) if model.verification_issues_json else [],
            evidence_trace=json.loads(model.evidence_trace_json) if model.evidence_trace_json else {},
            created_at=model.created_at,
        )
