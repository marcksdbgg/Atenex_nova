"""Presentation DTOs — Pydantic models for API request/response."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Collection ---
class CreateCollectionRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    language_profile: str = "auto"


class UpdateCollectionRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    generation_profile: str | None = None
    retrieval_profile: str | None = None


class CollectionResponse(BaseModel):
    id: str
    name: str
    description: str
    language_profile: str
    default_generation_profile: str
    default_retrieval_profile: str
    created_at: datetime
    updated_at: datetime


# --- Document ---
class DocumentResponse(BaseModel):
    id: str
    collection_id: str
    title: str
    mime_type: str
    source_path: str | None = None
    collection_path: str = ""
    status: str
    language: str
    version: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


class ImportLocalDocumentRequest(BaseModel):
    source_path: str = Field(min_length=1, max_length=1000)
    title: str | None = Field(default=None, max_length=255)
    mime_type: str | None = Field(default=None, max_length=255)
    collection_path: str | None = Field(default=None, max_length=800)


class ImportLocalFolderRequest(BaseModel):
    source_folder: str = Field(min_length=1, max_length=1000)
    collection_path: str | None = Field(default=None, max_length=800)
    recursive: bool = True


class ImportLocalFolderResponse(BaseModel):
    imported: int
    source_folder: str
    collection_path: str
    document_ids: list[str]


class DocumentNodeResponse(BaseModel):
    id: str
    document_id: str
    node_type: str
    raw_text: str
    normalized_text: str
    parent_id: str | None = None
    page_number: int | None = None
    order_index: int
    metadata_json: str | None = None

# --- Job ---
class JobResponse(BaseModel):
    id: str
    job_type: str
    target_id: str
    status: str
    error: str | None = None
    retries: int
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


# --- Query ---
class SearchRequest(BaseModel):
    collection_id: str
    query: str = Field(min_length=1)
    mode: str = "auto"


class AskRequest(BaseModel):
    collection_id: str
    query: str = Field(min_length=1)
    mode: str = "auto"
    generation_profile: str = "standard"


class QueryHitResponse(BaseModel):
    id: str
    source_type: str
    source_id: str
    document_id: str | None = None
    title: str
    snippet: str
    score: float
    rank: int
    page_number: int | None = None
    metadata: dict[str, str] | None = None


class QuerySearchResponse(BaseModel):
    query_id: str
    collection_id: str
    query: str
    normalized_query: str
    language: str
    intent: str
    route_mode: str
    total_hits: int
    hits: list[QueryHitResponse]


class QueryHistoryResponse(BaseModel):
    query_id: str
    answer_id: str | None = None
    collection_id: str
    query: str
    answer: str | None = None
    route_mode: str
    intent: str
    language: str
    verdict: str | None = None
    grounding_score: float | None = None
    created_at: datetime
    citations_count: int = 0


class CitationResponse(BaseModel):
    id: str
    answer_id: str
    document_id: str
    page_number: int | None = None
    node_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    snippet: str


class AnswerResponse(BaseModel):
    answer_id: str
    query_id: str
    collection_id: str
    query: str
    normalized_query: str
    language: str
    intent: str
    route_mode: str
    plan_type: str
    answer: str
    verdict: str
    grounding_score: float
    citations: list[CitationResponse]
    evidence: list[QueryHitResponse]


class EvaluationRunRequest(BaseModel):
    collection_id: str
    dataset_name: str = "baseline"


class EvaluationCaseResponse(BaseModel):
    id: str
    category: str
    question: str
    expected_answer: str
    expected_keywords: list[str]
    route_mode: str
    retrieval_metrics: dict[str, float]
    answer_metrics: dict[str, float]
    retrieved: list[dict[str, str | float]]
    answer_id: str | None = None


class EvaluationRunResponse(BaseModel):
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
    created_at: datetime

    @classmethod
    def from_run(cls, run) -> "EvaluationRunResponse":
        return cls(
            id=run.id,
            dataset_name=run.dataset_name,
            collection_id=run.collection_id,
            retrieval_recall_at_k=run.retrieval_recall_at_k,
            retrieval_mrr=run.retrieval_mrr,
            retrieval_ndcg=run.retrieval_ndcg,
            answer_grounding_score=run.answer_grounding_score,
            answer_relevance_score=run.answer_relevance_score,
            regression_delta=run.regression_delta,
            summary=run.summary,
            created_at=run.created_at,
        )


class EvaluationReportResponse(EvaluationRunResponse):
    previous_run_id: str | None = None
    cases: list[EvaluationCaseResponse]

    @classmethod
    def from_report(cls, report) -> "EvaluationReportResponse":
        return cls(
            **EvaluationRunResponse.from_run(report.run).model_dump(),
            previous_run_id=report.previous_run_id,
            cases=[
                EvaluationCaseResponse(
                    id=case.id,
                    category=case.category,
                    question=case.question,
                    expected_answer=case.expected_answer,
                    expected_keywords=case.expected_keywords,
                    route_mode=case.route_mode,
                    retrieval_metrics=case.retrieval_metrics,
                    answer_metrics=case.answer_metrics,
                    retrieved=case.retrieved,
                    answer_id=case.answer_id,
                )
                for case in report.cases
            ],
        )


# --- Common ---
class PaginatedResponse(BaseModel):
    items: list
    total: int
    offset: int
    limit: int


class ErrorResponse(BaseModel):
    code: str
    message: str


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class PipelineAuditResponse(BaseModel):
    id: str
    run_id: str
    entity_type: str
    entity_id: str
    pipeline: str
    stage: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = None
    metrics: dict[str, object]
    context: dict[str, object]


class DocumentEvidenceResponse(BaseModel):
    entity_type: str = "document"
    entity_id: str
    document: DocumentResponse
    jobs: list[JobResponse] = Field(default_factory=list)
    audit_events: list[PipelineAuditResponse] = Field(default_factory=list)
