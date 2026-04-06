"""Summary node entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class SummaryNode:
    """Hierarchical summary for a section, document or collection."""

    id: str
    scope_type: str
    scope_id: str
    text: str
    embedding_ref: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))