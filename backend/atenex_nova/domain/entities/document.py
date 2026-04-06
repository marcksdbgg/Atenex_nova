"""Atenex Nova — Domain entity: Document."""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from atenex_nova.domain.value_objects.identifiers import (
    VALID_TRANSITIONS,
    DocumentStatus,
)
from atenex_nova.shared.exceptions.base import InvalidStateTransitionError


@dataclass
class Document:
    """Represents a source file and its lifecycle.

    A document goes through a state machine:
    registered → parsed → normalized → segmented → embedded → indexed → ready
    Any state can transition to 'failed'.
    """

    id: str
    collection_id: str
    title: str
    source_path: str
    mime_type: str
    checksum: str
    status: DocumentStatus = DocumentStatus.REGISTERED
    language: str = "auto"
    version: int = 1
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def _transition_to(self, target: DocumentStatus) -> None:
        """Transition document to a new status with validation."""
        valid = VALID_TRANSITIONS.get(self.status, set())
        if target not in valid:
            raise InvalidStateTransitionError(
                entity_type="Document",
                current=self.status.value,
                target=target.value,
            )
        self.status = target
        self.updated_at = datetime.now(timezone.utc)
        if target != DocumentStatus.FAILED:
            self.error_message = None

    def mark_parsed(self) -> None:
        """Mark document as successfully parsed."""
        self._transition_to(DocumentStatus.PARSED)

    def mark_normalized(self) -> None:
        """Mark document as normalized."""
        self._transition_to(DocumentStatus.NORMALIZED)

    def mark_segmented(self) -> None:
        """Mark document as segmented into chunks."""
        self._transition_to(DocumentStatus.SEGMENTED)

    def mark_embedded(self) -> None:
        """Mark document as embedded."""
        self._transition_to(DocumentStatus.EMBEDDED)

    def mark_indexed(self) -> None:
        """Mark document as indexed in vector DB."""
        self._transition_to(DocumentStatus.INDEXED)

    def mark_ready(self) -> None:
        """Mark document as ready for querying."""
        self._transition_to(DocumentStatus.READY)

    def fail(self, reason: str) -> None:
        """Mark document as failed with an error reason."""
        self.status = DocumentStatus.FAILED
        self.error_message = reason
        self.updated_at = datetime.now(timezone.utc)

    @property
    def is_queryable(self) -> bool:
        """Check if document is ready for queries."""
        return self.status == DocumentStatus.READY
