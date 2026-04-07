"""Evaluation domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(slots=True)
class GoldenCase:
    id: str
    category: str
    question: str
    expected_answer: str
    expected_keywords: list[str]
    route_mode: str
    mode: str = "auto"


@dataclass(slots=True)
class GoldenSet:
    name: str
    description: str
    cases: list[GoldenCase] = field(default_factory=list)


@dataclass(slots=True)
class EvaluationCaseResult:
    id: str
    category: str
    question: str
    expected_answer: str
    expected_keywords: list[str]
    route_mode: str
    retrieval_metrics: dict[str, float]
    answer_metrics: dict[str, float]
    retrieved: list[dict[str, str]]
    answer_id: str | None = None


@dataclass(slots=True)
class EvaluationRun:
    id: str
    dataset_name: str
    collection_id: str
    retrieval_recall_at_k: float
    retrieval_mrr: float
    retrieval_ndcg: float
    answer_grounding_score: float
    answer_relevance_score: float
    regression_delta: dict[str, float]
    summary: dict[str, float | int | str]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
