"""Evidence item entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class EvidenceItem:
    """Retrieved evidence used to build a response pack."""

    id: str
    query_id: str
    source_type: str
    source_id: str
    score: float
    rank: int
    document_id: str | None = None
    page_number: int | None = None
    title: str = ""
    snippet: str = ""
    citation_candidate: bool = True
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
