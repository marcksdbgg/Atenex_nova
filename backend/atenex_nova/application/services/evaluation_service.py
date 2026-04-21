"""Application service for evaluation runs and reports."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from atenex_nova.application.services.answer_service import AnswerService
from atenex_nova.application.services.query_service import QueryService
from atenex_nova.domain.value_objects.identifiers import new_id
from atenex_nova.evaluation.datasets.manager import GoldenSetManager
from atenex_nova.evaluation.models import EvaluationCaseResult, EvaluationRun
from atenex_nova.evaluation.regression.comparator import RegressionComparator
from atenex_nova.evaluation.scorers.answer_scorer import AnswerScorer
from atenex_nova.evaluation.scorers.retrieval_scorer import RetrievalScorer
from atenex_nova.infrastructure.db.repositories.sql_collection_repo import SqlCollectionRepository
from atenex_nova.infrastructure.db.repositories.sql_evaluation_repo import (
    SqlEvaluationCaseRepository,
    SqlEvaluationRunRepository,
)


@dataclass(slots=True)
class EvaluationReport:
    run: EvaluationRun
    cases: list[EvaluationCaseResult]
    previous_run_id: str | None
    deltas: dict[str, float]


class EvaluationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._datasets = GoldenSetManager()
        self._retrieval_scorer = RetrievalScorer()
        self._answer_scorer = AnswerScorer()
        self._regression = RegressionComparator()
        self._query_service = QueryService(session)
        self._answer_service = AnswerService(session)
        self._run_repo = SqlEvaluationRunRepository(session)
        self._case_repo = SqlEvaluationCaseRepository(session)
        self._collection_repo = SqlCollectionRepository(session)

    def list_datasets(self) -> list[str]:
        return self._datasets.list_datasets()

    async def run(self, collection_id: str, dataset_name: str = "baseline") -> EvaluationReport:
        collection = await self._collection_repo.get_by_id(collection_id)
        if collection is None:
            raise ValueError("Collection not found")

        dataset = self._datasets.load(dataset_name)
        cases: list[EvaluationCaseResult] = []
        for case in dataset.cases:
            search_result = await self._query_service.search_only(collection_id=collection_id, query=case.question, mode=case.mode)
            retrieval_metrics = self._retrieval_scorer.score(
                [{"title": hit.title, "snippet": hit.snippet} for hit in search_result.hits],
                case.expected_keywords,
            )
            answer_bundle = await self._answer_service.answer(collection_id=collection_id, query=case.question, mode=case.mode)
            answer_metrics = self._answer_scorer.score(
                answer_bundle.answer.text,
                case.expected_answer,
                len(answer_bundle.citations),
                evidence_texts=[item.snippet for item in search_result.evidence_pack.items],
            )
            cases.append(
                EvaluationCaseResult(
                    id=case.id,
                    category=case.category,
                    question=case.question,
                    expected_answer=case.expected_answer,
                    expected_keywords=case.expected_keywords,
                    route_mode=answer_bundle.route_mode,
                    retrieval_metrics=retrieval_metrics,
                    answer_metrics=answer_metrics,
                    retrieved=[
                        {
                            "id": hit.id,
                            "title": hit.title,
                            "snippet": hit.snippet,
                            "score": hit.score,
                        }
                        for hit in search_result.hits
                    ],
                    answer_id=answer_bundle.answer.id,
                )
            )

        aggregate = self._aggregate(cases)
        previous = await self._previous_run(dataset_name, collection_id)
        deltas = self._regression.compare(previous.summary if previous else {}, aggregate)
        run = EvaluationRun(
            id=new_id(),
            dataset_name=dataset_name,
            collection_id=collection_id,
            retrieval_recall_at_k=aggregate["retrieval_recall_at_k"],
            retrieval_mrr=aggregate["retrieval_mrr"],
            retrieval_ndcg=aggregate["retrieval_ndcg"],
            answer_grounding_score=aggregate["answer_grounding_score"],
            answer_relevance_score=aggregate["answer_relevance_score"],
            regression_delta=deltas,
            summary=aggregate,
        )
        await self._run_repo.create(run)
        await self._case_repo.create_many(cases, run.id)
        await self._session.commit()
        return EvaluationReport(run=run, cases=cases, previous_run_id=previous.id if previous else None, deltas=deltas)

    async def get_run(self, run_id: str) -> EvaluationReport | None:
        run = await self._run_repo.get_by_id(run_id)
        if run is None:
            return None
        cases = await self._case_repo.list_by_run(run_id)
        previous = await self._previous_run(run.dataset_name, run.collection_id, exclude_run_id=run_id)
        deltas = self._regression.compare(previous.summary if previous else {}, run.summary)
        return EvaluationReport(run=run, cases=cases, previous_run_id=previous.id if previous else None, deltas=deltas)

    async def list_runs(self) -> list[EvaluationRun]:
        return await self._run_repo.list_all()

    async def _previous_run(self, dataset_name: str, collection_id: str, exclude_run_id: str | None = None) -> EvaluationRun | None:
        runs = await self._run_repo.list_all(limit=50)
        for run in runs:
            if run.dataset_name != dataset_name or run.collection_id != collection_id:
                continue
            if exclude_run_id and run.id == exclude_run_id:
                continue
            return run
        return None

    @staticmethod
    def _aggregate(cases: list[EvaluationCaseResult]) -> dict[str, float | int | str]:
        if not cases:
            return {
                "case_count": 0,
                "retrieval_recall_at_k": 0.0,
                "retrieval_mrr": 0.0,
                "retrieval_ndcg": 0.0,
                "answer_grounding_score": 0.0,
                "answer_relevance_score": 0.0,
                "answer_support_coverage": 0.0,
                "answer_citation_coverage": 0.0,
                "answer_overall_score": 0.0,
                "benchmark_pass_rate": 0.0,
            }
        count = len(cases)
        benchmark_passes = sum(
            1
            for case in cases
            if case.answer_metrics["overall"] >= 0.7 and case.answer_metrics["grounding"] >= 0.7
        )
        return {
            "case_count": count,
            "retrieval_recall_at_k": round(sum(case.retrieval_metrics["recall_at_k"] for case in cases) / count, 3),
            "retrieval_mrr": round(sum(case.retrieval_metrics["mrr"] for case in cases) / count, 3),
            "retrieval_ndcg": round(sum(case.retrieval_metrics["ndcg"] for case in cases) / count, 3),
            "answer_grounding_score": round(sum(case.answer_metrics["grounding"] for case in cases) / count, 3),
            "answer_relevance_score": round(sum(case.answer_metrics["relevance"] for case in cases) / count, 3),
            "answer_support_coverage": round(sum(case.answer_metrics["support_coverage"] for case in cases) / count, 3),
            "answer_citation_coverage": round(sum(case.answer_metrics["citation_coverage"] for case in cases) / count, 3),
            "answer_overall_score": round(sum(case.answer_metrics["overall"] for case in cases) / count, 3),
            "benchmark_pass_rate": round(benchmark_passes / count, 3),
        }
