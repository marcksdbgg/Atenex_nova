"""Relation edge entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class RelationEdge:
    """Semantic relation between two graph nodes."""

    id: str
    source_type: str
    source_id: str
    target_type: str
    target_id: str
    relation: str
    weight: float = 1.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
