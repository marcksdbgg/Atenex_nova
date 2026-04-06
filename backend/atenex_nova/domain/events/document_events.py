"""Domain events."""
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DomainEvent:
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DocumentRegistered(DomainEvent):
    document_id: str = ""
    collection_id: str = ""


@dataclass
class DocumentParsed(DomainEvent):
    document_id: str = ""


@dataclass
class DocumentIndexed(DomainEvent):
    document_id: str = ""


@dataclass
class DocumentFailed(DomainEvent):
    document_id: str = ""
    reason: str = ""
