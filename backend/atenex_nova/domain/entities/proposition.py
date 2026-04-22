"""Proposition entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Proposition:
    """Atomic claim extracted from a chunk."""

    id: str
    document_id: str
    source_chunk_id: str
    text: str
    kind: str = "fact"
    embedding_ref: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
