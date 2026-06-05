"""Chat and ChatMessage domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Chat:
    """Chat thread associated with a collection."""

    id: str
    collection_id: str
    title: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ChatMessage:
    """Single message inside a chat thread."""

    id: str
    chat_id: str
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
