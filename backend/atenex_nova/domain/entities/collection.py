"""Atenex Nova — Domain entity: Collection."""

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class Collection:
    """Represents a logical corpus / document collection.

    A collection groups related documents and defines default profiles
    for embedding and generation within that corpus.
    """

    id: str
    name: str
    description: str = ""
    language_profile: str = "auto"
    default_generation_profile: str = "standard"
    default_retrieval_profile: str = "standard"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def rename(self, new_name: str) -> None:
        """Rename the collection."""
        if not new_name.strip():
            raise ValueError("Collection name cannot be empty")
        self.name = new_name.strip()
        self.updated_at = datetime.now(UTC)

    def update_profiles(
        self,
        generation_profile: str | None = None,
        retrieval_profile: str | None = None,
    ) -> None:
        """Update generation and/or retrieval profiles."""
        if generation_profile is not None:
            self.default_generation_profile = generation_profile
        if retrieval_profile is not None:
            self.default_retrieval_profile = retrieval_profile
        self.updated_at = datetime.now(UTC)
