"""Citation entity."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Citation:
    """Exact span citation attached to an answer."""

    id: str
    answer_id: str
    document_id: str
    page_number: int | None = None
    node_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    snippet: str = ""
    bbox: dict[str, object] | None = None
    heading_path: list[str] = field(default_factory=list)
    page_asset_path: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
