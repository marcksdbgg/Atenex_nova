"""SQL repositories for evaluation runs and cases."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.evaluation.models import EvaluationCaseResult, EvaluationRun
from atenex_nova.infrastructure.db.models.tables import EvaluationCaseModel, EvaluationRunModel


class SqlEvaluationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, run: EvaluationRun) -> EvaluationRun:
        model = EvaluationRunModel(
            id=run.id,
            dataset_name=run.dataset_name,
            collection_id=run.collection_id,
            retrieval_recall_at_k=run.retrieval_recall_at_k,
            retrieval_mrr=run.retrieval_mrr,
            retrieval_ndcg=run.retrieval_ndcg,
            answer_grounding_score=run.answer_grounding_score,
            answer_relevance_score=run.answer_relevance_score,
            regression_delta_json=json.dumps(run.regression_delta),
            summary_json=json.dumps(run.summary),
            created_at=run.created_at,
        )
        self._session.add(model)
        await self._session.flush()
        return run

    async def get_by_id(self, run_id: str) -> EvaluationRun | None:
        result = await self._session.execute(select(EvaluationRunModel).where(EvaluationRunModel.id == run_id))
        model = result.scalar_one_or_none()
        if model is None:
            return None
        return EvaluationRun(
            id=model.id,
            dataset_name=model.dataset_name,
            collection_id=model.collection_id,
            retrieval_recall_at_k=model.retrieval_recall_at_k,
            retrieval_mrr=model.retrieval_mrr,
            retrieval_ndcg=model.retrieval_ndcg,
            answer_grounding_score=model.answer_grounding_score,
            answer_relevance_score=model.answer_relevance_score,
            regression_delta=json.loads(model.regression_delta_json),
            summary=json.loads(model.summary_json),
            created_at=model.created_at,
        )

    async def list_all(self, limit: int = 20) -> list[EvaluationRun]:
        result = await self._session.execute(select(EvaluationRunModel).order_by(EvaluationRunModel.created_at.desc()).limit(limit))
        return [
            EvaluationRun(
                id=model.id,
                dataset_name=model.dataset_name,
                collection_id=model.collection_id,
                retrieval_recall_at_k=model.retrieval_recall_at_k,
                retrieval_mrr=model.retrieval_mrr,
                retrieval_ndcg=model.retrieval_ndcg,
                answer_grounding_score=model.answer_grounding_score,
                answer_relevance_score=model.answer_relevance_score,
                regression_delta=json.loads(model.regression_delta_json),
                summary=json.loads(model.summary_json),
                created_at=model.created_at,
            )
            for model in result.scalars().all()
        ]


class SqlEvaluationCaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_many(self, cases: list[EvaluationCaseResult], run_id: str) -> list[EvaluationCaseResult]:
        models = [
            EvaluationCaseModel(
                id=case.id,
                run_id=run_id,
                category=case.category,
                question=case.question,
                expected_answer=case.expected_answer,
                expected_keywords_json=json.dumps(case.expected_keywords),
                route_mode=case.route_mode,
                retrieval_metrics_json=json.dumps(case.retrieval_metrics),
                answer_metrics_json=json.dumps(case.answer_metrics),
                retrieved_json=json.dumps(case.retrieved),
                answer_id=case.answer_id,
            )
            for case in cases
        ]
        self._session.add_all(models)
        await self._session.flush()
        return cases

    async def list_by_run(self, run_id: str) -> list[EvaluationCaseResult]:
        result = await self._session.execute(select(EvaluationCaseModel).where(EvaluationCaseModel.run_id == run_id))
        return [
            EvaluationCaseResult(
                id=model.id,
                category=model.category,
                question=model.question,
                expected_answer=model.expected_answer,
                expected_keywords=json.loads(model.expected_keywords_json),
                route_mode=model.route_mode,
                retrieval_metrics=json.loads(model.retrieval_metrics_json),
                answer_metrics=json.loads(model.answer_metrics_json),
                retrieved=json.loads(model.retrieved_json),
                answer_id=model.answer_id,
            )
            for model in result.scalars().all()
        ]
