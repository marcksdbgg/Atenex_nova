"""Query DTOs."""

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    collection_id: str
    query: str = Field(min_length=1)
    mode: str = "auto"


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
