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
    retrieval_text: str = field(default="", repr=False, compare=False)
    retrieval_context_messages: int = field(default=0, repr=False, compare=False)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def retrieval_query(self) -> str:
        """Return transient retrieval text without changing the persisted user query."""
        return self.retrieval_text or self.normalized_text or self.text

    def switch_route(self, new_mode: str) -> None:
        self.route_mode = new_mode
