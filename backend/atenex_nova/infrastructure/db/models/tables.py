"""Atenex Nova SQLModel ORM tables."""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, LargeBinary
from sqlmodel import Column, Field, SQLModel, Text


class CollectionModel(SQLModel, table=True):
    __tablename__ = "collections"
    id: str = Field(primary_key=True, max_length=36)
    name: str = Field(max_length=255, index=True)
    description: str = Field(default="", sa_column=Column(Text))
    language_profile: str = Field(default="auto", max_length=50)
    default_generation_profile: str = Field(default="standard", max_length=50)
    default_retrieval_profile: str = Field(default="standard", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentModel(SQLModel, table=True):
    __tablename__ = "documents"
    id: str = Field(primary_key=True, max_length=36)
    collection_id: str = Field(max_length=36, index=True)
    title: str = Field(max_length=500)
    source_path: str = Field(max_length=1000)
    collection_path: str = Field(default="", max_length=800, index=True)
    mime_type: str = Field(max_length=100)
    checksum: str = Field(max_length=64)
    status: str = Field(default="registered", max_length=20, index=True)
    language: str = Field(default="auto", max_length=20)
    version: int = Field(default=1)
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DocumentNodeModel(SQLModel, table=True):
    __tablename__ = "document_nodes"
    id: str = Field(primary_key=True, max_length=36)
    document_id: str = Field(max_length=36, index=True)
    parent_id: str | None = Field(default=None, max_length=36)
    node_type: str = Field(max_length=30)
    page_number: int | None = Field(default=None)
    order_index: int = Field(default=0)
    raw_text: str = Field(default="", sa_column=Column(Text))
    normalized_text: str = Field(default="", sa_column=Column(Text))
    bbox_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    metadata_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class ChunkModel(SQLModel, table=True):
    __tablename__ = "retrieval_chunks"
    id: str = Field(primary_key=True, max_length=36)
    document_id: str = Field(max_length=36, index=True)
    summary: str = Field(default="", sa_column=Column(Text))
    text: str = Field(sa_column=Column(Text))
    token_count: int = Field(default=0)
    node_ids_json: str = Field(default="[]", sa_column=Column(Text))
    embedding_ref: str | None = Field(default=None, max_length=100)
    sparse_ref: str | None = Field(default=None, max_length=100)
    metadata_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class PropositionModel(SQLModel, table=True):
    __tablename__ = "propositions"
    id: str = Field(primary_key=True, max_length=36)
    document_id: str = Field(max_length=36, index=True)
    source_chunk_id: str = Field(max_length=36)
    text: str = Field(sa_column=Column(Text))
    kind: str = Field(max_length=30)
    embedding_ref: str | None = Field(default=None, max_length=100)


class SummaryNodeModel(SQLModel, table=True):
    __tablename__ = "summary_nodes"
    id: str = Field(primary_key=True, max_length=36)
    scope_type: str = Field(max_length=30)
    scope_id: str = Field(max_length=36, index=True)
    text: str = Field(sa_column=Column(Text))
    provenance_json: str = Field(default="{}", sa_column=Column(Text))
    embedding_ref: str | None = Field(default=None, max_length=100)


class RelationEdgeModel(SQLModel, table=True):
    __tablename__ = "relation_edges"
    id: str = Field(primary_key=True, max_length=36)
    source_type: str = Field(max_length=30)
    source_id: str = Field(max_length=36, index=True)
    target_type: str = Field(max_length=30)
    target_id: str = Field(max_length=36, index=True)
    relation: str = Field(max_length=30)
    weight: float = Field(default=1.0)


class QueryModel(SQLModel, table=True):
    __tablename__ = "queries"
    id: str = Field(primary_key=True, max_length=36)
    collection_id: str = Field(max_length=36, index=True)
    original_text: str = Field(sa_column=Column(Text))
    normalized_text: str = Field(default="", sa_column=Column(Text))
    language: str = Field(default="auto", max_length=20)
    intent: str | None = Field(default=None, max_length=30)
    route_mode: str | None = Field(default=None, max_length=30)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AnswerModel(SQLModel, table=True):
    __tablename__ = "answers"
    id: str = Field(primary_key=True, max_length=36)
    query_id: str = Field(max_length=36, index=True)
    plan_type: str = Field(max_length=50)
    text: str = Field(sa_column=Column(Text))
    grounding_score: float = Field(default=0.0)
    verdict: str = Field(default="unverified", max_length=30)
    prompt_version: str = Field(default="v1", max_length=50)
    draft_text: str = Field(default="", sa_column=Column(Text))
    verification_issues_json: str = Field(default="[]", sa_column=Column(Text))
    evidence_trace_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    full_prompt: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    input_token_count: int | None = Field(default=None)
    output_token_count: int | None = Field(default=None)
    chat_history_used: bool | None = Field(default=None)
    chat_history_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class CitationModel(SQLModel, table=True):
    __tablename__ = "citations"
    id: str = Field(primary_key=True, max_length=36)
    answer_id: str = Field(max_length=36, index=True)
    document_id: str = Field(max_length=36)
    page_number: int | None = Field(default=None)
    node_id: str | None = Field(default=None, max_length=36)
    char_start: int | None = Field(default=None)
    char_end: int | None = Field(default=None)
    snippet: str = Field(default="", sa_column=Column(Text))
    bbox_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    heading_path_json: str = Field(default="[]", sa_column=Column(Text))
    page_asset_path: str | None = Field(default=None, max_length=1000)


class JobModel(SQLModel, table=True):
    __tablename__ = "jobs"
    id: str = Field(primary_key=True, max_length=36)
    job_type: str = Field(max_length=50, index=True)
    target_id: str = Field(max_length=36, index=True)
    status: str = Field(default="pending", max_length=20, index=True)
    payload_json: str = Field(default="{}", sa_column=Column(Text))
    result_json: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    retries: int = Field(default=0)
    max_retries: int = Field(default=3)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)


class EvaluationRunModel(SQLModel, table=True):
    __tablename__ = "evaluation_runs"
    id: str = Field(primary_key=True, max_length=36)
    dataset_name: str = Field(max_length=100, index=True)
    collection_id: str = Field(max_length=36, index=True)
    status: str = Field(default="completed", max_length=20, index=True)
    retrieval_recall_at_k: float = Field(default=0.0)
    retrieval_mrr: float = Field(default=0.0)
    retrieval_ndcg: float = Field(default=0.0)
    answer_grounding_score: float = Field(default=0.0)
    answer_relevance_score: float = Field(default=0.0)
    regression_delta_json: str = Field(default="{}", sa_column=Column(Text))
    summary_json: str = Field(default="{}", sa_column=Column(Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class EvaluationCaseModel(SQLModel, table=True):
    __tablename__ = "evaluation_cases"
    id: str = Field(primary_key=True, max_length=36)
    run_id: str = Field(max_length=36, index=True)
    category: str = Field(max_length=50, index=True)
    question: str = Field(sa_column=Column(Text))
    expected_answer: str = Field(sa_column=Column(Text))
    expected_keywords_json: str = Field(default="[]", sa_column=Column(Text))
    route_mode: str = Field(max_length=30)
    retrieval_metrics_json: str = Field(default="{}", sa_column=Column(Text))
    answer_metrics_json: str = Field(default="{}", sa_column=Column(Text))
    retrieved_json: str = Field(default="[]", sa_column=Column(Text))
    answer_id: str | None = Field(default=None, max_length=36)


class PipelineAuditModel(SQLModel, table=True):
    __tablename__ = "pipeline_audit_events"

    id: str = Field(primary_key=True, max_length=36)
    run_id: str = Field(max_length=36, index=True)
    entity_type: str = Field(max_length=30, index=True)
    entity_id: str = Field(max_length=36, index=True)
    pipeline: str = Field(max_length=50, index=True)
    stage: str = Field(max_length=80, index=True)
    status: str = Field(max_length=20, index=True)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = Field(default=None)
    duration_ms: float | None = Field(default=None)
    metrics_json: str = Field(default="{}", sa_column=Column(Text))
    context_json: str = Field(default="{}", sa_column=Column(Text))


class ChatModel(SQLModel, table=True):
    __tablename__ = "chats"
    id: str = Field(primary_key=True, max_length=36)
    collection_id: str = Field(max_length=36, index=True)
    title: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ChatMessageModel(SQLModel, table=True):
    __tablename__ = "chat_messages"
    id: str = Field(primary_key=True, max_length=36)
    chat_id: str = Field(max_length=36, index=True)
    role: str = Field(max_length=20)
    content: str = Field(sa_column=Column(Text))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QuantizationProfileModel(SQLModel, table=True):
    __tablename__ = "quantization_profiles"
    id: str = Field(primary_key=True, max_length=36)
    algorithm: str = Field(default="turboquant_prod", max_length=50)
    embedding_model: str = Field(max_length=255)
    dimension: int = Field()
    bit_width: int = Field(default=4)
    rotation_seed: int = Field(default=42)
    qjl_seed: int = Field(default=1337)
    codebook_version: str = Field(default="v1", max_length=50)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QuantizedVectorModel(SQLModel, table=True):
    __tablename__ = "quantized_vectors"
    id: str = Field(primary_key=True, max_length=36)
    node_id: str = Field(max_length=36, index=True)
    uint64_id: int = Field(sa_column=Column(BigInteger, index=True))
    tenant_id: str = Field(default="", max_length=36, index=True)
    collection_id: str = Field(max_length=36, index=True)
    memory_layer: str = Field(
        max_length=30, index=True
    )  # "chunk" | "proposition" | "summary" | "visual"
    profile_id: str = Field(max_length=36, index=True)
    idx_blob: bytes = Field(sa_column=Column(LargeBinary))
    qjl_blob: bytes = Field(sa_column=Column(LargeBinary))
    residual_norm: float = Field(default=0.0)
    vector_norm: float = Field(default=1.0)
    deleted_at: datetime | None = Field(default=None, nullable=True)
    version: int = Field(default=1)


class ImportSessionModel(SQLModel, table=True):
    __tablename__ = "import_sessions"

    id: str = Field(primary_key=True, max_length=36)
    collection_id: str = Field(max_length=36, index=True)
    source_kind: str = Field(max_length=30, index=True)
    source_root: str = Field(default="", max_length=1000)
    collection_path: str = Field(default="", max_length=800)
    status: str = Field(default="running", max_length=30, index=True)
    discovered_count: int = Field(default=0)
    attempted_count: int = Field(default=0)
    created_count: int = Field(default=0)
    deduplicated_count: int = Field(default=0)
    skipped_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    queued_jobs_count: int = Field(default=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = Field(default=None)
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))


class ImportSessionItemModel(SQLModel, table=True):
    __tablename__ = "import_session_items"

    id: str = Field(primary_key=True, max_length=36)
    session_id: str = Field(max_length=36, index=True)
    relative_path: str = Field(default="", max_length=800)
    source_path: str = Field(default="", max_length=1000)
    checksum: str | None = Field(default=None, max_length=64)
    mime_type: str | None = Field(default=None, max_length=100)
    status: str = Field(max_length=20, index=True)
    document_id: str | None = Field(default=None, max_length=36, index=True)
    job_id: str | None = Field(default=None, max_length=36)
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
