"""Query entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Query:
    """User query persisted for tracing and analytics."""

    id: str
    collection_id: str
    text: str
    normalized_text: str = ""
    language: str = "auto"
    intent: str = "factual"
    route_mode: str = "factual_local"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def switch_route(self, new_mode: str) -> None:
        self.route_mode = new_mode
