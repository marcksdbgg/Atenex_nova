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
