"""Answer entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Answer:
    """Final answer persisted after generation and verification."""

    id: str
    query_id: str
    plan_type: str
    text: str
    grounding_score: float = 0.0
    verdict: str = "unverified"
    prompt_version: str = "v1"
    draft_text: str = ""
    verification_issues: list[str] = field(default_factory=list)
    evidence_trace: dict[str, object] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
