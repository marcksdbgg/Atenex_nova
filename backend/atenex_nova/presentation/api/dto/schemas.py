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
    status: str
    language: str
    version: int
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime


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
